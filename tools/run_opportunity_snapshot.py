#!/usr/bin/env python3
"""
Opportunity Snapshot Writer
----------------------------

Writes reports/opportunity_snapshot.json with detailed opportunity metrics.
This adds instrumentation to distinguish "no edge" vs "no inputs".
"""

from __future__ import annotations

import json
import sys
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import Counter
from typing import Dict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.core.paths import REPORTS, CONFIG
from engine_alpha.core.opportunity_density import (
    load_state,
    save_state,
    update_opportunity_state,
    ewma,
    is_loop_alive,
)


def _parse_ts(ts_str: str) -> datetime | None:
    """Parse ISO timestamp string."""
    if not ts_str:
        return None
    try:
        # Handle various ISO formats
        ts_str = ts_str.replace("Z", "+00:00")
        return datetime.fromisoformat(ts_str).astimezone(timezone.utc)
    except Exception:
        return None


def _scan_log_file(path: Path, cutoff: datetime) -> tuple[int, int, int, Counter]:
    """
    Scan a JSONL log file for events in the last 24h.
    
    Returns:
        Tuple of (events_count, candidates_count, eligible_count, reason_counter)
    """
    events_count = 0
    candidates_count = 0
    eligible_count = 0
    reason_counter = Counter()
    
    if not path.exists():
        return events_count, candidates_count, eligible_count, reason_counter
    
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                
                # Check timestamp
                ts_str = entry.get("ts") or entry.get("timestamp") or entry.get("time")
                if ts_str:
                    ts_dt = _parse_ts(ts_str)
                    if ts_dt and ts_dt < cutoff:
                        continue
                
                events_count += 1
                
                # Check if candidate (has signal/ready indicators)
                action = entry.get("action") or entry.get("event") or entry.get("type", "").lower()
                reason = entry.get("reason") or entry.get("block_reason") or ""
                reason_str = str(reason).lower()
                
                # Count candidates (signal_ready, ready_now, would_trade, etc.)
                if any(keyword in reason_str for keyword in ["signal_ready", "ready_now", "would_trade", "would_hold"]):
                    candidates_count += 1
                
                # Count eligible (opened, would_open, eligible=True)
                if action in ("open", "opened", "would_open") or entry.get("eligible") is True:
                    eligible_count += 1
                
                # Track block reasons
                if reason and action in ("blocked", "no_valid_signals", "would_block"):
                    # Extract main reason (first part before comma/paren)
                    main_reason = reason_str.split(",")[0].split("(")[0].strip()
                    if main_reason:
                        reason_counter[main_reason] += 1
                
    except Exception:
        pass
    
    return events_count, candidates_count, eligible_count, reason_counter


