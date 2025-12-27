"""
Recovery Ramp Engine (Phase 5H)
--------------------------------

Evaluates recovery conditions and determines if limited recovery trading
can be allowed during halt_new_entries or de_risk modes.

Safety:
- Restrictive-only (never enables exploit/probe directly)
- Never overrides CapitalProtection
- Deterministic and auditable
- Hysteresis-based (requires stable signals)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

from engine_alpha.core.paths import REPORTS, CONFIG
from engine_alpha.reflect.trade_sanity import is_close_like_event, get_close_return_pct

# Paths
CAPITAL_PROTECTION_PATH = REPORTS / "risk" / "capital_protection.json"
PF_TIMESERIES_PATH = REPORTS / "pf" / "pf_timeseries.json"
PF_TIMESERIES_ALT_PATH = REPORTS / "pf_timeseries.json"
QUARANTINE_PATH = REPORTS / "risk" / "quarantine.json"
TRADES_PATH = REPORTS / "trades.jsonl"
LIVE_CANDIDATES_PATH = REPORTS / "risk" / "live_candidates.json"
EXECUTION_QUALITY_PATH = REPORTS / "research" / "execution_quality.json"
CAPITAL_PLAN_PATH = REPORTS / "risk" / "capital_plan.json"
RECOVERY_RAMP_STATE_PATH = REPORTS / "risk" / "recovery_ramp.json"

# Thresholds
PF7D_FLOOR_TO_RAMP = 0.95
PF7D_FLOOR_TO_DERISK = 0.90
PF7D_FLOOR_TO_NORMAL = 0.95
PF7D_SLOPE_MIN = 0.0005  # Minimum positive slope to consider "improving"
# Minimum valid closes (clean = non-corrupt) in last 24h; overridden by config/engine_config.json
MIN_CLEAN_CLOSES = 6
MAX_RECENT_LOSS_CLOSES = 6  # Block ramp if too many losses
NEEDED_OK_TICKS = 6  # Hysteresis: 6 consecutive OK ticks (~30 min at 5m cadence)
MIN_RECOVERY_SCORE = 0.65  # Minimum recovery score to allow trading


def _load_json(path: Path) -> Dict[str, Any]:
    """Safely load JSON file."""
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_json(path: Path, data: Dict[str, Any]) -> None:
    """Safely save JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def _load_engine_config() -> Dict[str, Any]:
    """Load engine_config.json (best-effort)."""
    cfg_path = CONFIG / "engine_config.json"
    if not cfg_path.exists():
        return {}
    try:
        with cfg_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _parse_timestamp(ts_str: str) -> datetime:
    """Parse ISO timestamp."""
    try:
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def _load_pf_timeseries() -> Dict[str, Any]:
    """Load PF timeseries with fallbacks."""
    # Try primary path first
    if PF_TIMESERIES_PATH.exists():
        return _load_json(PF_TIMESERIES_PATH)
    
    # Try alternate path
    if PF_TIMESERIES_ALT_PATH.exists():
        return _load_json(PF_TIMESERIES_ALT_PATH)
    
    return {}