def _load_json(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _load_engine_config():
    return _load_json(CONFIG / "engine_config.json")


def _scan_opportunity_events(path: Path, cutoff: datetime) -> tuple[int, int]:
    """
    Scan opportunity_events.jsonl for last-24h counts.
    Returns (events_count, eligible_count).
    """
    events = 0
    eligible = 0
    if not path.exists():
        return events, eligible
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                ts_str = entry.get("ts")
                if ts_str:
                    ts_dt = _parse_ts(ts_str)
                    if ts_dt and ts_dt < cutoff:
                        continue
                events += 1
                if entry.get("eligible"):
                    eligible += 1
    except Exception:
        return 0, 0
    return events, eligible


def _load_capital_stances() -> tuple[str, Dict[str, str]]:
    """Load capital mode and per-symbol stance map."""
    data = _load_json(REPORTS / "risk" / "capital_protection.json")
    mode = (data.get("global") or {}).get("mode") or data.get("mode") or "unknown"
    stances: Dict[str, str] = {}
    symbols_section = data.get("symbols") or data.get("per_symbol") or {}
    if isinstance(symbols_section, dict):
        for sym, val in symbols_section.items():
            try:
                stance = (val or {}).get("stance")
                if stance:
                    stances[str(sym).upper()] = str(stance)
            except Exception:
                continue
    elif isinstance(symbols_section, list):
        for entry in symbols_section:
            if not isinstance(entry, dict):
                continue
            sym = entry.get("symbol") or entry.get("name")
            stance = entry.get("stance")
            if sym and stance:
                stances[str(sym).upper()] = str(stance)
    return mode, stances


def _promo_active(sym: str) -> bool:
    try:
        cfg = _load_json(CONFIG / "engine_config.json")
        promo = (cfg.get("core_promotions") or {}).get(sym.upper())
        return bool(promo and promo.get("enabled", False))
    except Exception:
        return False


def _scan_recovery_ramp_v2(path: Path, cutoff: datetime) -> tuple[int, int, int, Counter, dict]:
    """
    Scan recovery_ramp_v2.json for symbol evaluations.
    
    Returns:
        Tuple of (events_count, candidates_count, eligible_count, reason_counter, metadata_dict)
    """
    events_count = 0
    candidates_count = 0
    eligible_count = 0
    reason_counter = Counter()
    metadata = {
        "capital_mode": None,
        "execql_hostile_count": 0,
        "score_too_low_count": 0,
        "score_details": [],  # List of (score, threshold, reason) tuples
        "execql_gate_failures": Counter(),  # Track which gates fail
        "champion_override_count": 0,
        "champion_override_examples": [],
    }
    
    if not path.exists():
        return events_count, candidates_count, eligible_count, reason_counter, metadata
    
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Extract capital_mode
        metadata["capital_mode"] = data.get("capital_mode")
        
        # Check file timestamp
        file_ts_str = data.get("generated_at") or data.get("ts")
        if file_ts_str:
            file_ts = _parse_ts(file_ts_str)
            if file_ts and file_ts < cutoff:
                return events_count, candidates_count, eligible_count, reason_counter, metadata
        
        # Scan symbols
        symbols = data.get("symbols", {})
        champion_override_examples = []
        
        for symbol, symbol_data in symbols.items():
            if not isinstance(symbol_data, dict):
                continue
            
            events_count += 1
            
            # Check gates to determine if candidate
            gates = symbol_data.get("gates", {})
            score = symbol_data.get("score", 0.0)
            is_eligible = symbol_data.get("eligible") is True
            
            # Consider it a candidate if it has a score > 0 or passes some gates
            is_candidate = score > 0 or gates.get("not_quarantined") or gates.get("policy_not_blocked")
            
            if is_candidate:
                candidates_count += 1
            
            # Check if eligible
            if is_eligible or symbol in data.get("decision", {}).get("allowed_symbols", []):
                eligible_count += 1
            
            # Track block reasons with details
            reasons = symbol_data.get("reasons", [])
            if isinstance(reasons, list):
                for reason in reasons:
                    if reason:
                        reason_str = str(reason).lower()
                        main_reason = reason_str.split(",")[0].split("(")[0].strip()
                        
                        # Track champion_override (can be permissive or restrictive)
                        if "champion_override" in reason_str or "champion" in reason_str:
                            metadata["champion_override_count"] = metadata.get("champion_override_count", 0) + 1
                            # Determine mode: permissive (eligible=true) or restrictive (eligible=false)
                            if is_eligible:
                                mode = "force_allow"
                            else:
                                mode = "force_block"
                            
                            # Collect example (up to 3)
                            if len(champion_override_examples) < 3:
                                champion_override_examples.append({
                                    "symbol": symbol,
                                    "timeframe": "15m",  # Default, could be extracted if available
                                    "reason": reason,
                                    "score": score,
                                    "eligible": is_eligible,
                                    "execql_not_hostile": gates.get("execql_not_hostile"),
                                    "decision": "allowed" if symbol in data.get("decision", {}).get("allowed_symbols", []) else "blocked",
                                    "mode": mode,
                                })
                        
                        # Track execql_hostile
                        if "execql_hostile" in reason_str:
                            metadata["execql_hostile_count"] += 1
                            # Track which execql gate failed
                            if not gates.get("execql_not_hostile"):
                                metadata["execql_gate_failures"]["execql_not_hostile"] += 1
                        
                        # Track score_too_low with details
                        if "score" in reason_str and "low" in reason_str:
                            metadata["score_too_low_count"] += 1
                            # Extract score and threshold from reason string
                            # Format: "score_too_low (0.35 < 0.55)"
                            match = re.search(r'\(([\d.]+)\s*[<>]\s*([\d.]+)\)', reason)
                            if match:
                                score_val = float(match.group(1))
                                threshold_val = float(match.group(2))
                                metadata["score_details"].append({
                                    "score": score_val,
                                    "threshold": threshold_val,
                                    "symbol": symbol,
                                })
                        
                        if main_reason:
                            reason_counter[main_reason] += 1
        
        # Store champion override examples
        metadata["champion_override_examples"] = champion_override_examples
                
    except Exception:
        pass
    
    return events_count, candidates_count, eligible_count, reason_counter, metadata


def compute_opportunity_snapshot(symbol: str = "ETHUSDT", timeframe: str = "15m") -> dict[str, any]:
    """
    Compute opportunity snapshot with instrumentation from log files.
    
    Args:
        symbol: Trading symbol (default: ETHUSDT)
        timeframe: Timeframe (default: 15m)
    
    Returns:
        Dict with opportunity metrics and diagnostic fields
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    
    # Load state for density metrics
    state = load_state()
    global_data = state.get("global", {})
    by_regime = state.get("by_regime", {})
    
    # Find observed regime from opportunity density state (most recent last_ts).
    # This can drift from the canonical regime classifier if one side lags.
    current_regime = "unknown"
    latest_ts = None
    for regime, regime_data in by_regime.items():
        regime_ts = regime_data.get("last_ts")
        if regime_ts:
            try:
                ts_dt = _parse_ts(regime_ts)
                if ts_dt and (latest_ts is None or ts_dt > latest_ts):
                    latest_ts = ts_dt
                    current_regime = regime
            except Exception:
                pass

    regime_observed = current_regime

    # Canonical regime source: reports/regime_snapshot.json (if available).
    # If present, use it as the "current regime" for floors/eligibility and reporting.
    regime_current = regime_observed
    regime_source = "opportunity_state"
    symbol_regime = None
    global_regime = None
    try:
        regime_snapshot_path = REPORTS / "regime_snapshot.json"
        if regime_snapshot_path.exists():
            with regime_snapshot_path.open("r", encoding="utf-8") as f:
                regime_snap = json.load(f)
            cand = regime_snap.get("regime")
            if isinstance(cand, str) and cand:
                regime_current = cand
                global_regime = cand
                regime_source = "regime_snapshot"
    except Exception:
        pass

    # Load per-symbol regime if available
    try:
        sym_reg_path = REPORTS / "regimes" / f"regime_snapshot_{symbol}.json"
        if sym_reg_path.exists():
            with sym_reg_path.open("r", encoding="utf-8") as f:
                sym_snap = json.load(f)
            cand = sym_snap.get("regime")
            if isinstance(cand, str) and cand:
                symbol_regime = cand
    except Exception:
        pass

    effective_regime = symbol_regime or regime_current
    regime_agree = (symbol_regime == global_regime) if symbol_regime and global_regime else None
    
    current_regime_data = by_regime.get(regime_current, {})
    
    # Extract density metrics
    density_ewma = current_regime_data.get("eligible_ewma", 0.0) / max(current_regime_data.get("ticks_ewma", 1e-9), 1e-9)
    global_density_ewma = global_data.get("eligible_ewma", 0.0) / max(global_data.get("ticks_ewma", 1e-9), 1e-9)
    
    # Determine eligibility (simplified threshold)
    eligible = density_ewma > 0.1  # 10% density threshold
    
    # Scan log files for event counts
    all_reason_counter = Counter()
    total_events = 0
    total_candidates = 0
    total_eligible = 0
    ramp_metadata = {}
    
    # Scan recovery_ramp_v2.json (returns metadata)
    ramp_path = REPORTS / "risk" / "recovery_ramp_v2.json"
    evts, cands, elig, reasons, metadata = _scan_recovery_ramp_v2(ramp_path, cutoff)
    total_events += evts
    total_candidates += cands
    total_eligible += elig
    all_reason_counter.update(reasons)
    ramp_metadata = metadata
    
    # Also scan opportunity_events.jsonl (primary source for density counts)
    evt_path = REPORTS / "opportunity_events.jsonl"
    evt_events, evt_eligible = _scan_opportunity_events(evt_path, cutoff)
    events_24h = evt_events
    eligible_24h = evt_eligible
    
    # Update density state from eligible events (Option A: feed density from eligible events)
    # This ensures density reflects actual eligible events, not just trading loop ticks
    # GUARD: Trading loop is authoritative - snapshot only updates as fallback when loop is idle
    opp_state = load_state()
    now_ts = now.isoformat()
    
    # Check if trading loop is alive (heartbeat check is more reliable than last_source)
    loop_is_alive = is_loop_alive(max_age_seconds=90)
    
    # Also check last_source as fallback
    meta = opp_state.get("meta", {})
    last_source = meta.get("last_source")
    
    # If loop is active (heartbeat fresh OR last_source == "loop"), snapshot is observer-only (no mutations)
    # Only update density if loop is idle (no heartbeat AND last_source != "loop")
    is_loop_active = loop_is_alive or (last_source == "loop")
    
    # Round window end to minute for idempotency (prevents double-counting from rapid refreshes)
    window_end_dt = now.replace(second=0, microsecond=0)
    window_end_ts = window_end_dt.isoformat()
    
    # Check debounce: only ingest if this window hasn't been processed yet
    last_ingest_ts = meta.get("last_density_ingest_ts")
    
    should_ingest = True
    if last_ingest_ts:
        try:
            from dateutil import parser
            last_ingest_dt = parser.isoparse(last_ingest_ts)
            # Only skip if we're in the same minute window
            if window_end_dt <= last_ingest_dt:
                should_ingest = False
        except Exception:
            # If parsing fails, allow ingest (safer)
            pass
    
    # Compute eligible rate from the 24h window
    eligible_rate_24h = total_eligible / max(total_events, 1) if total_events > 0 else 0.0
    
    # Update density state proportionally based on eligible rate
    # Only if: (1) loop is NOT active, (2) debounce allows, (3) we have events
    if not is_loop_active and should_ingest and total_events > 0:
        # Update state once with the observed eligible rate
        # This approximates "eligible_rate_24h fraction of events were eligible"
        # We update both eligible and non-eligible to maintain proper tick/eligible ratio
        # Use a batch update: update N times where N = min(total_events, 50) to avoid excessive computation
        # But weight eligible updates by eligible_rate_24h
        
        # Calculate how many updates to do (cap to avoid excessive computation)
        num_updates = min(total_events, 50)
        eligible_updates = int(num_updates * eligible_rate_24h)
        non_eligible_updates = num_updates - eligible_updates
        
        # Update state with eligible events
        for _ in range(eligible_updates):
            opp_state, _ = update_opportunity_state(
                opp_state,
                now_ts,
                regime_current,
                is_eligible=True,
                alpha=0.05,  # Standard EWMA alpha
            )
        
        # Update state with non-eligible events (to maintain tick count)
        for _ in range(non_eligible_updates):
            opp_state, _ = update_opportunity_state(
                opp_state,
                now_ts,
                regime_current,
                is_eligible=False,
                alpha=0.05,
            )
        
        # Mark this window as ingested and mark snapshot as source
        if "meta" not in opp_state:
            opp_state["meta"] = {}
        opp_state["meta"]["last_density_ingest_ts"] = window_end_ts
        opp_state["meta"]["last_source"] = "snapshot"
        opp_state["meta"]["last_update_ts"] = now_ts
        
        # Save updated state
        save_state(opp_state)
    
    # Reload to get updated density (even if we skipped ingest, we need current state)
    opp_state = load_state()
    by_regime = opp_state.get("by_regime", {})
    current_regime_data = by_regime.get(regime_current, {})
    global_data = opp_state.get("global", {})
    
    # Recompute density deterministically from observed counts
    by_regime_density = opp_state.get("by_regime_density", {})
    # Use observed opportunity events for density (if present), else fallback to totals
    if events_24h == 0 and eligible_24h == 0:
        events_24h = total_events
        eligible_24h = total_eligible
    density_current = eligible_24h / max(events_24h, 1)
    
    global_density_ewma = global_data.get("eligible_ewma", 0.0) / max(global_data.get("ticks_ewma", 1e-9), 1e-9)
    
    # Get density floor for current regime (from config defaults)
    cfg = _load_engine_config()
    default_floors = {
        "trend_up": 0.08,
        "trend_down": 0.08,
        "chop": 0.10,
        "high_vol": 0.12,
        "unknown": 0.10,
    }
    density_floors_cfg = cfg.get("opportunity_density_floor_by_regime", {}) if isinstance(cfg, dict) else {}
    density_floor = density_floors_cfg.get(regime_current, density_floors_cfg.get("unknown", default_floors.get("unknown")))
    if density_floor is None:
        density_floor = default_floors.get(regime_current, default_floors["unknown"])
    
    # Scan exploit_lane_gate_log.jsonl
    gate_log_path = REPORTS / "risk" / "exploit_lane_gate_log.jsonl"
    evts, cands, elig, reasons = _scan_log_file(gate_log_path, cutoff)
    total_events += evts
    total_candidates += cands
    total_eligible += elig
    all_reason_counter.update(reasons)
    
    # Scan recovery_lane_v2_trades.jsonl
    recovery_log_path = REPORTS / "loop" / "recovery_lane_v2_trades.jsonl"
    evts, cands, elig, reasons = _scan_log_file(recovery_log_path, cutoff)
    total_events += evts
    total_candidates += cands
    total_eligible += elig
    all_reason_counter.update(reasons)
    
    # Get top 3 block reasons
    reasons_top = [reason for reason, _ in all_reason_counter.most_common(3)]
    
    # Compute derived metrics
    eligible_rate = total_eligible / max(total_candidates, 1)
    hostile_rate = ramp_metadata.get("execql_hostile_count", 0) / max(total_candidates, 1)
    score_low_rate = ramp_metadata.get("score_too_low_count", 0) / max(total_candidates, 1)
    champion_override_count = ramp_metadata.get("champion_override_count", 0)
    champion_override_rate = champion_override_count / max(total_candidates, 1)
    
    # Determine champion override mode (most common mode in examples)
    champion_examples = ramp_metadata.get("champion_override_examples", [])
    champion_override_mode = "unknown"
    if champion_examples:
        modes = [ex.get("mode") for ex in champion_examples if ex.get("mode")]
        if modes:
            mode_counter = Counter(modes)
            champion_override_mode = mode_counter.most_common(1)[0][0]
    
    # Extract score details (average score vs threshold)
    score_details = ramp_metadata.get("score_details", [])
    avg_score_gap = None
    if score_details:
        gaps = [d["threshold"] - d["score"] for d in score_details]
        avg_score_gap = sum(gaps) / len(gaps) if gaps else None
    
    # Determine eligible_now and reason
    # eligible_now is based on density_current vs density_floor (regime-specific)
    # density_current and density_floor are already computed above
    # Load capital mode/stances once
    capital_mode, stances = _load_capital_stances()

    # Safe lever: stance-normal relief in high_vol (capital_mode normal)
    density_floor_effective = density_floor
    density_floor_reason = None
    stance = None
    if isinstance(stances, dict):
        stance = stances.get(symbol.upper()) or stances.get("ANCHOR") or stances.get("ETHUSDT")
    if capital_mode == "normal" and regime_current == "high_vol" and stance == "normal":
        density_floor_effective = min(density_floor, 0.06)
        density_floor_reason = "high_vol_stance_normal_relief"

    eligible_now = density_current >= density_floor_effective
    
    # Determine eligible_now_reason and density_low flag
    eligible_now_reason = None
    density_low = False
    density_penalty_scale = None
    if events_24h == 0:
        eligible_now = False
        eligible_now_reason = "no_event_stream"
    elif not eligible_now:
        if density_current == 0.0:
            eligible_now_reason = "density_below_floor"
        elif density_current < density_floor_effective:
            eligible_now_reason = f"density_below_floor ({density_current:.3f} < {density_floor_effective})"
            density_low = True
            density_penalty_scale = 0.5
        else:
            eligible_now_reason = "unknown"
    else:
        eligible_now_reason = "density_above_floor"

    # Bypass: allow stance-normal or promotion symbols during risk-off when density is the only blocker
    # Extended: allow promotion to bypass density even in normal capital_mode.
    density_bypass_applied = False
    density_bypass_due_to_promotion = False
    density_bypass_reason = None
    promo_active = _promo_active(symbol)
    if (not eligible_now) and eligible_now_reason and "density_below_floor" in str(eligible_now_reason):
        # Risk-off bypass (existing behavior)
        if capital_mode in {"halt_new_entries", "de_risk"} and (stance == "normal" or promo_active):
            eligible_now = True
            density_bypass_applied = True
            density_bypass_reason = f"density_below_floor_bypassed (capital_mode={capital_mode}, stance={stance}, promo={promo_active})"
            eligible_now_reason = density_bypass_reason
        # Promotion-only bypass in normal mode
        elif promo_active:
            eligible_now = True
            density_bypass_applied = True
            density_bypass_due_to_promotion = True
            density_bypass_reason = "density_below_floor_bypassed_promotion"
            eligible_now_reason = density_bypass_reason
    
    return {
        # Canonical regime used for floors/eligibility
        "regime": effective_regime,
        "global_regime": global_regime or regime_current,
        "symbol_regime": symbol_regime,
        "effective_regime": effective_regime,
        "regime_agree": regime_agree,
        "regime_observed": regime_observed,
        "regime_source": regime_source,
        "symbol": symbol,
        "timeframe": timeframe,
        "eligible": eligible,  # This is eligible_now (based on density)
        "eligible_now": eligible_now,  # Explicit eligible_now flag
        "eligible_now_reason": eligible_now_reason,
        "density_current": density_current,
        "density_floor": density_floor,
        "density_floor_effective": density_floor_effective,
        "density_floor_reason": density_floor_reason,
        "density_low": density_low,
        "density_penalty_scale": density_penalty_scale,
        "density_by_regime": by_regime_density.copy() if by_regime_density else {},  # Per-regime densities
        "global_density_ewma": global_density_ewma,
        "density_bypass_applied": density_bypass_applied,
        "density_bypass_due_to_promotion": density_bypass_due_to_promotion,
        "density_bypass_reason": density_bypass_reason,
        "last_update_ts": current_regime_data.get("last_ts") or now.isoformat(),
        # Deterministic counts used for density_current
        "events_24h": events_24h,
        "eligible_24h": eligible_24h,
        "events_seen_24h": events_24h,
        "candidates_seen_24h": total_candidates,
        "eligible_seen_24h": eligible_24h,
        "reasons_top": reasons_top,
        # Derived metrics
        "eligible_rate": eligible_rate,
        "hostile_rate": hostile_rate,
        "score_low_rate": score_low_rate,
        # Capital mode context
        "capital_mode": ramp_metadata.get("capital_mode"),
        # ExecQL details
        "execql_hostile_count": ramp_metadata.get("execql_hostile_count", 0),
        "execql_hostile_top_component": list(ramp_metadata.get("execql_gate_failures", Counter()).most_common(1))[0][0] if ramp_metadata.get("execql_gate_failures") else None,
        # Score details
        "score_too_low_count": ramp_metadata.get("score_too_low_count", 0),
        "avg_score_gap": avg_score_gap,  # Average gap between score and threshold
        # Champion override details
        "champion_override_count": champion_override_count,
        "champion_override_rate": champion_override_rate,
        "champion_override_mode": champion_override_mode,
        "champion_override_examples": champion_examples[:3],  # Up to 3 examples
        "generated_at": now.isoformat(),
    }


def main() -> int:
    """Main entry point."""
    result = compute_opportunity_snapshot()
    
    # Write to reports/opportunity_snapshot.json
    output_path = REPORTS / "opportunity_snapshot.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    
    print(f"Opportunity snapshot: regime={result.get('regime')}, eligible={result.get('eligible')}, "
          f"events_24h={result.get('events_seen_24h')}, eligible_24h={result.get('eligible_seen_24h')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