def _compute_pf_metrics(pf_timeseries: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    """Compute PF metrics from timeseries."""
    result = {
        "pf_7d": None,
        "pf_30d": None,
        "pf_7d_slope": None,
        "pf_timeseries_age_minutes": None,
        "data_fresh": False,
        "insufficient_history": False,
    }
    
    if not pf_timeseries:
        return result
    
    # Check data freshness first (from meta.generated_at)
    meta = pf_timeseries.get("meta", {})
    generated_at_str = meta.get("generated_at") or pf_timeseries.get("generated_at")
    
    if generated_at_str:
        try:
            gen_time = _parse_timestamp(generated_at_str)
            age_minutes = (now - gen_time).total_seconds() / 60
            result["pf_timeseries_age_minutes"] = age_minutes
            result["data_fresh"] = age_minutes < 90  # <90 minutes old
        except Exception:
            result["pf_timeseries_age_minutes"] = None
            result["data_fresh"] = False
    else:
        result["data_fresh"] = False
    
    # Try to get global PF values (multiple possible structures)
    global_pf = (
        pf_timeseries.get("global", {}) or
        pf_timeseries.get("metrics", {}) or
        pf_timeseries.get("summary", {}) or
        {}
    )
    
    # Try multiple field names and structures
    # Structure 1: global.pf_7d, global.pf_30d
    pf_7d = (
        global_pf.get("pf_7d") or
        global_pf.get("pf_7d_display") or
        global_pf.get("pf_7D") or
        pf_timeseries.get("pf_7d") or
        pf_timeseries.get("pf_7d_display")
    )
    pf_30d = (
        global_pf.get("pf_30d") or
        global_pf.get("pf_30d_display") or
        global_pf.get("pf_30D") or
        pf_timeseries.get("pf_30d") or
        pf_timeseries.get("pf_30d_display")
    )
    
    # Structure 2: global.7d.pf, global.30d.pf (actual structure)
    if pf_7d is None:
        pf_7d_window = global_pf.get("7d", {}) or global_pf.get("7D", {})
        if pf_7d_window:
            pf_7d = pf_7d_window.get("pf")
    
    if pf_30d is None:
        pf_30d_window = global_pf.get("30d", {}) or global_pf.get("30D", {})
        if pf_30d_window:
            pf_30d = pf_30d_window.get("pf")
    
    result["pf_7d"] = pf_7d
    result["pf_30d"] = pf_30d
    
    # Compute PF_7D slope (properly normalized)
    # Since pf_timeseries.json doesn't store historical snapshots, we compute
    # a trend slope from the difference between 7d and 30d windows.
    # The 7d window represents recent performance, 30d represents longer-term.
    # Slope = (PF_7D - PF_30D) / time_delta
    # Time delta: 7d window is ~7 days ago to now, 30d is ~30 days ago to now
    # Effective time difference: ~23 days (30 - 7)
    # Normalize to per-hour: (PF_7D - PF_30D) / (23 days * 24 hours/day)
    if pf_7d is not None and pf_30d is not None:
        # Compute normalized slope (PF change per hour)
        # Time difference between midpoints: (30 - 7) / 2 = 11.5 days
        # But we want the rate of change, so use the full window difference
        days_delta = 23.0  # 30d - 7d window difference
        hours_delta = days_delta * 24.0
        
        raw_slope = (pf_7d - pf_30d) / hours_delta
        
        # Clamp to reasonable range [-0.2, +0.2] per hour
        # (this prevents extreme values from numerical issues)
        result["pf_7d_slope"] = max(-0.2, min(0.2, raw_slope))
    else:
        result["insufficient_history"] = True
        result["pf_7d_slope"] = 0.0
    
    return result


def _load_recent_closes(now: datetime, window_hours: int = 24) -> Tuple[int, int, Optional[str]]:
    """Load recent closes from trades.jsonl.
    
    Returns:
        (clean_closes, loss_closes, last_close_ts)
        
    Clean close definition (validity-focused):
      - close-like event (type/event in {"close","exit"})
      - entry_px present and valid (not None/0/1.0, entry_px_invalid not True)
      - exit_px present and valid
      - pct finite (NaN/inf discarded)
      - scratches (pct == 0) count as clean if valid
      - losses count as clean (they are tracked separately in loss_closes)
    """
    if not TRADES_PATH.exists():
        return 0, 0, None
    
    cutoff = now - timedelta(hours=window_hours)
    clean_closes = 0
    loss_closes = 0
    last_close_ts = None
    
    try:
        with TRADES_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trade = json.loads(line)
                    # Canonical close detection (event/type)
                    if not is_close_like_event(trade):
                        continue
                    
                    ts_str = trade.get("ts") or trade.get("timestamp") or trade.get("time")
                    if not ts_str:
                        continue
                    
                    trade_time = _parse_timestamp(ts_str)
                    if trade_time < cutoff:
                        continue
                    
                    if last_close_ts is None or trade_time > _parse_timestamp(last_close_ts):
                        last_close_ts = ts_str
                    
                    # Validate entry/exit prices
                    entry_px = trade.get("entry_px")
                    exit_px = trade.get("exit_px")
                    entry_invalid_flag = trade.get("entry_px_invalid") is True
                    try:
                        entry_px_val = float(entry_px) if entry_px is not None else None
                        exit_px_val = float(exit_px) if exit_px is not None else None
                    except Exception:
                        continue
                    if entry_invalid_flag:
                        continue
                    if entry_px_val is None or exit_px_val is None:
                        continue
                    if entry_px_val == 0.0 or exit_px_val == 0.0:
                        continue
                    if abs(entry_px_val - 1.0) < 1e-12:
                        continue  # treat 1.0 sentinel as invalid
                    
                    # Use canonical pct extractor
                    pct = get_close_return_pct(trade)
                    if pct is None:
                        continue
                    try:
                        pct_val = float(pct)
                    except Exception:
                        continue
                    if not (float("-inf") < pct_val < float("inf")):
                        continue
                    
                    # Loss tracking
                    if pct_val < -0.001:
                        loss_closes += 1
                        clean_closes += 1  # losses count as clean if data is valid
                    elif pct_val > 0.001:
                        clean_closes += 1
                    else:
                        # scratches and near-zero/fees count as clean if valid
                        clean_closes += 1
                except Exception:
                    continue
    except Exception:
        pass
    
    return clean_closes, loss_closes, last_close_ts


def _get_allowed_symbols(
    capital_plan: Dict[str, Any],
    live_candidates: Dict[str, Any],
    quarantine: Dict[str, Any],
    execution_quality: Dict[str, Any],
) -> List[str]:
    """Get allowed symbols for recovery trading."""
    allowed = []
    
    # Get quarantined symbols
    quarantined = set(quarantine.get("blocked_symbols", []))
    
    # Get symbol data
    by_symbol_plan = capital_plan.get("by_symbol", {}) or capital_plan.get("symbols", {})
    by_symbol_live = live_candidates.get("by_symbol", {}) or live_candidates.get("symbols", {})
    
    candidates = []
    
    for symbol, plan_data in by_symbol_plan.items():
        # Skip quarantined
        if symbol in quarantined:
            continue
        
        # Check tier (prefer tier1, allow tier2)
        tier = plan_data.get("tier", "tier3")
        if tier not in ("tier1", "tier2"):
            continue
        
        # Check ready_now
        live_data = by_symbol_live.get(symbol, {})
        ready_now_val = live_data.get("ready_now")
        if not ready_now_val or str(ready_now_val).upper() not in ("Y", "YES", "TRUE", "1"):
            continue
        
        # Check execution quality (if available)
        exec_data = execution_quality.get("data", {}).get(symbol, {}) or \
                   execution_quality.get("symbols", {}).get(symbol, {})
        exec_label = exec_data.get("summary", {}).get("overall_label") or \
                    exec_data.get("overall_label")
        if exec_label == "hostile":
            continue
        
        # Get weight for sorting
        weight = plan_data.get("weight", 0.0) or plan_data.get("capital_weight", 0.0)
        
        candidates.append({
            "symbol": symbol,
            "tier": tier,
            "weight": weight,
        })
    
    # Sort by tier (tier1 first), then weight (descending)
    candidates.sort(key=lambda x: (0 if x["tier"] == "tier1" else 1, -x["weight"]))
    
    return [c["symbol"] for c in candidates]


def evaluate_recovery_ramp(now_iso: Optional[str] = None) -> Dict[str, Any]:
    """
    Evaluate recovery ramp status.
    
    Returns:
        Dict with recovery_mode, recovery_score, gates, metrics, allowances
    """
    now = datetime.now(timezone.utc) if now_iso is None else _parse_timestamp(now_iso)
    
    # Initialize result
    result = {
        "ts": now.isoformat(),
        "capital_mode": "unknown",
        "recovery_mode": "OFF",
        "recovery_score": 0.0,
        "gates": {
            "pf_timeseries_fresh_pass": False,
            "pf7d_floor_pass": False,
            "pf7d_slope_pass": False,
            "clean_closes_pass": False,
            "quarantine_active_pass": False,
            "drawdown_ok_pass": True,  # Default to True (no drawdown data yet)
        },
        "metrics": {
            "pf_7d": None,
            "pf_30d": None,
            "pf_7d_slope": None,
            "recent_clean_closes": 0,
            "recent_loss_closes": 0,
            "last_close_ts": None,
            "quarantined_symbols": [],
        },
        "hysteresis": {
            "ok_ticks": 0,
            "needed_ok_ticks": NEEDED_OK_TICKS,
        },
        "allowances": {
            "allow_recovery_trading": False,
            "allowed_symbols": [],
            "max_positions": 1,
            "risk_mult_cap": 0.25,
        },
        "reason": "",
        "notes": [],
    }
    
    try:
        # Load required data
        capital_protection = _load_json(CAPITAL_PROTECTION_PATH)
        pf_timeseries = _load_pf_timeseries()
        quarantine = _load_json(QUARANTINE_PATH)
        capital_plan = _load_json(CAPITAL_PLAN_PATH)
        live_candidates = _load_json(LIVE_CANDIDATES_PATH)
        execution_quality = _load_json(EXECUTION_QUALITY_PATH)
        
        # Load previous state for hysteresis
        prev_state = _load_json(RECOVERY_RAMP_STATE_PATH)
        prev_ok_ticks = prev_state.get("hysteresis", {}).get("ok_ticks", 0)
        
        # Extract capital mode
        capital_mode = (
            capital_protection.get("mode") or
            capital_protection.get("global", {}).get("mode") or
            "unknown"
        )
        result["capital_mode"] = capital_mode
        
        # Get PF metrics
        pf_metrics = _compute_pf_metrics(pf_timeseries, now)
        result["metrics"]["pf_7d"] = pf_metrics["pf_7d"]
        result["metrics"]["pf_30d"] = pf_metrics["pf_30d"]
        result["metrics"]["pf_7d_slope"] = pf_metrics["pf_7d_slope"]
        result["metrics"]["pf_timeseries_age_minutes"] = pf_metrics["pf_timeseries_age_minutes"]
        result["metrics"]["pf7d_value"] = pf_metrics["pf_7d"]
        
        # Determine clean close threshold (configurable)
        engine_cfg = _load_engine_config()
        min_clean_closes_cfg = engine_cfg.get("recovery_min_clean_closes_24h")
        try:
            min_clean_closes = int(min_clean_closes_cfg) if min_clean_closes_cfg is not None else MIN_CLEAN_CLOSES
        except Exception:
            min_clean_closes = MIN_CLEAN_CLOSES
        if min_clean_closes < 1:
            min_clean_closes = MIN_CLEAN_CLOSES
        min_clean_closes_base = min_clean_closes

        # Option B relief valve: in de_risk only, allow 5 instead of 6 clean closes
        if capital_mode == "de_risk":
            min_clean_closes = min(min_clean_closes, 5)
        min_clean_closes_effective = min_clean_closes

        # Get recent closes
        clean_closes, loss_closes, last_close_ts = _load_recent_closes(now, window_hours=24)
        result["metrics"]["recent_clean_closes"] = clean_closes
        result["metrics"]["recent_loss_closes"] = loss_closes
        result["metrics"]["last_close_ts"] = last_close_ts
        result["metrics"]["min_clean_closes_base"] = min_clean_closes_base
        result["metrics"]["min_clean_closes_required"] = min_clean_closes_effective
        
        # Get quarantined symbols
        quarantined_symbols = quarantine.get("blocked_symbols", [])
        result["metrics"]["quarantined_symbols"] = quarantined_symbols
        
        # Evaluate gates
        pf_7d = pf_metrics["pf_7d"]
        pf_7d_slope = pf_metrics["pf_7d_slope"]
        data_fresh = pf_metrics["data_fresh"]
        pf_age_minutes = pf_metrics["pf_timeseries_age_minutes"]
        
        # Gate 0: PF timeseries freshness (hard gate - must pass)
        pf_timeseries_fresh_pass = data_fresh
        result["gates"]["pf_timeseries_fresh_pass"] = pf_timeseries_fresh_pass
        
        if not pf_timeseries_fresh_pass:
            if pf_age_minutes is not None:
                result["notes"].append(f"PF timeseries stale ({pf_age_minutes:.1f} minutes old)")
            else:
                result["notes"].append("PF timeseries timestamp missing or invalid")
        
        # Gate 1: PF7D floor (only if data is fresh)
        if pf_7d is not None and pf_timeseries_fresh_pass:
            if capital_mode == "halt_new_entries":
                pf7d_floor_pass = pf_7d >= PF7D_FLOOR_TO_RAMP
            elif capital_mode == "de_risk":
                pf7d_floor_pass = pf_7d >= PF7D_FLOOR_TO_DERISK
            else:
                pf7d_floor_pass = pf_7d >= PF7D_FLOOR_TO_NORMAL
        else:
            pf7d_floor_pass = False
            if pf_7d is None:
                result["notes"].append("PF_7D data missing - using core trader PF if available")
        
        result["gates"]["pf7d_floor_pass"] = pf7d_floor_pass
        # Emit explicit floor requirement for visibility
        if capital_mode == "halt_new_entries":
            pf7d_floor_required = PF7D_FLOOR_TO_RAMP
        elif capital_mode == "de_risk":
            pf7d_floor_required = PF7D_FLOOR_TO_DERISK
        else:
            pf7d_floor_required = PF7D_FLOOR_TO_NORMAL
        result["metrics"]["pf7d_floor_required"] = pf7d_floor_required
        
        # Gate 2: PF7D slope (improving) - only if data is fresh
        if pf_7d_slope is not None and pf_timeseries_fresh_pass:
            pf7d_slope_pass = pf_7d_slope >= PF7D_SLOPE_MIN
        else:
            pf7d_slope_pass = False  # Conservative: require slope if data available
        
        result["gates"]["pf7d_slope_pass"] = pf7d_slope_pass
        
        if pf_metrics.get("insufficient_history", False):
            result["notes"].append("Insufficient PF history for slope calculation")
        
        # Gate 3: Clean closes
        clean_closes_pass = clean_closes >= min_clean_closes_effective
        result["gates"]["clean_closes_pass"] = clean_closes_pass
        
        # Gate 4: Not too many recent losses
        loss_closes_pass = loss_closes <= MAX_RECENT_LOSS_CLOSES
        result["gates"]["loss_closes_pass"] = loss_closes_pass
        
        # Gate 5: Quarantine active (if in halt, we want quarantine to have identified loss contributors)
        quarantine_active = quarantine.get("enabled", False) and len(quarantined_symbols) > 0
        if capital_mode == "halt_new_entries":
            # In halt, quarantine should be active (loss contributors identified)
            quarantine_active_pass = quarantine_active
        else:
            # In de_risk/normal, quarantine active is neutral
            quarantine_active_pass = True
        
        result["gates"]["quarantine_active_pass"] = quarantine_active_pass
        
        # Compute recovery score [0, 1]
        # Note: pf_timeseries_fresh_pass is a hard gate (must pass for any score)
        score = 0.0
        
        if not pf_timeseries_fresh_pass:
            # If data is stale, score is 0 (hard gate)
            score = 0.0
        else:
            if pf7d_floor_pass:
                score += 0.30
            
            if pf7d_slope_pass:
                score += 0.20
            
            if clean_closes_pass:
                score += 0.20
            
            if loss_closes_pass:
                score += 0.15
            
            if quarantine_active_pass:
                score += 0.15
        
        result["recovery_score"] = min(1.0, max(0.0, score))
        
        # Determine recovery mode
        all_gates_pass = (
            pf_timeseries_fresh_pass and
            pf7d_floor_pass and
            pf7d_slope_pass and
            clean_closes_pass and
            loss_closes_pass and
            quarantine_active_pass
        )

        failing_gates = [k for k, v in result["gates"].items() if not v]
        gate_details = []
        if not pf_timeseries_fresh_pass:
            gate_details.append("pf_timeseries_fresh_pass=False")
        if not pf7d_floor_pass:
            gate_details.append(
                f"pf7d_floor_pass=False (pf7d={pf_7d}, floor={pf7d_floor_required})"
            )
        if not pf7d_slope_pass:
            gate_details.append(f"pf7d_slope_pass=False (slope={pf_7d_slope})")
        if not clean_closes_pass:
            gate_details.append(
                f"clean_closes_pass=False (clean={clean_closes}, required={min_clean_closes_effective})"
            )
        if not loss_closes_pass:
            gate_details.append(f"loss_closes_pass=False (losses={loss_closes}, max={MAX_RECENT_LOSS_CLOSES})")
        if not quarantine_active_pass and capital_mode == "halt_new_entries":
            gate_details.append("quarantine_active_pass=False (halt_new_entries requires quarantine)")
        gate_details_str = "; ".join(gate_details) if gate_details else ""

        if capital_mode == "normal":
            if all_gates_pass and result["recovery_score"] >= MIN_RECOVERY_SCORE:
                ok_ticks = min(prev_ok_ticks + 1, NEEDED_OK_TICKS)
            else:
                ok_ticks = 0
            result["hysteresis"]["ok_ticks"] = ok_ticks
            result["recovery_mode"] = "READY_FOR_NORMAL"
            base_reason = (
                f"capital_mode=normal; gates={'pass' if all_gates_pass else 'fail'}; "
                f"ticks={ok_ticks}/{NEEDED_OK_TICKS}"
            )
            result["reason"] = base_reason if not gate_details_str else f"{base_reason}; {gate_details_str}"
        elif capital_mode == "de_risk":
            if all_gates_pass and result["recovery_score"] >= MIN_RECOVERY_SCORE:
                ok_ticks = min(prev_ok_ticks + 1, NEEDED_OK_TICKS)
            else:
                ok_ticks = 0
            result["hysteresis"]["ok_ticks"] = ok_ticks
            result["recovery_mode"] = "READY_FOR_DE_RISK"
            base_reason = (
                f"capital_mode=de_risk; gates={'pass' if all_gates_pass else 'fail'}; "
                f"ticks={ok_ticks}/{NEEDED_OK_TICKS}"
            )
            result["reason"] = base_reason if not gate_details_str else f"{base_reason}; {gate_details_str}"
        elif capital_mode == "halt_new_entries":
            if all_gates_pass and result["recovery_score"] >= MIN_RECOVERY_SCORE:
                ok_ticks = min(prev_ok_ticks + 1, NEEDED_OK_TICKS)
                result["hysteresis"]["ok_ticks"] = ok_ticks
                result["recovery_mode"] = "RAMPING"
                if ok_ticks >= NEEDED_OK_TICKS:
                    result["reason"] = (
                        f"all_gates_pass (score={result['recovery_score']:.2f}, ticks={ok_ticks}/{NEEDED_OK_TICKS})"
                        + (f"; {gate_details_str}" if gate_details_str else "")
                    )
                else:
                    result["reason"] = (
                        f"gates_pass_waiting_ticks (score={result['recovery_score']:.2f}, ticks={ok_ticks}/{NEEDED_OK_TICKS})"
                        + (f"; {gate_details_str}" if gate_details_str else "")
                    )
            else:
                result["hysteresis"]["ok_ticks"] = 0
                result["recovery_mode"] = "OFF"
                fail_str = ",".join(failing_gates)
                extra = f"; {gate_details_str}" if gate_details_str else ""
                result["reason"] = f"gates_failed: {fail_str}{extra}"
        else:
            result["hysteresis"]["ok_ticks"] = 0
            result["recovery_mode"] = "OFF"
            result["reason"] = f"capital_mode={capital_mode} (not in recovery state)"
        
        # Determine if recovery trading is allowed
        allow_recovery_trading = (
            result["recovery_mode"] == "RAMPING" and
            result["hysteresis"]["ok_ticks"] >= NEEDED_OK_TICKS
        )
        
        result["allowances"]["allow_recovery_trading"] = allow_recovery_trading
        
        # Get allowed symbols if trading is allowed
        if allow_recovery_trading:
            allowed_symbols = _get_allowed_symbols(
                capital_plan,
                live_candidates,
                quarantine,
                execution_quality,
            )
            result["allowances"]["allowed_symbols"] = allowed_symbols[:5]  # Top 5 only
        
        # Add data freshness note
        if not pf_metrics["data_fresh"]:
            result["notes"].append("PF timeseries data may be stale")
        
        # Save state
        _save_json(RECOVERY_RAMP_STATE_PATH, result)
        
        return result
    
    except Exception as e:
        # On error, return safe defaults
        result["recovery_mode"] = "OFF"
        result["reason"] = f"evaluation_error: {str(e)}"
        result["notes"].append(f"Error during evaluation: {str(e)}")
        _save_json(RECOVERY_RAMP_STATE_PATH, result)
        return result


__all__ = ["evaluate_recovery_ramp"]

