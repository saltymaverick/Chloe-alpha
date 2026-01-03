from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Tuple

import yaml
import dateutil.parser

from engine_alpha.signals.signal_processor import get_signal_vector, get_signal_vector_live
from engine_alpha.core.confidence_engine import decide, COUNCIL_WEIGHTS, apply_bucket_mask, REGIME_BUCKET_MASK
from engine_alpha.core.paths import REPORTS, CONFIG
from engine_alpha.data.live_prices import get_live_ohlcv
from engine_alpha.core.regime import classify_regime
from engine_alpha.core.profit_amplifier import evaluate as pa_evaluate, risk_multiplier as pa_rmult
from engine_alpha.core.risk_adapter import evaluate as risk_eval
from engine_alpha.core.opportunity_density import update_opportunity_state, save_state, load_state
from engine_alpha.loop.execute_trade import open_if_allowed, close_now
from engine_alpha.loop.lanes import resolve_lane
from engine_alpha.loop.lanes.registry import registry as lane_registry
from engine_alpha.loop.lanes.base import LaneDecision, LaneContext
from engine_alpha.loop.position_manager import (
    get_open_position,
    set_position,
    get_live_position,
    set_live_position,
    clear_live_position,
    clear_position,
)
from engine_alpha.reflect.trade_analysis import update_pf_reports
from engine_alpha.reflect import pf_weighted
from engine_alpha.config.feature_flags import get_feature_registry, refresh_feature_registry
from engine_alpha.reflect.counterfactual_ledger import record_trading_decision, resolve_trade_counterfactual
from engine_alpha.reflect.regime_uncertainty import assess_regime_uncertainty
from engine_alpha.reflect.edge_half_life import analyze_edge_strength
from engine_alpha.reflect.meta_intelligence import assess_meta_decision_quality
from engine_alpha.reflect.fair_value_gaps import detect_and_log_fvgs
from engine_alpha.reflect.missed_expansion_analytics import record_expansion_analytics
from engine_alpha.core import position_sizing

TRADES_PATH = REPORTS / "trades.jsonl"
ORCH_SNAPSHOT = REPORTS / "orchestrator_snapshot.json"
EQUITY_LIVE_PATH = REPORTS / "equity_live.json"
EQUITY_CURVE_LIVE_PATH = REPORTS / "equity_curve_live.jsonl"
EQUITY_CURVE_NORM_PATH = REPORTS / "equity_curve_norm.jsonl"

# Phase: Stabilization & Realism - Unified code path for all modes
IS_PAPER_MODE = os.getenv("MODE", "PAPER").upper() == "PAPER"
# Base live min confidence (global)
MIN_CONF_LIVE_DEFAULT = 0.55
MIN_CONF_LIVE = float(os.getenv("MIN_CONF_LIVE", MIN_CONF_LIVE_DEFAULT))

def _parse_timestamp(ts_str: str) -> datetime | None:
    """Parse timestamp string to datetime, handling various formats."""
    try:
        if not ts_str:
            return None
        # Handle ISO format with Z suffix
        ts_str = ts_str.replace("Z", "+00:00")
        return dateutil.parser.isoparse(ts_str)
    except Exception:
        return None

# -----------------------------------------------------------------------------
# Entry threshold config (per-regime floors, tuned via tools/threshold_tuner.py)
# -----------------------------------------------------------------------------

ENTRY_THRESHOLDS_DEFAULT: dict[str, float] = {
    "trend_down": 0.50,
    "high_vol": 0.55,
    "trend_up": 0.60,
    "chop": 0.25,  # Lowered back to reduce false negatives in chop regime detection
}


def _load_entry_thresholds() -> dict[str, float]:
    """
    Load per-regime entry thresholds from config/entry_thresholds.json.

    Falls back to ENTRY_THRESHOLDS_DEFAULT on missing/parse error.
    """
    try:
        cfg_path = (
            Path(__file__)
            .resolve()
            .parents[2]
            / "config"
            / "entry_thresholds.json"
        )
    except Exception:
        # Very defensive: just return defaults
        return dict(ENTRY_THRESHOLDS_DEFAULT)

    if not cfg_path.exists():
        return dict(ENTRY_THRESHOLDS_DEFAULT)

    try:
        raw = json.loads(cfg_path.read_text())
        merged: dict[str, float] = dict(ENTRY_THRESHOLDS_DEFAULT)
        for key, value in raw.items():
            try:
                merged[key] = float(value)
            except (TypeError, ValueError):
                # Ignore non-numeric values
                continue
        return merged
    except Exception:
        # On any parse error, fall back to defaults
        return dict(ENTRY_THRESHOLDS_DEFAULT)


_ENTRY_THRESHOLDS: dict[str, float] = _load_entry_thresholds()

# Unified neutral zone threshold (all modes use same value)
NEUTRAL_THRESHOLD_DEFAULT = 0.25  # Lowered from 0.30 to reduce false neutralizations

# Phase 5J-R: Chop exploration cooldown to prevent micro-churn
CHOP_EXPLORATION_COOLDOWN_MINUTES = 15  # 15 minutes between chop exploration attempts
_CHOP_COOLDOWN_FILE = REPORTS / "risk" / "chop_cooldowns.json"

# CORE lane safeguards to prevent scalping behavior
_CORE_COOLDOWN_FILE = REPORTS / "risk" / "core_cooldowns.json"

# CORE Extreme TP Override (rare opportunity capture)
EXTREME_TP_ATR_MULTIPLE = 2.5  # 2.5x ATR for extreme move detection
EXTREME_TP_MIN_TIME_SECONDS = 90  # Minimum 90 seconds even for extreme moves
EXTREME_TP_MAX_RATIO = 0.05  # Max 5% of CORE trades can be extreme TP
EXTREME_TP_ATR_MULT = 2.5  # ATR multiplier for extreme TP threshold
EXTREME_TP_ABS_PCT_FALLBACK = 0.012  # 1.20% absolute fallback if ATR unavailable
_EXTREME_TP_TRACKING_FILE = REPORTS / "risk" / "extreme_tp_tracking.json"

def _load_chop_cooldowns():
    """Load chop exploration cooldowns from persistent storage."""
    if not _CHOP_COOLDOWN_FILE.exists():
        return {}
    try:
        with _CHOP_COOLDOWN_FILE.open("r") as f:
            data = json.load(f)
            # Convert ISO strings back to timestamps for comparison
            return data
    except Exception:
        return {}

def _save_chop_cooldowns(cooldowns):
    """Save chop exploration cooldowns to persistent storage."""
    try:
        _CHOP_COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _CHOP_COOLDOWN_FILE.open("w") as f:
            json.dump(cooldowns, f, indent=2)
        print(f"CHOP_COOLDOWN_SAVED: {len(cooldowns)} cooldowns to {_CHOP_COOLDOWN_FILE}")
    except Exception as e:
        print(f"CHOP_COOLDOWN_SAVE_ERROR: {e}")

def _load_core_cooldowns():
    """Load CORE lane cooldowns from persistent storage."""
    if not _CORE_COOLDOWN_FILE.exists():
        return {}
    try:
        with _CORE_COOLDOWN_FILE.open("r") as f:
            data = json.load(f)
            return data
    except Exception:
        return {}

def _save_core_cooldowns(cooldowns):
    """Save CORE lane cooldowns to persistent storage."""
    try:
        _CORE_COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _CORE_COOLDOWN_FILE.open("w") as f:
            json.dump(cooldowns, f, indent=2)
        print(f"CORE_COOLDOWN_SAVED: {len(cooldowns)} cooldowns to {_CORE_COOLDOWN_FILE}")
    except Exception as e:
        print(f"CORE_COOLDOWN_SAVE_ERROR: {e}")

# Load cooldowns at module startup
_CHOP_EXPLORATION_COOLDOWN = _load_chop_cooldowns()
_CORE_COOLDOWN = _load_core_cooldowns()

def _load_extreme_tp_tracking():
    """Load extreme TP tracking data."""
    if not _EXTREME_TP_TRACKING_FILE.exists():
        return {"total_extreme_tp": 0, "total_core_trades": 0, "last_reset": None}
    try:
        with _EXTREME_TP_TRACKING_FILE.open("r") as f:
            return json.load(f)
    except Exception:
        return {"total_extreme_tp": 0, "total_core_trades": 0, "last_reset": None}

def _save_extreme_tp_tracking(tracking):
    """Save extreme TP tracking data."""
    try:
        _EXTREME_TP_TRACKING_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _EXTREME_TP_TRACKING_FILE.open("w") as f:
            json.dump(tracking, f, indent=2)
    except Exception as e:
        print(f"EXTREME_TP_TRACKING_SAVE_ERROR: {e}")

def _check_extreme_tp_governance():
    """Check if extreme TP overrides are within governance limits."""
    tracking = _load_extreme_tp_tracking()
    total_extreme = tracking.get("total_extreme_tp", 0)
    total_core = tracking.get("total_core_trades", 0)

    if total_core == 0:
        return True

    ratio = total_extreme / total_core
    return ratio <= EXTREME_TP_MAX_RATIO

def _record_extreme_tp(symbol, pnl_pct, time_held):
    """Record an extreme TP event for governance tracking."""
    tracking = _load_extreme_tp_tracking()
    tracking["total_extreme_tp"] = tracking.get("total_extreme_tp", 0) + 1
    tracking["total_core_trades"] = tracking.get("total_core_trades", 0) + 1

    # Check governance limits
    if not _check_extreme_tp_governance():
        print(f"GOVERNANCE_WARNING: Extreme TP ratio exceeded {EXTREME_TP_MAX_RATIO:.1%}, disabling override")
        # TODO: Could disable override here by setting a flag

    _save_extreme_tp_tracking(tracking)
    print(f"EXTREME_TP_RECORDED: {symbol} pnl={pnl_pct:.2f}% time_held={time_held}s (governance_ok={_check_extreme_tp_governance()})")

def _is_extreme_tp_override(lane_id, unrealized_pnl_pct, time_held_seconds, regime, volatility_regime=None, regime_info=None):
    """
    Check if CORE position qualifies for extreme TP override.
    Allows early exit only for objectively exceptional market moves.
    """
    if lane_id != "core":
        return False

    # Governance check: ensure we haven't exceeded frequency limits
    if not _check_extreme_tp_governance():
        return False

    # Time constraint: must hold at least minimum time even for extreme moves
    if time_held_seconds < EXTREME_TP_MIN_TIME_SECONDS:
        return False

    # Price expansion threshold: must be exceptional move
    # Use ATR-based threshold (2.5x ATR) or fallback to absolute %
    extreme_threshold_pct = EXTREME_TP_ABS_PCT_FALLBACK * 100  # Convert to percentage
    try:
        # TODO: Implement ATR calculation for proper threshold
        # For now, use absolute threshold
        pass
    except Exception:
        pass

    if abs(unrealized_pnl_pct) < extreme_threshold_pct:
        return False

    # Regime guard: allow in trending/high_vol, block in chop unless special conditions
    allowed_regimes = {"trend_up", "trend_down", "high_vol"}
    blocked_regimes = {"chop"}

    if regime in blocked_regimes:
        # Special case: allow chop if vol_expanding AND compression_breakout
        if not (volatility_regime == "expanding" and regime_info and
                regime_info.get("compression_breakout", False)):
            return False
    elif regime not in allowed_regimes:
        return False

    return True

def _cleanup_expired_chop_cooldowns():
    """Clean up expired chop exploration cooldowns."""
    now_dt = datetime.now(timezone.utc)
    expired_symbols = []
    for symbol, cooldown_iso in _CHOP_EXPLORATION_COOLDOWN.items():
        try:
            cooldown_dt = datetime.fromisoformat(cooldown_iso.replace("Z", "+00:00"))
            if now_dt >= cooldown_dt:
                expired_symbols.append(symbol)
        except Exception:
            # Invalid timestamp, remove it
            expired_symbols.append(symbol)

    for symbol in expired_symbols:
        del _CHOP_EXPLORATION_COOLDOWN[symbol]

    if expired_symbols:
        print(f"CHOP_COOLDOWN_CLEANUP: Removed expired cooldowns for {expired_symbols}")
        _save_chop_cooldowns(_CHOP_EXPLORATION_COOLDOWN)
NEUTRAL_THRESHOLD = float(os.getenv("COUNCIL_NEUTRAL_THRESHOLD", str(NEUTRAL_THRESHOLD_DEFAULT)))

MIN_HOLD_BARS_LIVE_DEFAULT = 4 if IS_PAPER_MODE else 2  # Phase 52: Longer min-hold in PAPER
MIN_HOLD_BARS_LIVE = int(os.getenv("MIN_HOLD_BARS_LIVE", MIN_HOLD_BARS_LIVE_DEFAULT))

# Council performance logging
COUNCIL_LOG_PATH = REPORTS / "council_perf.jsonl"
DEBUG_COUNCIL_LOG = os.getenv("DEBUG_COUNCIL_LOG", "1") == "1"

# Phase 51: Anti-Thrash Guardrails
# In-memory state to prevent rapid-fire trading bursts
_COOL_DOWN_SECONDS = 5  # Minimum seconds between opens
_BAD_EXIT_WINDOW_SECONDS = 10  # Time window for tracking bad exits
_BAD_EXIT_THRESHOLD = 3  # Number of SL/drop exits that trigger suppression

# Inaction logging deduplication (in-memory, resets on restart)
_inaction_dedupe_cache: Dict[Tuple[str, str, str], datetime] = {}

_LAST_BAR_STATE = {
    "bar_ts": None,
    "opened_this_bar": False,
    "last_open_ts": None,
    "recent_bad_exits": [],  # List of datetime objects for SL/drop exits
}


def _log_inaction_if_blocked(symbol: str, timeframe: str, direction: int, confidence: float,
                           regime: str, allow_opens: bool, entry_min_conf: float) -> None:
    """
    Log inaction decisions at FINAL_DECISION level with deduplication.

    Only logs when decision is blocked and hasn't been logged recently for same conditions.
    """
    # Determine if decision is blocked
    is_blocked = False
    barrier_type = ""
    barrier_reason = ""

    if not allow_opens:
        is_blocked = True
        barrier_type = "policy_block"
        barrier_reason = "allow_opens_false"
    elif direction == 0:
        is_blocked = True
        barrier_type = "neutral_decision"
        barrier_reason = "direction_zero"
    elif confidence < entry_min_conf:
        is_blocked = True
        barrier_type = "confidence_threshold"
        barrier_reason = f"conf_{confidence:.2f}_below_{entry_min_conf:.2f}"

    # Only log if blocked and dedupe check passes
    if is_blocked and _should_log_inaction(symbol, timeframe, barrier_reason):
        try:
            from engine_alpha.reflect.inaction_performance import record_inaction_decision
            record_inaction_decision(
                symbol=symbol,
                intended_direction=direction,
                confidence=confidence,
                regime=regime,
                barrier_type=barrier_type,
                barrier_reason=barrier_reason,
                market_state={
                    "timeframe": timeframe,
                    "entry_min_conf": entry_min_conf,
                    "regime": regime
                }
            )
            # Logged successfully
        except Exception as e:
            print(f"INACTION_LOGGING_ERROR: {e}")


def _should_log_inaction(symbol: str, timeframe: str, barrier_reason: str) -> bool:
    """
    Deduplication check for inaction logging.
    Returns False if same (symbol, timeframe, barrier_reason) was logged within 5 minutes.
    """
    cache_key = (symbol, timeframe, barrier_reason)
    now = datetime.now(timezone.utc)

    # Check if we logged this recently
    if cache_key in _inaction_dedupe_cache:
        last_logged = _inaction_dedupe_cache[cache_key]
        if (now - last_logged).total_seconds() < 300:  # 5 minutes
            return False

    # Update cache and allow logging
    _inaction_dedupe_cache[cache_key] = now
    return True


def _log_council_event(event: dict) -> None:
    """Append a council perf event to council_perf.jsonl (logging only)."""
    if not DEBUG_COUNCIL_LOG:
        return
    try:
        COUNCIL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with COUNCIL_LOG_PATH.open("a") as f:
            f.write(json.dumps(event) + "\n")
    except Exception:
        # Logging must never break trading
        pass


def _count_lines(path: Path) -> int:
    try:
        with path.open("r") as handle:
            return sum(1 for _ in handle)
    except Exception:
        return 0


def regime_allows_entry(regime: str) -> bool:
    """
    Controls whether we're willing to open a trade in a given regime.

    LIVE/PAPER: only trend_down / high_vol.
    BACKTEST (when BACKTEST_FREE_REGIME=1): allow all regimes for debugging/tuning.
    """
    # Backtest override
    if os.getenv("BACKTEST_FREE_REGIME") == "1":
        return True
    
    # Live/PAPER behavior - allow chop for mean reversion strategies
    return regime in ("trend_down", "high_vol", "chop")


def compute_entry_min_conf(regime: str, risk_band: str | None) -> float:
    """
    Compute effective entry minimum confidence based on:

    - Regime floor from _ENTRY_THRESHOLDS.
    - Risk band adjustments:
        A: +0.00
        B: +0.03 (more conservative)
        C: +0.05 (most conservative)
    - Clamped to [0.35, 0.90].

    Returned value is rounded to 2 decimals.
    """
    base = _ENTRY_THRESHOLDS.get(regime, ENTRY_THRESHOLDS_DEFAULT["chop"])

    if risk_band == "B":
        base += 0.03
    elif risk_band == "C":
        base += 0.05

    # Clamp
    if base < 0.35:
        base = 0.35
    if base > 0.90:
        base = 0.90

    return round(base, 2)


# Removed unused _compute_entry_min_conf() function - dead code
# Use compute_entry_min_conf() instead (line 152)


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _annotate_last_open(pa_mult: float, adapter: dict, total_mult: float) -> None:
    if not TRADES_PATH.exists():
        return
    try:
        lines = TRADES_PATH.read_text().splitlines()
    except Exception:
        return
    if not lines:
        return
    try:
        last = json.loads(lines[-1])
    except Exception:
        return
    if last.get("type") != "open":
        return
    band = adapter.get("band")
    last["risk_mult"] = total_mult
    if band is not None:
        last["risk_band"] = band
    last["risk_factors"] = {
        "pa": pa_mult,
        "adapter": float(adapter.get("mult", 1.0)),
        "band": band,
    }
    lines[-1] = json.dumps(last)
    TRADES_PATH.write_text("\n".join(lines) + "\n")


def _extract_spread_bps(context: Dict) -> float | None:
    if not isinstance(context, dict):
        return None
    val = context.get("spread_bps")
    if isinstance(val, (int, float)):
        return float(val)
    val = context.get("spread")
    if isinstance(val, (int, float)):
        return float(val) * 10000.0
    return None


def _extract_latency_ms(context: Dict) -> float | None:
    if not isinstance(context, dict):
        return None
    val = context.get("latency_ms")
    if isinstance(val, (int, float)):
        return float(val)
    val = context.get("latency")
    if isinstance(val, (int, float)):
        return float(val)
    return None


def _append_equity_live_record(ts: str, equity: float, adj_pct: float, pct_net: float, r_value: float) -> None:
    EQUITY_CURVE_LIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": ts,
        "equity": float(equity),
        "adj_pct": float(adj_pct),
        "pct_net": float(pct_net),
        "r": float(r_value),
    }
    with EQUITY_CURVE_LIVE_PATH.open("a") as handle:
        handle.write(json.dumps(payload) + "\n")


def _noise_from_trade(trade: Dict[str, Any], noise_bps: float) -> float:
    if noise_bps <= 0:
        return 0.0
    seed_parts = [
        str(trade.get("ts") or trade.get("exit_ts") or ""),
        str(trade.get("id") or trade.get("trade_id") or ""),
        str(trade.get("pct") or trade.get("pnl_pct") or ""),
        str(trade.get("direction") or trade.get("dir") or ""),
    ]
    seed = "|".join(seed_parts).encode("utf-8")
    digest = hashlib.sha256(seed).digest()
    rand = int.from_bytes(digest[:8], "big") / float(1 << 64)
    return (rand * 2.0 - 1.0) * (noise_bps / 10000.0)


def _build_normalized_batch_curve(cfg: Dict[str, Any], start_index: int = 0) -> None:
    """Append normalized equity curve entries for new CLOSE events."""
    try:
        lines = TRADES_PATH.read_text().splitlines()
    except Exception:
        lines = []

    fraction = float(position_sizing.risk_fraction(cfg))
    cap_adj = float(cfg.get("cap_adj_pct", 0.0) or 0.0)
    start_equity = float(cfg.get("start_equity_live", cfg.get("start_equity_norm", 10000.0)))
    fee_bps = float(cfg.get("fees_bps_default", 0.0))
    slip_bps = float(cfg.get("slip_bps_default", 0.0))
    noise_bps = float(cfg.get("batch_noise_bps", 0.0))
    cost = (fee_bps + slip_bps) / 10000.0

    equity = start_equity
    seen_ts: set[str] = set()
    if EQUITY_CURVE_NORM_PATH.exists():
        try:
            for raw in EQUITY_CURVE_NORM_PATH.read_text().splitlines():
                raw = raw.strip()
                if not raw:
                    continue
                entry = json.loads(raw)
                if not isinstance(entry, dict):
                    continue
                ts_val = entry.get("ts")
                if isinstance(ts_val, str):
                    seen_ts.add(ts_val)
                eq_val = entry.get("equity")
                if isinstance(eq_val, (int, float)):
                    equity = float(eq_val)
        except Exception:
            equity = start_equity
            seen_ts.clear()

    if not seen_ts:
        start_index = 0

    entries: List[Dict[str, Any]] = []
    for raw in lines[start_index:]:
        raw = raw.strip()
        if not raw:
            continue
        try:
            trade = json.loads(raw)
        except Exception:
            continue
        event_type = str(trade.get("type") or trade.get("event") or "").lower()
        if event_type != "close":
            continue
        ts = trade.get("ts") or trade.get("exit_ts") or _now()
        if not isinstance(ts, str):
            ts = _now()
        if ts in seen_ts:
            continue
        try:
            adj_pct = float(trade.get("pct", trade.get("pnl_pct", 0.0)))
        except Exception:
            adj_pct = 0.0
        adj_pct = position_sizing.cap_pct(adj_pct, cap_adj)
        noise = _noise_from_trade(trade, noise_bps)
        pct_net = adj_pct + noise - cost
        r_val = pct_net * fraction
        equity = max(0.0, equity * (1.0 + r_val))
        entry = {
            "ts": ts,
            "equity": float(equity),
            "adj_pct": float(adj_pct),
            "pct_net": float(pct_net),
            "r": float(r_val),
            "fraction": fraction,
        }
        entries.append(entry)
        seen_ts.add(ts)

    if not entries:
        return

    try:
        EQUITY_CURVE_NORM_PATH.parent.mkdir(parents=True, exist_ok=True)
        with EQUITY_CURVE_NORM_PATH.open("a") as handle:
            for entry in entries:
                handle.write(json.dumps(entry) + "\n")
    except Exception:
        return

    try:
        pf_weighted.update(source="norm")
    except Exception:
        pass


def _load_policy() -> Dict[str, bool]:
    if not ORCH_SNAPSHOT.exists():
        return {"allow_opens": True, "allow_pa": True}
    try:
        content = ORCH_SNAPSHOT.read_text().strip()
        if not content:
            return {}
        data = json.loads(content)
        policy = data.get("policy", {})
        return {
            "allow_opens": bool(policy.get("allow_opens", True)),
            "allow_pa": bool(policy.get("allow_pa", True)),
        }
    except Exception:
        return {"allow_opens": True, "allow_pa": True}


def _load_exit_config() -> Dict[str, float]:
    gates_path = CONFIG / "gates.yaml"
    try:
        with gates_path.open("r") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception:
        data = {}
    exit_cfg = data.get("EXIT") or data.get("exit") or {}
    if not isinstance(exit_cfg, dict):
        exit_cfg = {}

    def _get_number(key: str, fallback: float, cast=float):
        raw = exit_cfg.get(key)
        if raw is None:
            raw = exit_cfg.get(key.lower())
        try:
            return cast(raw)
        except (TypeError, ValueError):
            return fallback

    decay_bars = max(1, int(_get_number("DECAY_BARS", 8, int)))
    take_profit_conf = float(max(0.0, _get_number("TAKE_PROFIT_CONF", 0.75)))
    stop_loss_conf = float(max(0.0, _get_number("STOP_LOSS_CONF", 0.12)))

    return {
        "DECAY_BARS": decay_bars,
        "TAKE_PROFIT_CONF": take_profit_conf,
        "STOP_LOSS_CONF": stop_loss_conf,
    }


def run_step(entry_min_conf: float = 0.70, exit_min_conf: float = 0.30, reverse_min_conf: float = 0.60):
    # Load config for default symbol/timeframe
    from engine_alpha.core.config_loader import load_engine_config
    cfg = load_engine_config()
    symbol = cfg.get("symbol", "ETHUSDT")
    timeframe = cfg.get("timeframe", "1h")

    exit_cfg = _load_exit_config()
    decay_bars = exit_cfg["DECAY_BARS"]
    take_profit_conf = exit_cfg["TAKE_PROFIT_CONF"]
    stop_loss_conf = exit_cfg["STOP_LOSS_CONF"]

    # Apply regime-specific adjustments (will be updated after regime determination)
    regime_specific_adjustments_done = False

    policy = _load_policy()

    out = get_signal_vector()
    decision = decide(out["signal_vector"], out["raw_registry"])
    final = decision["final"]
    regime = decision["regime"]
    price_based_regime = regime  # For compatibility

    print(f"SIGNAL_PROCESSED: {symbol}_{timeframe} final_dir={final.get('dir')} final_conf={final.get('conf'):.2f}")
    print(f"ABOUT_TO_EXEC_LANE: {symbol}_{timeframe} final_dir={final.get('dir')} final_conf={final.get('conf'):.2f}")
    print(f"REACHED_LANE_EXEC_SECTION: {symbol}_{timeframe} - lane execution section entered")
    print(f"LANE_EXEC_PRE: {symbol}_{timeframe} resolved_lane={resolved_lane_id}")

    # Execute lane-specific logic now that we have signal data
    print(f"LANE_EXEC_DEBUG: {symbol}_{timeframe} executing lane {resolved_lane_id} with final_dir={final.get('dir')} final_conf={final.get('conf'):.2f}")
    try:
        lane_instance = lane_registry.get_lane(resolved_lane_id, {})
        print(f"LANE_EXEC_DEBUG: {symbol}_{timeframe} got lane instance {lane_instance}")
        # Build proper LaneContext object
        lane_ctx = LaneContext(
            symbol=symbol,
            timeframe=timeframe,
            regime=price_based_regime,
            signal_vector={
                "direction": final["dir"],
                "confidence": final["conf"],
                "regime": price_based_regime,
                "close": signal_dict.get("close", 0) if signal_dict else 0,
                "atr": signal_dict.get("atr", 0.02) if signal_dict else 0.02,
            },
            position=None,  # Will be populated if there's an open position
            policy_state=symbol_policy if isinstance(symbol_policy, dict) else {},
            market_data={
                "regime": price_based_regime,
                "regime_info": regime_info,
                "micro_regime": micro_regime_data.get('micro_regime') if micro_regime_data else None,
                "expansion_event": expansion_event
            },
            loop_state={}
        )

        lane_result = lane_instance.execute_tick(lane_ctx)

        if lane_result.decision == LaneDecision.SKIP:
            print(f"LANE_SKIP: {symbol}_{timeframe} lane={resolved_lane_id} reason={lane_result.reason}")
            return  # Skip this symbol

        # Use lane-determined risk multiplier
        risk_mult = lane_result.risk_mult

    except Exception as e:
        print(f"LANE_ERROR: {symbol}_{timeframe} lane={resolved_lane_id} error={e}")
        selected_lane_for_analytics = None  # Error = no trade
        return  # Skip on error

    # Record expansion analytics if we have regime data
    if micro_regime_data:
        regime_for_analytics = {
            "regime": price_based_regime,
            "micro_regime": micro_regime_data.get('micro_regime', 'unknown'),
            "conf": micro_regime_data.get('confidence', 0.0),
            "expansion_event": expansion_event,
            "expansion_strength": micro_regime_data.get('expansion_strength', 0.0),
            "follow_through": micro_regime_data.get('follow_through', False)
        }
        # Determine final selected lane for analytics
        final_selected_lane = resolved_lane_id if 'lane_result' in locals() and lane_result.decision != LaneDecision.SKIP else None
        record_expansion_analytics(symbol, regime_for_analytics, final_selected_lane)

    # For run_step() (batch mode), lane_id will be determined from position data during closes
    # No default lane here - it's per-position

    # Provide defaults for variables that exist in run_step_live() but not here
    chop_micro_churn_throttle = 1.0  # No throttling in batch mode

    print(f"BEFORE_SIGNAL_PROCESSING: {symbol}_{timeframe} about to call get_signal_vector")

    # Use regime-specific thresholds from decision.gates, with parameter as fallback
    gates = decision.get("gates", {})
    regime_entry_min_conf = gates.get("entry_min_conf", entry_min_conf)
    gates_exit_min_conf = gates.get("exit_min_conf", exit_min_conf)
    gates_reverse_min_conf = gates.get("reverse_min_conf", reverse_min_conf)

    pa_status = pa_evaluate(REPORTS / "pa_status.json")
    pa_mult = pa_rmult(REPORTS / "pa_status.json") if policy.get("allow_pa", True) else 1.0
    adapter = risk_eval() or {}
    if not isinstance(adapter, dict):
        adapter = {}
    adapter_mult = float(adapter.get("mult", 1.0))
    adapter_band = adapter.get("band") or "N/A"
    adapter["mult"] = adapter_mult
    adapter["band"] = adapter_band

    # Apply symbol-class-specific risk_mult for CORE lane
    base_rmult = max(0.5, min(1.25, float(pa_mult) * adapter_mult))

    # Lane-specific risk_mult will be applied after lane resolution (lane_id not available yet)
    rmult = base_rmult

    # PAPER + band C override: slightly softer entry threshold for learning
    effective_entry_min_conf = regime_entry_min_conf
    # Chop regime uses higher entry threshold set above (no override needed)
    is_paper_mode = True  # run_step() is PAPER mode
    if is_paper_mode and adapter_band == "C":
        effective_entry_min_conf = max(0.0, regime_entry_min_conf - 0.03)
        print(f"ENTRY-DEBUG: PAPER band=C using softened entry_min_conf={effective_entry_min_conf:.2f} (final_conf={final['conf']:.2f})")

    # Apply regime-specific adjustments after PAPER override
    if price_based_regime == "chop":
        # Increase entry threshold in chop to prevent micro-churn
        effective_entry_min_conf = max(effective_entry_min_conf, 0.80)  # Require very high confidence in chop

    # META-INTELLIGENCE: Assess regime uncertainty and edge half-life
    # This provides second-order intelligence for trading decisions
    uncertainty_metrics = None
    edge_metrics = None

    # Get OHLCV data for meta-intelligence analysis
    from engine_alpha.data.live_prices import get_live_ohlcv
    ohlcv_live = get_live_ohlcv(symbol, timeframe)

    try:
        uncertainty_metrics = assess_regime_uncertainty(
            market_data={
                "closes": ohlcv_live.get("close", [])[-50:] if ohlcv_live.get("close") else [],
                "volumes": ohlcv_live.get("volume", [])[-50:] if ohlcv_live.get("volume") else [],
                "highs": ohlcv_live.get("high", [])[-50:] if ohlcv_live.get("high") else [],
                "lows": ohlcv_live.get("low", [])[-50:] if ohlcv_live.get("low") else [],
            },
            current_regime=regime,
            timestamp=datetime.now(timezone.utc)
        )
    except Exception as e:
        print(f"REGIME_UNCERTAINTY_ERROR: {e}")

    try:
        # Load recent trades for edge analysis
        recent_trades = []
        if TRADES_PATH.exists():
            with TRADES_PATH.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        trade = json.loads(line)
                        if (trade.get("symbol") == symbol and
                            trade.get("type") == "close" and
                            trade.get("pct") is not None):
                            recent_trades.append(trade)
                    except:
                        continue

        # Analyze edge strength using recent performance
        if len(recent_trades) >= 10:
            recent_returns = [t["pct"] for t in recent_trades[-30:]]
            if recent_returns:
                from engine_alpha.research.pf_timeseries import _compute_pf_for_window
                current_pf = _compute_pf_for_window(recent_returns)
                wins = sum(1 for r in recent_returns if r > 0)
                win_rate = wins / len(recent_returns)
                expectancy = sum(recent_returns) / len(recent_returns)

                edge_metrics = analyze_edge_strength(
                    symbol=symbol,
                    pf=current_pf,
                    win_rate=win_rate,
                    expectancy=expectancy,
                    total_trades=len(recent_returns),
                    time_window_days=7,
                    historical_trades=recent_trades[-100:]
                )
    except Exception as e:
        print(f"EDGE_HALF_LIFE_ERROR: {e}")

    # META-INTELLIGENCE: Detect Fair Value Gaps (Observer-only)
    # This identifies structural price dislocations for meta-analysis
    fvg_context = None
    registry = refresh_feature_registry()
    if not registry.is_off("fvg_detector"):
        try:
            # Get OHLCV data for FVG detection (independent of regime uncertainty)
            from engine_alpha.data.live_prices import get_live_ohlcv
            ohlcv_result = get_live_ohlcv(symbol, timeframe)
            print(f"FVG_DEBUG: got OHLCV result type {type(ohlcv_result)}")
            if isinstance(ohlcv_result, tuple) and len(ohlcv_result) >= 1:
                candles_list = ohlcv_result[0]
                print(f"FVG_DEBUG: got {len(candles_list)} candles for {symbol}")
                if candles_list and len(candles_list) > 0:
                    detected_gaps = detect_and_log_fvgs(
                        symbol=symbol,
                        candles=candles_list[-50:],  # Last 50 candles
                        current_regime=regime,
                        timeframe=timeframe
                    )
                    print(f"FVG_DEBUG: detected {len(detected_gaps)} gaps for {symbol}")
                    if detected_gaps:
                        print(f"FVG_DEBUG: gap details - {detected_gaps[0].direction} {detected_gaps[0].gap_size_pct:.2f}%")

            if detected_gaps:
                print(f"FVG_DETECTED: {len(detected_gaps)} new gaps on {symbol} "
                      f"({detected_gaps[0].direction} {detected_gaps[0].gap_size_pct:.2f}%)")

                # Build FVG context for meta-analysis
                from engine_alpha.reflect.fair_value_gaps import fvg_detector
                fvg_context = {
                    "detected_gaps": len(detected_gaps),
                    "recent_gaps": [gap._asdict() for gap in detected_gaps[-3:]],  # Last 3 gaps
                    "fvg_statistics": fvg_detector.get_fvg_statistics(symbol, days_back=7)
                }

        except Exception as e:
            # FVG detection failure shouldn't stop trading
            print(f"FVG_DETECTION_ERROR: {e}")

    # META-INTELLIGENCE: Consult unified meta-decision system
    # This provides comprehensive second-order decision quality assessment
    meta_decision_score = None
    try:
        # Use available variables instead of final[]
        meta_decision_score = assess_meta_decision_quality(
            symbol=symbol,
            decision_type="entry",
            market_context={
                "regime": regime,
                "adapter_band": adapter_band
            }
        )

        # Log meta-intelligence insights
        if meta_decision_score.overall_score < 0.4:
            print(f"META-CAUTION: {symbol} decision score {meta_decision_score.overall_score:.2f} - {meta_decision_score.recommendation}")
        elif meta_decision_score.overall_score > 0.8:
            print(f"META-CONFIDENCE: {symbol} decision score {meta_decision_score.overall_score:.2f} - proceeding with high meta-confidence")

    except Exception as e:
        print(f"META-INTELLIGENCE_ERROR: {e}")

    # Record comprehensive meta-intelligence decision
    record_trading_decision(
        symbol=symbol,
        direction=final["dir"],
        confidence=final["conf"],
        regime=regime,
        entry_price=None,
        market_state={"regime": regime, "adapter_band": adapter_band},
        decision_type="entry_attempt",
        regime_uncertainty=uncertainty_metrics,
        edge_strength=edge_metrics,
        fvg_context=fvg_context
    )

    opened = False
    if policy.get("allow_opens", True):
        # Apply chop micro-churn throttling
        effective_rmult = rmult * chop_micro_churn_throttle

        # DEBUG: Log when we attempt to open
        print(f"OPEN_ATTEMPT: {symbol}_{timeframe} dir={final['dir']} conf={final['conf']:.2f} rmult={effective_rmult:.2f}")

        opened = open_if_allowed(final_dir=final["dir"],
                             final_conf=final["conf"],
                             entry_min_conf=effective_entry_min_conf,
                             risk_mult=effective_rmult,
                             regime=price_based_regime,  # Use price_based_regime directly to avoid variable shadowing
                             risk_band=adapter_band,  # Pass risk_band for observability
                             symbol=symbol,
                             timeframe=timeframe,
                             lane_id=lane_id)
        if opened:
            _annotate_last_open(float(pa_mult), adapter, rmult)
        else:
            # META-INTELLIGENCE: Record inaction when trade blocked by open_if_allowed
            print(f"INACTION_TRIGGERED: {symbol} blocked by open_if_allowed")
            try:
                from engine_alpha.reflect.inaction_performance import record_inaction_decision
                # Determine the specific barrier that blocked the trade
                barrier_type = "entry_min_conf" if final["conf"] < effective_entry_min_conf else "pretrade_check"
                barrier_reason = f"conf_{final['conf']:.2f}_below_min_{effective_entry_min_conf:.2f}" if final["conf"] < effective_entry_min_conf else "pretrade_checks_failed"

                # Use available variables for inaction recording
                record_inaction_decision(
                    symbol=symbol,
                    intended_direction=1,  # Default to long for blocked trades
                    confidence=0.5,  # Neutral confidence for blocked trades
                    regime=regime,
                    barrier_type=barrier_type,
                    barrier_reason=barrier_reason,
                    market_state={"regime": regime, "adapter_band": adapter_band, "entry_min_conf": effective_entry_min_conf}
                )
                print(f"INACTION_RECORDED: {symbol}")
            except Exception as e:
                print(f"INACTION_RECORDING_ERROR: {e}")
    else:
        # META-INTELLIGENCE: Record inaction when trade blocked by policy
        print(f"INACTION_TRIGGERED: {symbol} blocked by policy")
        try:
            from engine_alpha.reflect.inaction_performance import record_inaction_decision
            record_inaction_decision(
                symbol=symbol,
                intended_direction=0,  # No direction for policy-blocked trades
                confidence=0.0,  # Zero confidence for blocked trades
                regime=regime,
                barrier_type="policy_block",
                barrier_reason="policy_allows_opens_false",
                market_state={"regime": regime, "adapter_band": adapter_band}
            )
            print(f"INACTION_RECORDED: {symbol}")
        except Exception as e:
            print(f"INACTION_RECORDING_ERROR: {e}")

    pos = get_open_position()
    if pos and pos.get("dir"):
        pos["bars_open"] = pos.get("bars_open", 0) + 1
        set_position(pos)
        same_dir = final["dir"] != 0 and final["dir"] == pos["dir"]
        opposite_dir = final["dir"] != 0 and final["dir"] != pos["dir"]
        take_profit = same_dir and final["conf"] >= take_profit_conf
        stop_loss = opposite_dir and final["conf"] >= stop_loss_conf
        flip = (final["dir"] != 0 and final["dir"] != pos["dir"] and final["conf"] >= gates_reverse_min_conf)
        drop = (final["conf"] < gates_exit_min_conf)
        decay = (pos["bars_open"] >= decay_bars)

        # PnL pct calculation summary (for run_step exits):
        # - take_profit: pct = abs(conf) [positive, uses confidence as proxy]
        # - stop_loss: pct = -abs(conf) [negative, uses confidence as proxy]
        # - flip/drop/decay: pct = conf (same_dir) or -conf (opposite_dir) [uses confidence as proxy]
        # - uses final["conf"] (confidence score), NOT actual entry_price/exit_price differences
        # - does NOT use entry_price/exit_price directly (this is what we will fix)
        # - entry_px is stored as 1.0 (dummy value), exit_px is never tracked
        close_pct = None
        if take_profit:
            print(f"EXIT-DEBUG: TP hit conf={final['conf']:.4f} >= take_profit_conf={take_profit_conf:.4f}")
            close_pct = abs(float(final.get("conf", 0.0)))
        elif stop_loss:
            close_pct = -abs(float(final.get("conf", 0.0)))
        elif drop:
            print(f"EXIT-DEBUG: EXIT-MIN hit conf={final['conf']:.4f} < exit_min_conf={gates_exit_min_conf:.4f}")
            close_pct = float(final.get("conf", 0.0)) if same_dir else -float(final.get("conf", 0.0))
        elif flip:
            print(f"EXIT-DEBUG: REVERSE hit dir={final['dir']} conf={final['conf']:.4f} >= reverse_min_conf={gates_reverse_min_conf:.4f}")
            close_pct = float(final.get("conf", 0.0)) if same_dir else -float(final.get("conf", 0.0))
        elif decay:
            close_pct = float(final.get("conf", 0.0)) if same_dir else -float(final.get("conf", 0.0))

        if close_pct is not None:
            # Use stored regime from position for exit logging
            stored_regime = pos.get("regime") or pos.get("regime_at_entry") or regime or "unknown"

            # DEBUG: Log position regime data for debugging
            print(f"REGIME_DEBUG_CLOSE: {symbol}_{timeframe} pos={pos} current_regime={regime} stored_regime={stored_regime}")
            print(f"REGIME_DEBUG_CLOSE: pos keys: {list(pos.keys()) if pos else 'None'}")

            # Regression check: warn if we're closing with unknown regime but position had stored regime
            if stored_regime == "unknown" and (pos.get("regime") or pos.get("regime_at_entry")):
                print(f"REGIME_REGRESSION_WARNING: {symbol}_{timeframe} close with unknown regime but position had stored regime")
            # Get lane_id from position data (positions remember their opening lane)
            pos_lane_id = pos.get('lane_id') if pos else None
            actual_lane_id = pos_lane_id or lane_id  # Fallback to global default if position doesn't have it
            close_now(pct=close_pct, regime=stored_regime, lane_id=actual_lane_id)

            # Set CORE cooldown after closing a CORE position
            if actual_lane_id == "core":
                try:
                    from engine_alpha.core.config_loader import load_engine_config
                    cfg = load_engine_config()
                    core_cooldown_seconds = cfg.get("core_cooldown_seconds", 900)  # Default 15 minutes
                    cooldown_until_dt = datetime.now(timezone.utc) + timedelta(seconds=core_cooldown_seconds)
                    cooldown_until_iso = cooldown_until_dt.isoformat().replace("+00:00", "Z")
                    _CORE_COOLDOWN[symbol] = cooldown_until_iso
                    _save_core_cooldowns(_CORE_COOLDOWN)
                    print(f"CORE_COOLDOWN_SET: {symbol} for {core_cooldown_seconds}s (reason: core_close)")
                except Exception as e:
                    print(f"CORE_COOLDOWN_SET_ERROR: {symbol} {e}")

            clear_position()
            if flip and policy.get("allow_opens", True):
                if open_if_allowed(
                    final_dir=final["dir"],
                    final_conf=final["conf"],
                    entry_min_conf=effective_entry_min_conf,
                    risk_mult=rmult,
                    regime=price_based_regime,  # Use price_based_regime directly to avoid variable shadowing
                    risk_band=adapter_band,  # Pass risk_band for observability
                    symbol=symbol,
                    timeframe=timeframe,
                    lane_id=lane_id,
                ):
                    _annotate_last_open(float(pa_mult), adapter, rmult)

    update_pf_reports(TRADES_PATH,
                      REPORTS / "pf_local.json",
                      REPORTS / "pf_live.json")

    # Update opportunity density tracking
    try:
        # Determine if this represents a trading opportunity
        # Opportunity exists when we have a clear directional signal with reasonable confidence
        is_opportunity = (
            final["dir"] != 0 and  # Clear direction
            final["conf"] >= 0.3 and  # Reasonable confidence threshold
            regime != "unknown"  # Valid regime classification
        )

        # Update opportunity state
        opp_state = load_state()
        opp_state, opp_metrics = update_opportunity_state(
            opp_state,
            _now(),
            regime,
            is_eligible=is_opportunity,
            alpha=0.05
        )
        save_state(opp_state)

        # Log opportunity event for snapshot analysis
        from engine_alpha.core.atomic_io import atomic_append_jsonl
        opportunity_event = {
            "ts": _now(),
            "symbol": symbol,
            "timeframe": timeframe,
            "regime": regime,
            "final_dir": final["dir"],
            "final_conf": final["conf"],
            "eligible": is_opportunity,
            "eligible_reason": "signal_ready" if is_opportunity else "low_confidence",
            "density_current": opp_metrics.get("density_current", 0.0),
        }
        atomic_append_jsonl(REPORTS / "opportunity_events.jsonl", opportunity_event)

    except Exception as e:
        # Opportunity tracking failure shouldn't stop trading
        print(f"OPPORTUNITY_UPDATE_ERROR: {e}")

    return {"ts": _now(),
            "regime": regime,
            "final": final,
            "policy": policy,
            "pa": {"armed": bool(pa_status.get("armed")), "rmult": float(pa_mult)},
            "risk_adapter": adapter}


# run_step_live gating summary:
# - uses final_dir = final["dir"] (from decide(), -1/0/+1)
# - uses final_conf = final["conf"] (confidence score from decide())
# - conditions for executing a trade (writes to REPORTS/trades.jsonl):
#   OPENS: policy.allow_opens=True AND final_dir != 0 AND not duplicate position AND
#          passes _try_open gates (risk_r > 0, can_open(), pretrade_check(), open_if_allowed with entry_min_conf)
#   CLOSES: if position exists, triggers on: take_profit (same_dir AND conf >= take_profit_conf),
#           stop_loss (opposite_dir AND conf >= stop_loss_conf), flip (opposite_dir AND conf >= reverse_min_conf),
#           drop (conf < exit_min_conf), or decay (bars_open >= decay_bars)
# - trades emitted via: open_if_allowed() writes "open" events, close_now() writes "close" events
def run_step_live(symbol: str = "ETHUSDT",
                  timeframe: str = "1h",
                  limit: int = 200,
                  entry_min_conf: float = 0.70,
                  exit_min_conf: float = 0.30,
                  reverse_min_conf: float = 0.60,
                  bar_ts: str | None = None,
                  now: Optional[datetime] = None):
    """
    Run one step of the trading loop.

    Args:
        symbol: Trading symbol (e.g., "ETHUSDT")
        timeframe: Timeframe (e.g., "1h")
        limit: Number of bars to fetch for signals
    """
    print(f"RUN_STEP_LIVE_START: {symbol}_{timeframe}")
    # Phase 51: Anti-Thrash Guardrails - Reset per-bar state
    global _LAST_BAR_STATE

    # Phase 5J-R: Clean up expired chop exploration cooldowns
    _cleanup_expired_chop_cooldowns()

    # Use provided now or current UTC time
    if now is None:
        now = datetime.now(timezone.utc)
    
    current_bar_ts = bar_ts or _now()
    if _LAST_BAR_STATE.get("bar_ts") != current_bar_ts:
        # New bar → reset per-bar state
        _LAST_BAR_STATE["bar_ts"] = current_bar_ts
        _LAST_BAR_STATE["opened_this_bar"] = False
    
    # Prune old bad exits (older than BAD_EXIT_WINDOW_SECONDS)
    now_dt = now
    recent_bad_exits = [
        exit_ts for exit_ts in _LAST_BAR_STATE.get("recent_bad_exits", [])
        if (now_dt - exit_ts).total_seconds() <= _BAD_EXIT_WINDOW_SECONDS
    ]
    _LAST_BAR_STATE["recent_bad_exits"] = recent_bad_exits
    
    exit_cfg = _load_exit_config()
    decay_bars = exit_cfg["DECAY_BARS"]
    take_profit_conf_base = exit_cfg["TAKE_PROFIT_CONF"]
    stop_loss_conf_base = exit_cfg["STOP_LOSS_CONF"]

    policy = _load_policy()
    print(f"POLICY_LOADED: {symbol} policy_keys={list(policy.keys()) if policy else 'None'}")

    # Load symbol policy state and resolve lane
    from engine_alpha.risk.symbol_state import load_symbol_states
    symbol_states = load_symbol_states()
    sym_policy_map = symbol_states.get("symbols", {}) if isinstance(symbol_states, dict) else {}
    symbol_policy = sym_policy_map.get(symbol, {}) if isinstance(sym_policy_map, dict) else {}

    # Lane resolution moved to after regime determination

    # Phase 52.5: Price-based regime detection
    # Get OHLCV rows for price-based regime classification
    rows = get_live_ohlcv(symbol, timeframe, limit=limit, no_cache=True)
    # Use last 20 bars for regime detection (or all if fewer available)
    window = rows[-20:] if len(rows) >= 20 else rows
    
    # Use full regime classifier for all modes (LAB/BACKTEST now matches LIVE/PAPER)
    DEBUG_REGIME = os.getenv("DEBUG_REGIME", "0") == "1"
    DEBUG_SIGNALS = os.getenv("DEBUG_SIGNALS", "0") == "1"
    
    regime_info = classify_regime(window)
    price_based_regime = regime_info.get("regime", "chop")
    regime_metrics = regime_info.get("metrics", {})
    if DEBUG_REGIME:
        print(f"REGIME-DEBUG: price_based_regime={price_based_regime} metrics={regime_metrics}")

    # Resolve execution lane using canonical logic (single source of truth)
    # Now that we have regime information, we can make informed lane decisions

    # Load micro-regime data from regime fusion if available
    micro_regime_data = None
    expansion_event = False
    try:
        from engine_alpha.core.regime_fusion import REPORT_PATH
        import json
        if REPORT_PATH.exists():
            with open(REPORT_PATH, 'r') as f:
                fusion_data = json.load(f)
                symbol_key = f"{symbol}:{timeframe}"
                symbol_data = None
                if symbol_key in fusion_data.get('symbols', {}):
                    symbol_data = fusion_data['symbols'][symbol_key]
                elif timeframe == "1h":
                    # Fallback to 15m data for 1h trading (regime analysis done on 15m)
                    fallback_key = f"{symbol}:15m"
                    if fallback_key in fusion_data.get('symbols', {}):
                        symbol_data = fusion_data['symbols'][fallback_key]
                        print(f"MICRO_REGIME_FALLBACK: Using 15m data for {symbol} 1h trading")

                if symbol_data and 'micro_regime' in symbol_data:
                    micro_regime_data = symbol_data['micro_regime']
                    expansion_event = micro_regime_data.get('expansion_event', False)
                    print(f"MICRO_REGIME_LOADED: {symbol} expansion_event={expansion_event}, micro_regime={micro_regime_data.get('micro_regime')}")
                else:
                    print(f"MICRO_REGIME_MISSING: {symbol} no micro_regime data found")
    except Exception as e:
        # Micro-regime data not available, continue without it
        pass

    lane_context = {
        "regime": price_based_regime,
        "regime_info": regime_info,
        "timeframe": timeframe,
        "micro_regime": micro_regime_data.get('micro_regime') if micro_regime_data else None,
        "expansion_event": expansion_event,
    }
    # Phase: CORE chop entry block (CORE must NOT scalp) - BEFORE lane resolution
    if price_based_regime == "chop" and not expansion_event:
        # Force lane to exploration for chop regime when no expansion event (CORE never trades chop)
        lane_context_forced = lane_context.copy()
        lane_context_forced["force_exploration"] = True

        lane_id = resolve_lane(symbol, symbol_policy, lane_context_forced)
        if lane_id == "core":
            # This shouldn't happen with force_exploration, but double-check
            print(f"CORE_ENTRY_BLOCK_CHOP: {symbol}_{timeframe} regime={price_based_regime} - Forcing exploration for chop")
            lane_id = "exploration"
    else:
        # Allow normal lane resolution (including EXPANSION) in chop if expansion_event is present
        lane_id = resolve_lane(symbol, symbol_policy, lane_context)

    # Store resolved lane_id for later execution after signal processing
    resolved_lane_id = lane_id
    print(f"LANE_RESOLVED: {symbol}_{timeframe} resolved_lane={resolved_lane_id}")

    # Lane-specific risk_mult will be applied after final rmult calculation

    lane_reason = f"policy_stage_{symbol_policy.get('stage', 'unknown')}_allow_core_{symbol_policy.get('allow_core', False)}_regime_{price_based_regime}"

    # Phase: CORE lane cooldown enforcement (15min after CORE close)
    if lane_id == "core":
        now_dt = datetime.now(timezone.utc)
        core_cooldown_iso = _CORE_COOLDOWN.get(symbol)
        if core_cooldown_iso:
            try:
                core_cooldown_dt = datetime.fromisoformat(core_cooldown_iso.replace("Z", "+00:00"))
                if now_dt < core_cooldown_dt:
                    remaining_seconds = (core_cooldown_dt - now_dt).total_seconds()
                    remaining_minutes = remaining_seconds / 60
                    print(f"CORE_COOLDOWN_BLOCK: {symbol}_{timeframe} remaining={remaining_minutes:.1f}min reason=core_cooldown")
                    return  # Early return - skip this symbol entirely
                else:
                    # Cooldown expired, remove it
                    del _CORE_COOLDOWN[symbol]
                    _save_core_cooldowns(_CORE_COOLDOWN)
                    print(f"CORE_COOLDOWN_EXPIRED: {symbol} cooldown passed")
            except Exception as e:
                print(f"CORE_COOLDOWN_ERROR: {symbol} invalid cooldown {core_cooldown_iso}: {e}")

    # Phase 5J-R: Early chop exploration cooldown check (before signal processing)
    if price_based_regime == "chop":
        now_dt = datetime.now(timezone.utc)
        cooldown_iso = _CHOP_EXPLORATION_COOLDOWN.get(symbol)
        if cooldown_iso:
            try:
                cooldown_dt = datetime.fromisoformat(cooldown_iso.replace("Z", "+00:00"))
                if now_dt < cooldown_dt:
                    remaining_seconds = (cooldown_dt - now_dt).total_seconds()
                    remaining_minutes = remaining_seconds / 60
                    print(f"CHOP_EXPLORATION_COOLDOWN: {symbol} blocked, {remaining_minutes:.1f}min remaining")
                    return  # Early return - skip this symbol entirely
                else:
                    print(f"COOLDOWN_EXPIRED: {symbol} cooldown passed")
            except Exception as e:
                print(f"CHOP_COOLDOWN_PARSE_ERROR: {symbol} {cooldown_iso} - {e}")
                del _CHOP_EXPLORATION_COOLDOWN[symbol]
                _save_chop_cooldowns(_CHOP_EXPLORATION_COOLDOWN)

    print(f"AFTER_CHOP_COOLDOWN: {symbol}_{timeframe} continuing to signal processing")

    # Phase: Chop Micro-Churn Detection and Throttling
    def _detect_chop_micro_churn_throttle(symbol: str, timeframe: str) -> float:
        """
        Detect micro-churn in chop regime and apply throttling.
        Returns multiplier < 1.0 to reduce trading activity when micro-churn detected.
        """
        try:
            # Load recent trades for this symbol/timeframe
            trades_file = REPORTS / "trades.jsonl"
            if not trades_file.exists():
                return 1.0

            cutoff = datetime.now(timezone.utc) - timedelta(hours=1)  # Last hour
            recent_trades = []

            with trades_file.open("r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        trade = json.loads(line)
                        if (trade.get("type") == "close" and
                            trade.get("symbol") == symbol.upper() and
                            trade.get("timeframe") == timeframe.lower()):
                            ts = trade.get("ts")
                            if ts:
                                dt = _parse_timestamp(ts)
                                if dt and dt >= cutoff:
                                    recent_trades.append(trade)
                    except Exception:
                        continue

            if len(recent_trades) < 5:
                return 1.0  # Not enough data

            # Analyze for micro-churn: trades that last < 30 seconds
            micro_churn_count = 0
            total_trades = len(recent_trades)

            for trade in recent_trades:
                entry_ts = trade.get("entry_ts") or trade.get("ts")
                exit_ts = trade.get("ts") or trade.get("exit_ts")
                if entry_ts and exit_ts:
                    try:
                        entry_dt = _parse_timestamp(entry_ts)
                        exit_dt = _parse_timestamp(exit_ts)
                        duration = (exit_dt - entry_dt).total_seconds()
                        if duration < 30:  # Micro-churn threshold
                            micro_churn_count += 1
                    except Exception:
                        continue

            micro_churn_rate = micro_churn_count / total_trades

            # Apply throttling based on micro-churn rate
            if micro_churn_rate > 0.5:  # >50% micro-churn
                print(f"CHOP_MICRO_CHURN_THROTTLE: {symbol}_{timeframe} rate={micro_churn_rate:.2f} micro={micro_churn_count}/{total_trades} -> 0.3x")
                return 0.3  # Heavy throttling
            elif micro_churn_rate > 0.3:  # >30% micro-churn
                print(f"CHOP_MICRO_CHURN_THROTTLE: {symbol}_{timeframe} rate={micro_churn_rate:.2f} micro={micro_churn_count}/{total_trades} -> 0.6x")
                return 0.6  # Moderate throttling
            elif micro_churn_rate > 0.2:  # >20% micro-churn
                print(f"CHOP_MICRO_CHURN_THROTTLE: {symbol}_{timeframe} rate={micro_churn_rate:.2f} micro={micro_churn_count}/{total_trades} -> 0.8x")
                return 0.8  # Light throttling

            return 1.0  # No throttling

        except Exception as e:
            print(f"CHOP_MICRO_CHURN_ERROR: {e}")
            return 1.0  # Fail-safe: no throttling

    # Phase: Chop Micro-Churn Throttling
    chop_micro_churn_throttle = 1.0
    if price_based_regime == "chop":
        chop_micro_churn_throttle = _detect_chop_micro_churn_throttle(symbol, timeframe)
        if chop_micro_churn_throttle < 1.0:
            print(f"CHOP_MICRO_CHURN_THROTTLE: {symbol}_{timeframe} regime={price_based_regime} throttle={chop_micro_churn_throttle:.2f}")

    print(f"AFTER_MICRO_CHURN: {symbol} continuing to signal processing")

    # Extract volatility metrics for Phase 54
    atr_pct = regime_metrics.get("atr_pct", 0.0)
    vol_expansion = regime_metrics.get("vol_expansion", 1.0)
    slope = regime_metrics.get("slope", 0.0)
    
    # Phase: Stabilization - Unified regime classification (no special modes)
    # Regime is determined purely from price data, same for all modes

    try:
        out = get_signal_vector_live(symbol=symbol, timeframe=timeframe, limit=limit)
        print(f"SIGNAL_VECTOR_GOT: {symbol} signals={len(out.get('signal_vector', []))}")
        # Pass price-based regime to decide() so council aggregation uses correct regime
        decision = decide(out["signal_vector"], out["raw_registry"], regime_override=price_based_regime)
        print(f"DECIDE_COMPLETED: {symbol} decision_keys={list(decision.keys()) if decision else 'None'}")
        final = decision["final"]
        print(f"FINAL_DECISION: {symbol} dir={final.get('dir')} conf={final.get('conf'):.3f}")
    except Exception as e:
        print(f"SIGNAL_PROCESSING_ERROR: {symbol} {e}")
        return  # Early return on signal processing error
    # Use price-based regime (already passed to decide(), but keep for consistency)
    regime = price_based_regime

    # Apply regime-specific adjustments after signal processing
    # (Moved to after effective_entry_min_conf declaration)

    # Phase 52.5: Map panic_down to trend_down for weights lookup
    # Note: We use REGIME_BUCKET_WEIGHTS, not COUNCIL_WEIGHTS (legacy)
    regime_for_weights = "trend_down" if regime == "panic_down" else regime
    
    # Phase 52: Chop Stabilization - Adjust TP/SL thresholds in chop regime (PAPER only)
    if IS_PAPER_MODE and regime == "chop":
        take_profit_conf = 0.60  # Slightly easier to take profit
        stop_loss_conf = 0.50     # More confident before calling it a loss
    elif IS_PAPER_MODE and regime in ("trend_down", "high_vol"):
        # Lower TP threshold for trend_down/high_vol to increase TP/SL ratio vs drop/decay
        # Entry thresholds are 0.52-0.58, so TP at 0.60 is more achievable (only 0.02-0.08 increase needed)
        # This makes TP more likely to fire before drop/decay, increasing meaningful trades
        take_profit_conf = 0.60  # Lower from 0.65 to 0.60 (matching chop regime) to capture more TP exits
        stop_loss_conf = stop_loss_conf_base  # Keep SL threshold unchanged
    else:
        take_profit_conf = take_profit_conf_base
        stop_loss_conf = stop_loss_conf_base
    
    # Direction/confidence summary:
    # - final_dir and final_conf come from council aggregation in decide() (confidence_engine.py)
    # - Signal vector (12 signals) → bucket scores (5 buckets: momentum, meanrev, flow, positioning, timing)
    # - Bucket directions: dir_i = sign(score_i) if abs(score_i) >= DIR_THRESHOLD (0.05), else 0
    #   (DIR_THRESHOLD defined in confidence_engine.py line 57, used in _compute_bucket_directions)
    # - Bucket confidences: conf_i = clip(abs(score_i), 0, 1)
    # - Council aggregation: final_score = Σ (council_weight_i * dir_i * conf_i) where weights vary by regime
    # - final_dir = sign(final_score): 1 if final_score > 0, -1 if final_score < 0, 0 if final_score == 0
    # - final_conf = clip(abs(final_score), 0, 1)
    # - Note: DIR_THRESHOLD (0.05) is used at bucket level, not for final_dir (any non-zero final_score → non-zero dir)
    
    # Use base result from decide() (already computed with REGIME_BUCKET_WEIGHTS)
    # Then apply Phase 54 regime-aware bucket emphasis (PAPER only) as a post-processing step
    base_final = final  # From decide(): {"dir": ..., "conf": ..., "score": ...}
    base_final_score = base_final.get("score", 0.0)
    
    # Phase 54: Regime-aware bucket emphasis (PAPER only)
    # Apply small multipliers to bucket weights based on regime, then recompute final_score
    # This is a post-processing step that adjusts the base aggregation from decide()
    bucket_debug = []  # Initialize for debug logging
    if IS_PAPER_MODE:
        from engine_alpha.core.confidence_engine import REGIME_BUCKET_WEIGHTS, BUCKET_ORDER
        buckets = decision.get("buckets", {})
        
        # Extract bucket dirs/confs for Phase 54 adjustments
        bucket_dirs = {name: buckets.get(name, {}).get("dir", 0) for name in BUCKET_ORDER}
        bucket_confs = {name: buckets.get(name, {}).get("conf", 0.0) for name in BUCKET_ORDER}
        
        # Phase 54: Regime-aware bucket emphasis multipliers
        bucket_weight_adj = {name: 1.0 for name in BUCKET_ORDER}
        if regime in ("trend_down", "trend_up"):
            bucket_weight_adj["momentum"] = 1.10
            bucket_weight_adj["flow"] = 1.05
            bucket_weight_adj["positioning"] = 1.05
        elif regime == "chop":
            registry = refresh_feature_registry()
            mode = registry.mode("chop_meanrev_override")
            if registry.is_enforce("chop_meanrev_override"):
                bucket_weight_adj["meanrev"] = 1.10
                bucket_weight_adj["flow"] = 0.90
                print(f"CHOP_MEANREV_OVERRIDE: applied meanrev=1.10, flow=0.90 (enforce mode)")
            elif registry.is_observe("chop_meanrev_override"):
                # In observe mode, compute but don't apply
                print(f"CHOP_MEANREV_OVERRIDE: would adjust meanrev=1.10, flow=0.90 (observe mode)")
            # else: off mode - no adjustment
        
        # Recompute final_score with Phase 54 adjustments
        regime_weights = REGIME_BUCKET_WEIGHTS.get(regime, REGIME_BUCKET_WEIGHTS.get("chop", {}))
        weighted_score = 0.0
        weight_sum = 0.0
        
        for bucket_name in BUCKET_ORDER:
            bucket_dir = bucket_dirs.get(bucket_name, 0)
            bucket_conf = bucket_confs.get(bucket_name, 0.0)
            base_weight = float(regime_weights.get(bucket_name, 0.0))
            adjusted_weight = base_weight * bucket_weight_adj.get(bucket_name, 1.0)
            
            if bucket_dir == 0 or adjusted_weight <= 0.0 or bucket_conf <= 0.0:
                continue
            
            score = bucket_dir * bucket_conf
            weighted_score += adjusted_weight * score
            weight_sum += adjusted_weight
            bucket_debug.append({
                "name": bucket_name,
                "dir": int(bucket_dir),
                "conf": float(bucket_conf),
                "weight": float(adjusted_weight),
            })
        
        if weight_sum > 0.0:
            base_final_score = weighted_score / weight_sum
    else:
        # In LIVE mode, use buckets from decide() for debug logging
        from engine_alpha.core.confidence_engine import BUCKET_ORDER
        buckets = decision.get("buckets", {})
        for bucket_name in BUCKET_ORDER:
            bucket_data = buckets.get(bucket_name, {})
            bucket_dir = bucket_data.get("dir", 0)
            bucket_conf = bucket_data.get("conf", 0.0)
            if bucket_dir != 0 and bucket_conf > 0.0:
                bucket_debug.append({
                    "name": bucket_name,
                    "dir": int(bucket_dir),
                    "conf": float(bucket_conf),
                    "weight": 0.0,  # Not used in LIVE mode
                })
    
    # Apply neutral zone logic: if base_final_score magnitude is below threshold, set dir=0
    # Use same neutral zone for all modes (unified behavior)
    # NOTE: Neutral zone is applied ONCE here, not in decide()
    score_abs = abs(base_final_score)
    if score_abs < NEUTRAL_THRESHOLD:
        effective_final_dir = 0
        effective_final_conf = score_abs
    else:
        effective_final_dir = 1 if base_final_score > 0 else -1
        effective_final_conf = min(score_abs, 1.0)
    
    # Round confidence to match decide() output format
    effective_final_conf = round(effective_final_conf, 2)
    
    # SIGNAL-DEBUG: Log bucket-level details and council aggregation
    # (DEBUG_SIGNALS already defined earlier in function)
    
    # Phase 52.5: Panic/Flush regime behavior (PAPER mode only)
    # Mild confidence boost for panic_down to acknowledge stronger regime signal
    if IS_PAPER_MODE and regime == "panic_down":
        effective_final_conf = min(1.0, effective_final_conf + 0.05)
        if DEBUG_SIGNALS:
            print(f"SIGNAL-DEBUG: panic_down conf boost applied: final_conf={effective_final_conf:.2f}")
    if DEBUG_SIGNALS:
        ts_str = bar_ts or _now()
        bucket_str = "; ".join(
            f"{b['name']}:dir={b['dir']},conf={b['conf']:.2f},w={b['weight']:.3f}"
            for b in bucket_debug
        )
        print(
            f"SIGNAL-DEBUG: ts={ts_str} regime={regime} "
            f"buckets={bucket_str} | "
            f"base_final_score={base_final_score:.4f} final_dir={effective_final_dir} final_conf={effective_final_conf:.2f}"
        )
        if effective_final_dir == 0:
            print(f"SIGNAL-DEBUG: neutralized base_final_score={base_final_score:.4f} < NEUTRAL_THRESHOLD={NEUTRAL_THRESHOLD:.2f}")
    
    # Get gates from decision (for exit thresholds)
    gates = decision.get("gates", {})
    gates_exit_min_conf_base = gates.get("exit_min_conf", exit_min_conf)
    # Lower drop threshold for trend_down/high_vol to reduce drop exits and increase TP/SL ratio
    # Drop fires when conf < exit_min_conf, so lowering exit_min_conf (0.25 vs 0.30) makes drop fire LESS often
    if IS_PAPER_MODE and regime in ("trend_down", "high_vol"):
        gates_exit_min_conf = 0.25  # Lower from 0.30 to reduce drop exits (only fires when conf < 0.25)
    else:
        gates_exit_min_conf = gates_exit_min_conf_base
    gates_reverse_min_conf = gates.get("reverse_min_conf", reverse_min_conf)
    
    # Evaluate risk adapter to get risk_band (needed for threshold computation)
    pa_status = pa_evaluate(REPORTS / "pa_status.json")
    pa_mult = pa_rmult(REPORTS / "pa_status.json") if policy.get("allow_pa", True) else 1.0
    adapter = risk_eval() or {}
    if not isinstance(adapter, dict):
        adapter = {}
    adapter_mult = float(adapter.get("mult", 1.0))
    adapter_band = adapter.get("band") or "A"
    
    # Compute entry threshold using simplified helper (regime + risk_band only)
    effective_min_conf_live = compute_entry_min_conf(price_based_regime, adapter_band)
    
    # Debug logging for thresholds (low-volume, per bar)
    if DEBUG_SIGNALS:
        print(f"THRESHOLDS: regime={price_based_regime} risk_band={adapter_band} entry_min={effective_min_conf_live:.2f}")
        print(f"EXIT-THRESHOLDS: regime={price_based_regime} tp_conf={take_profit_conf:.2f} sl_conf={stop_loss_conf:.2f}")
    adapter["mult"] = adapter_mult
    adapter["band"] = adapter_band
    rmult = max(0.5, min(1.25, float(pa_mult) * adapter_mult))

    # Apply lane-specific risk_mult adjustments now that lane_id is resolved and rmult is final
    if lane_id in ["core", "scalp", "exploration"]:
        from engine_alpha.loop.lanes.resolver import get_symbol_class, get_lane_defaults
        symbol_class = get_symbol_class(symbol)
        lane_defaults = get_lane_defaults(lane_id, symbol_class)
        lane_specific_rmult = lane_defaults.get("risk_mult", rmult)  # fallback to current rmult if not found
        rmult = lane_specific_rmult


    # Phase 56: Dynamic Risk Scaling - Regime-based risk multiplier (PAPER only)
    def _regime_rmult(price_based_regime: str) -> float:
        """
        Regime-based risk multiplier for PAPER mode ONLY.
        LIVE mode always uses 1.0 here.
        
        Multipliers are modest and bounded.
        """
        # Base assumption: neutral = 1.0
        if price_based_regime == "panic_down":
            return 1.50  # only in PAPER; still combined with band_mult
        if price_based_regime in ("trend_down", "trend_up"):
            return 1.25
        if price_based_regime == "high_vol":
            return 0.75
        if price_based_regime == "chop":
            return 0.40
        # Unknown regime: neutral
        return 1.0
    
    # Phase 56: Compute regime multiplier (PAPER only)
    if IS_PAPER_MODE:
        regime_mult = _regime_rmult(price_based_regime)
        # Safety bounds
        MAX_RMULT = 1.50  # maximum regime multiplier factor
        MIN_RMULT = 0.20  # smallest meaningful factor
        regime_mult = max(MIN_RMULT, min(regime_mult, MAX_RMULT))
    else:
        regime_mult = 1.0  # LIVE mode unaffected

    live_pos = get_live_position()

    sizing_cfg = position_sizing.cfg()
    allow_live_writes = bool(sizing_cfg.get("write_live_equity", True))
    context_meta = out.get("context", {}) if isinstance(out.get("context", {}), dict) else {}

    equity_live_value = position_sizing.read_equity_live()
    if allow_live_writes and not EQUITY_LIVE_PATH.exists():
        position_sizing.write_equity_live(equity_live_value)

    # Extract final direction and confidence from council decision (with neutral zone override)
    # These values are computed by decide() via council aggregation, then adjusted by neutral zone logic above
    final_dir = effective_final_dir  # -1 (SHORT), 0 (FLAT), or +1 (LONG) - may be overridden to 0 by neutral zone
    final_conf = effective_final_conf  # Confidence score [0.0, 1.0] - adjusted by neutral zone logic
    allow_opens = policy.get("allow_opens", True)

    # DEBUG: force a single tiny test trade when FORCE_TEST_TRADE=1
    if os.getenv("FORCE_TEST_TRADE", "0") == "1":
        print("DEBUG: Forcing test trade (LONG, conf=0.55, size=0.01)")
        # Note: execute_trade doesn't exist, using open_if_allowed as fallback
        # This will only work if policy allows opens and no duplicate position
        open_if_allowed(final_dir=1, final_conf=0.55, entry_min_conf=0.55, risk_mult=1.0)

    def _try_open(direction: int, confidence: float, now: Optional[datetime] = None, regime: Optional[str] = None) -> bool:
        # Phase 51: Anti-Thrash Guardrails - Check guardrails before opening
        global _LAST_BAR_STATE
        
        if direction == 0:
            return False
        
        # Regime gate: only allow entries in trend_down and high_vol (unified for all modes)
        # This is checked here as a safety net, but should already be checked at call site
        # Can be overridden in backtests with BACKTEST_FREE_REGIME=1
        if regime and not regime_allows_entry(regime):
            if DEBUG_SIGNALS:
                free_regime = os.getenv("BACKTEST_FREE_REGIME") == "1"
                gate_msg = "all regimes allowed (BACKTEST_FREE_REGIME=1)" if free_regime else "only trend_down/high_vol allowed"
                print(
                    f"REGIME-GATE: skip open in regime={regime} "
                    f"(dir={direction}, conf={confidence:.4f}) - {gate_msg}"
                )
            return False
        
        # Guardrail 1: Max 1 open per bar
        if _LAST_BAR_STATE.get("opened_this_bar"):
            bar_ts_display = _LAST_BAR_STATE.get("bar_ts", "unknown")
            if DEBUG_SIGNALS:
                print(f"LIVE-GUARD: skip open, already opened on this bar {bar_ts_display}")
            return False
        
        # Guardrail 2: Cooldown between opens (uses simulated time in backtest)
        if now is None:
            now = datetime.now(timezone.utc)
        
        last_open_ts_str = _LAST_BAR_STATE.get("last_open_ts")
        if last_open_ts_str:
            try:
                last_open_dt = datetime.fromisoformat(last_open_ts_str.replace("Z", "+00:00"))
                delta_sec = (now - last_open_dt).total_seconds()
                if delta_sec < _COOL_DOWN_SECONDS:
                    if DEBUG_SIGNALS:
                        print(f"LIVE-GUARD: cooldown active ({delta_sec:.1f}s < {_COOL_DOWN_SECONDS}s), skip open.")
                    return False
            except Exception:
                # If parsing fails, ignore cooldown just this time (safety fallback)
                pass
        
        # Guardrail 4: Cluster SL/drop guard (uses simulated time in backtest)
        if now is None:
            now = datetime.now(timezone.utc)
        
        current_bad_exits = _LAST_BAR_STATE.get("recent_bad_exits", [])
        # Filter bad exits to only those within the window (using simulated time)
        recent_bad_exits = [
            exit_ts for exit_ts in current_bad_exits
            if (now - exit_ts).total_seconds() <= _BAD_EXIT_WINDOW_SECONDS
        ]
        if len(recent_bad_exits) >= _BAD_EXIT_THRESHOLD:
            if DEBUG_SIGNALS:
                print(f"LIVE-GUARD: {len(recent_bad_exits)} SL/drop exits in last {_BAD_EXIT_WINDOW_SECONDS}s, skip open.")
            return False
        
        current_pos = get_live_position()
        current_r = float(current_pos.get("risk_r", 0.0)) if isinstance(current_pos, dict) else 0.0
        equity_live_snapshot = position_sizing.read_equity_live()
        base_risk_r = position_sizing.compute_R(equity_live_snapshot, sizing_cfg)
        
        # Phase 56: Apply band_mult and regime_rmult to base risk
        # band_mult comes from risk_adapter (adapter_mult)
        band_mult = adapter_mult  # From risk_adapter evaluation above
        risk_r = base_risk_r * band_mult * regime_mult
        
        if risk_r <= 0:
            print(f"LIVE-DEBUG: skip trade dir={direction} conf={confidence:.4f} - risk_r={risk_r:.2f} <= 0")
            return False
        
        # Phase 56: Debug logging for risk scaling
        if DEBUG_SIGNALS:
            print(f"RISK-SCALE: mode={'PAPER' if IS_PAPER_MODE else 'LIVE'} band={adapter_band} band_mult={band_mult:.2f} regime={price_based_regime} regime_mult={regime_mult:.2f} base_risk_r={base_risk_r:.2f} risk_r={risk_r:.2f}")
        gross_after = current_r + risk_r
        symbol_after = current_r + risk_r
        # Convert to R units (normalize by risk_r) for can_open check
        # If risk_r is 0, we'd already have returned False above
        if risk_r > 0:
            gross_after_r = gross_after / risk_r
            symbol_after_r = symbol_after / risk_r
        else:
            gross_after_r = 0.0
            symbol_after_r = 0.0
        if not position_sizing.can_open(gross_after_r, symbol_after_r, sizing_cfg):
            print(f"LIVE-DEBUG: skip trade dir={direction} conf={confidence:.4f} - exposure caps: gross={gross_after_r:.2f}R symbol={symbol_after_r:.2f}R (dollars: gross=${gross_after:.2f} symbol=${symbol_after:.2f})")
            return False
        spread_bps = _extract_spread_bps(context_meta)
        latency_ms = _extract_latency_ms(context_meta)
        # Relax pretrade checks when confidence >= 0.65
        high_conf = confidence >= 0.65
        if high_conf:
            # For high confidence, allow up to 2x normal spread/latency limits
            relaxed_cfg = sizing_cfg.copy()
            relaxed_cfg["reject_if_spread_bps_gt"] = float(sizing_cfg.get("reject_if_spread_bps_gt", 20)) * 2.0
            relaxed_cfg["reject_if_latency_ms_gt"] = float(sizing_cfg.get("reject_if_latency_ms_gt", 2000)) * 2.0
            pretrade_ok = position_sizing.pretrade_check(spread_bps, latency_ms, relaxed_cfg)
        else:
            pretrade_ok = position_sizing.pretrade_check(spread_bps, latency_ms, sizing_cfg)
        if not pretrade_ok:
            print(f"LIVE-DEBUG: skip trade dir={direction} conf={confidence:.2f} - pretrade check failed: spread={spread_bps}bps latency={latency_ms}ms")
            return False
        
        # All modes now use same entry logic (LAB/BACKTEST matches LIVE/PAPER)
        opened_local = open_if_allowed(
            final_dir=direction,
            final_conf=confidence,
            entry_min_conf=effective_min_conf_live,
            risk_mult=rmult,
            regime=regime,
            risk_band=adapter_band,
            symbol=symbol,
            timeframe=timeframe,
            lane_id=lane_id
        )
        
        if not opened_local:
            if DEBUG_SIGNALS:
                print(f"LIVE-DEBUG: skip trade dir={direction} conf={confidence:.2f} - open_if_allowed returned False")
            return False
        
        # Phase 51: Anti-Thrash Guardrails - Mark that we opened on this bar
        _LAST_BAR_STATE["opened_this_bar"] = True
        _LAST_BAR_STATE["last_open_ts"] = now.isoformat()
        
        if high_conf:
            print(f"LIVE-DEBUG: HIGH-CONF trade opened dir={direction} conf={confidence:.4f} risk_r={risk_r:.2f}")
        ts_val = bar_ts or _now()
        # Get entry price from latest bar for price-based PnL calculation
        entry_price = 1.0  # fallback to dummy value
        ohlcv_rows = get_live_ohlcv(symbol=symbol, timeframe=timeframe, limit=1)
        if ohlcv_rows and len(ohlcv_rows) > 0:
            entry_price = ohlcv_rows[-1].get("close", 1.0)
        new_pos = {
            "dir": direction,
            "bars_open": 0,
            "entry_px": float(entry_price) if entry_price is not None else 1.0,
            "last_ts": ts_val,
            "risk_r": risk_r,
            "regime": regime,  # Store regime at entry time for exit logging
            "regime_at_entry": regime,  # For debugging
        }
        set_live_position(new_pos)
        set_position(new_pos)
        _annotate_last_open(float(pa_mult), adapter, rmult)
        
        # Log council perf event for open
        if opened_local:
            _log_council_event({
                "event": "open",
                "ts": ts_val,
                "regime": regime,
                "final_dir": int(direction),
                "final_conf": float(confidence),
                "risk_band": adapter_band,
                "risk_mult": float(rmult),
                "buckets": bucket_debug,
            })
        
        return opened_local

    # ------------------------------------------------------------------
    # Entry gating: Unified logic for all modes
    # ------------------------------------------------------------------
    # Step 1: Regime gate (only trend_down and high_vol allowed, unless BACKTEST_FREE_REGIME=1)
    if not regime_allows_entry(price_based_regime):
        if DEBUG_SIGNALS:
            free_regime = os.getenv("BACKTEST_FREE_REGIME") == "1"
            gate_msg = "all regimes allowed (BACKTEST_FREE_REGIME=1)" if free_regime else "only trend_down/high_vol allowed"
            print(
                f"REGIME-GATE: skip open in regime={price_based_regime} "
                f"(dir={effective_final_dir}, conf={effective_final_conf:.2f}) - {gate_msg}"
            )
        # Build result dict for early return
        final = {"dir": effective_final_dir, "conf": effective_final_conf}
        return {
            "ts": bar_ts or _now(),
            "regime": regime,
            "final": final,
            "policy": policy,
            "pa": {"armed": bool(pa_status.get("armed")), "rmult": float(pa_mult)},
            "risk_adapter": adapter,
            "context": out.get("context", {}),
            "equity_live": position_sizing.read_equity_live(),
            "pnl": 0.0,
        }
    
    # Step 2: Check confidence threshold
    # TEMPORARY: More lenient for chop regime testing
    threshold_to_use = effective_min_conf_live
    # Chop regime exploration disabled due to micro-churn - requires high confidence
    # BUT: Allow EXPANSION lane very permissive entry when expansion_event is detected
    expansion_event_active = micro_regime_data and micro_regime_data.get('expansion_event', False)
    is_expansion_lane = resolved_lane_id == "expansion"

    print(f"THRESHOLD_DEBUG: {symbol} regime={regime} lane={resolved_lane_id} expansion_event={expansion_event_active} conf={effective_final_conf:.3f}")

    if regime == "chop" and not (is_expansion_lane and expansion_event_active):
        threshold_to_use = max(threshold_to_use, 0.80)  # Require very high confidence in chop (unless EXPANSION with expansion_event)
        print(f"THRESHOLD_CHOP_PENALTY: {symbol} applied chop penalty, threshold={threshold_to_use}")
    elif is_expansion_lane and expansion_event_active:
        # EXPANSION with expansion_event gets very permissive threshold (matches lane logic)
        threshold_to_use = 0.25
        print(f"THRESHOLD_EXPANSION_BYPASS: {symbol} using EXPANSION threshold {threshold_to_use}")
    else:
        print(f"THRESHOLD_BYPASS: {symbol} bypass chop penalty (expansion_event={expansion_event_active})")

    # Special case: Allow EXPANSION lane with expansion_event + follow_through to bypass confidence threshold
    threshold_rejected = allow_opens and effective_final_dir != 0 and effective_final_conf < threshold_to_use
    follow_through_active = micro_regime_data and micro_regime_data.get('follow_through', False)
    expansion_bypass = (is_expansion_lane and expansion_event_active and follow_through_active)
    print(f"BYPASS_CHECK: {symbol} threshold_rejected={threshold_rejected}, is_expansion_lane={is_expansion_lane}, expansion_event_active={expansion_event_active}, follow_through_active={follow_through_active}, bypass={expansion_bypass}")

    if threshold_rejected and not expansion_bypass:
        if DEBUG_SIGNALS:
            print(f"ENTRY-THRESHOLD: skip trade dir={effective_final_dir} conf={effective_final_conf:.2f} < entry_min={threshold_to_use:.2f}")
        # Build result dict for early return
        final = {"dir": effective_final_dir, "conf": effective_final_conf}
        return {
            "ts": bar_ts or _now(),
            "regime": regime,
            "final": final,
            "policy": policy,
            "pa": {"armed": bool(pa_status.get("armed")), "rmult": float(pa_mult)},
            "risk_adapter": adapter,
            "context": out.get("context", {}),
            "equity_live": position_sizing.read_equity_live(),
            "pnl": 0.0,
        }

    if expansion_bypass and threshold_rejected:
        print(f"EXPANSION_CONFIDENCE_BYPASS: {symbol} conf={effective_final_conf:.3f} < {threshold_to_use:.3f} but expansion_event + follow_through allows continuation")
    
    # META-INTELLIGENCE: Record inaction for decisions that cannot proceed
    # This catches blocking at the FINAL_DECISION level with deduplication
    _log_inaction_if_blocked(symbol, timeframe, effective_final_dir, effective_final_conf,
                           price_based_regime, allow_opens, effective_min_conf_live)

    # LANE EXECUTION: Execute lane-specific logic now that we have signal data
    print(f"LANE_EXEC_PRE: {symbol}_{timeframe} resolved_lane={resolved_lane_id}")

    # Execute lane-specific logic now that we have signal data
    print(f"LANE_EXEC_DEBUG: {symbol}_{timeframe} executing lane {resolved_lane_id} with final_dir={effective_final_dir} final_conf={effective_final_conf:.2f}")
    try:
        lane_instance = lane_registry.get_lane(resolved_lane_id, {})
        print(f"LANE_EXEC_DEBUG: {symbol}_{timeframe} got lane instance {lane_instance}")
        # Build proper LaneContext object
        lane_ctx = LaneContext(
            symbol=symbol,
            timeframe=timeframe,
            regime=price_based_regime,
            signal_vector={
                "direction": effective_final_dir,
                "confidence": effective_final_conf,
                "regime": price_based_regime,
                "close": out.get("signal", {}).get("close", 0),
                "atr": out.get("signal", {}).get("atr", 0.02),
            },
            position=None,  # Will be populated if there's an open position
            policy_state=policy if isinstance(policy, dict) else {},
            market_data={
                "regime": price_based_regime,
                "regime_info": regime_info,
                "micro_regime": micro_regime_data.get('micro_regime') if micro_regime_data else None,
                "expansion_event": expansion_event
            },
            loop_state={}
        )

        lane_result = lane_instance.execute_tick(lane_ctx)

        if lane_result.decision == LaneDecision.SKIP:
            print(f"LANE_SKIP: {symbol}_{timeframe} lane={resolved_lane_id} reason={lane_result.reason}")
            # Lane chose to skip - respect this decision
            return {
                "ts": bar_ts or _now(),
                "regime": regime,
                "final": final,
                "policy": policy,
                "pa": {"armed": bool(pa_status.get("armed")), "rmult": float(pa_mult)},
                "risk_adapter": adapter,
                "context": out.get("context", {}),
                "equity_live": position_sizing.read_equity_live(),
                "trading_decision": "lane_skip",
                "lane_skip_reason": lane_result.reason,
                "pnl": 0.0,
            }

        # Lane approved the trade - continue with opening logic
        print(f"LANE_APPROVED: {symbol}_{timeframe} lane={resolved_lane_id} proceeding to trade opening")

    except Exception as e:
        print(f"LANE_ERROR: {symbol}_{timeframe} lane={resolved_lane_id} error={e}")
        # On lane error, skip this symbol
        return {
            "ts": bar_ts or _now(),
            "regime": regime,
            "final": final,
            "policy": policy,
            "pa": {"armed": bool(pa_status.get("armed")), "rmult": float(pa_mult)},
            "risk_adapter": adapter,
            "context": out.get("context", {}),
            "equity_live": position_sizing.read_equity_live(),
            "trading_decision": "lane_error",
            "lane_error": str(e),
            "pnl": 0.0,
        }

    # Step 3: Attempt to open (regime gate and threshold checks passed)
    # Use the modified threshold that accounts for EXPANSION bypass
    final_threshold = threshold_to_use if not expansion_bypass else 0.0  # Allow any confidence for EXPANSION bypass
    can_open = (allow_opens and effective_final_dir != 0 and effective_final_conf >= final_threshold)
    print(f"CAN_OPEN_CHECK: {symbol} can_open={can_open}, allow_opens={allow_opens}, final_dir={effective_final_dir}, final_threshold={final_threshold}, conf={effective_final_conf:.3f}, expansion_bypass={expansion_bypass}")
    opened = False
    if can_open:
        if not (live_pos and live_pos.get("dir") == effective_final_dir):
            opened = _try_open(effective_final_dir, effective_final_conf, now=now, regime=price_based_regime)
            if opened and DEBUG_SIGNALS:
                mode = "PAPER" if IS_PAPER_MODE else "LIVE"
                print(
                    f"ENTRY: mode={mode} dir={effective_final_dir} "
                    f"conf={effective_final_conf:.2f} >= entry_min={effective_min_conf_live:.2f} "
                    f"regime={price_based_regime} risk_band={adapter_band}"
                )

    live_pos = get_live_position()
    # live_exit logic summary:
    # - takes profit when: same_dir AND conf >= take_profit_conf
    # - stops loss when: opposite_dir AND conf >= stop_loss_conf
    # - reverses when: opposite_dir AND conf >= reverse_min_conf (reopens in new direction if allow_opens)
    # - exits on low confidence when: conf < exit_min_conf
    # - decays after N bars when: bars_open >= decay_bars
    if live_pos and live_pos.get("dir"):
        live_pos["bars_open"] = live_pos.get("bars_open", 0) + 1
        live_pos["last_ts"] = bar_ts or _now()
        set_live_position(live_pos)
        set_position(live_pos)
        # Calculate current P&L for exit decisions
        entry_price = live_pos.get("entry_px")
        current_pct = None
        if entry_price and exit_price:
            try:
                entry_val = float(entry_price)
                exit_val = float(exit_price)
                dir_val = int(live_pos.get("dir", 1))
                if entry_val > 0:
                    raw_change = (exit_val - entry_val) / entry_val
                    signed_change = raw_change * dir_val
                    current_pct = signed_change  # Already as decimal (not percentage)
            except (TypeError, ValueError):
                pass

        # Exit conditions based on P&L thresholds (not signal direction)
        # TP: profitable position (pct > profit threshold)
        # SCALP lane uses ATR-based exits, others use percentage-based
        if lane_id == "scalp":
            # SCALP: ATR-based TP/SL
            from engine_alpha.loop.lanes.resolver import get_lane_defaults, get_symbol_class
            symbol_class = get_symbol_class(symbol)
            scalp_defaults = get_lane_defaults("scalp", symbol_class)

            # Get ATR for symbol (simplified - would need actual ATR calculation)
            # For now, use conservative defaults
            atr_pct = 0.005  # Assume 0.5% ATR, would be calculated from actual ATR

            tp_atr_mult = scalp_defaults.get("tp_atr_mult", 0.3)
            sl_atr_mult = scalp_defaults.get("sl_atr_mult", 0.45)

            profit_threshold = tp_atr_mult * atr_pct
            loss_threshold = -sl_atr_mult * atr_pct

            print(f"SCALP_THRESHOLDS: {symbol} ATR~{atr_pct:.3f} TP={profit_threshold:.4f} SL={loss_threshold:.4f}")
        else:
            # Standard percentage-based exits
            profit_threshold = 0.002  # 0.2% profit to take profits
            loss_threshold = -0.001   # -0.1% loss to cut losses

        take_profit = current_pct is not None and current_pct >= profit_threshold
        stop_loss = current_pct is not None and current_pct <= loss_threshold

        if take_profit:
            print(f"TP_CONDITION_MET: {symbol}_{timeframe} pct={current_pct:.4f} >= {profit_threshold:.4f} (profitable exit)")
        if stop_loss:
            print(f"SL_CONDITION_MET: {symbol}_{timeframe} pct={current_pct:.4f} <= {loss_threshold:.4f} (loss exit)")
        # Keep signal-based exits for flip/drop (these are different from TP/SL)
        same_dir = final["dir"] != 0 and final["dir"] == live_pos["dir"]
        opposite_dir = final["dir"] != 0 and final["dir"] != live_pos["dir"]

        flip = (
            final["dir"] != 0
            and final["dir"] != live_pos["dir"]
            and final["conf"] >= gates_reverse_min_conf
        )
        # ---------------------------
        # EXIT-MIN
        # ---------------------------
        drop = (final["conf"] < gates_exit_min_conf)
        # ---------------------------
        # DECAY
        # ---------------------------
        decay = (live_pos["bars_open"] >= decay_bars)
        bars_open = live_pos.get("bars_open", 0)


        # PnL pct calculation summary (for live exits):
        # - take_profit: pct = abs(conf) [positive, uses confidence as proxy]
        # - stop_loss: pct = -abs(conf) [negative, uses confidence as proxy]
        # - flip: pct = conf (same_dir) or -conf (opposite_dir) [uses confidence as proxy]
        # - drop: pct = conf (same_dir) or -conf (opposite_dir) [uses confidence as proxy]
        # - decay: pct = conf (same_dir) or -conf (opposite_dir) [uses confidence as proxy]
        # - uses final["conf"] (confidence score), NOT actual entry_price/exit_price differences
        # - does NOT use entry_price/exit_price directly (this is what we will fix)
        # - entry_px is stored as 1.0 (dummy value), exit_px is never tracked
        close_pct = None
        reopen_after_flip = False
        # Phase 51: Anti-Thrash Guardrails - Ensure min-hold is respected
        # Gate normal exits (TP, SL, reverse, drop) with minimum hold time
        # Decay is handled separately as it has its own gate (bars_open >= decay_bars)
        # Critical exits (hard stop-loss) are allowed before min-hold
        
        # NEW: Time-based min-hold enforcement (seconds since entry)
        # Use entry_ts from position for more precise min-hold than bar-based
        min_hold_seconds = 30  # 30 seconds minimum hold for normal/core positions
        age_seconds = 0
        entry_ts = live_pos.get("entry_ts")
        if entry_ts:
            try:
                entry_time = datetime.fromisoformat(entry_ts.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
                now_time = datetime.now(timezone.utc)
                age_seconds = (now_time - entry_time).total_seconds()
            except Exception:
                age_seconds = 0

        # Check exit hierarchy with safety and opportunity capture
        # 1. SAFETY: Stop losses ALWAYS override (capital protection)
        # 2. EXTREME TP: Rare opportunity capture for CORE
        # 3. MIN-HOLD: Quality control for lane discipline
        # 4. NORMAL EXITS: Allowed after min-hold

        core_min_hold_seconds = 1800  # 30 minutes for CORE
        try:
            from engine_alpha.core.config_loader import load_engine_config
            cfg = load_engine_config()
            core_min_hold_seconds = cfg.get("core_min_hold_seconds", 1800)
        except Exception:
            pass  # Use default

        # Determine effective min-hold based on lane and symbol class
        from engine_alpha.loop.lanes.resolver import get_symbol_class, get_lane_defaults

        symbol_class = get_symbol_class(symbol)
        lane_defaults = get_lane_defaults(lane_id, symbol_class)

        # Use symbol-class-specific min-hold for CORE, defaults for others
        if lane_id == "core":
            effective_min_hold = lane_defaults.get("min_hold_s", core_min_hold_seconds)
        else:
            lane_min_hold_map = {
                "exploration": 15,
                "recovery": 30,
                "quarantine": 0,
                "scalp": 0,  # Scalp allows immediate exits
            }
            effective_min_hold = lane_min_hold_map.get(lane_id, min_hold_seconds)

        # Calculate unrealized P&L for extreme TP check
        unrealized_pnl_pct = 0.0
        if entry_price and exit_price:
            try:
                entry_val = float(entry_price)
                exit_val = float(exit_price)
                dir_val = int(live_pos.get("dir", 1))
                if entry_val > 0:
                    raw_change = (exit_val - entry_val) / entry_val
                    signed_change = raw_change * dir_val
                    unrealized_pnl_pct = signed_change * 100  # Convert to percentage
            except (TypeError, ValueError):
                pass

        # Check extreme TP override for CORE take profits
        extreme_tp_override = False
        if take_profit and lane_id == "core":
            extreme_tp_override = _is_extreme_tp_override(
                lane_id=lane_id,
                unrealized_pnl_pct=unrealized_pnl_pct,
                time_held_seconds=age_seconds,
                regime=price_based_regime,
                volatility_regime=None,  # TODO: Pass actual volatility regime
                regime_info=regime_info
            )

        if extreme_tp_override:
            # EXTREME TP OVERRIDE: Allow immediate exit for exceptional moves
            print(f"EXTREME_TP_OVERRIDE: {symbol}_{timeframe} pnl={unrealized_pnl_pct:.2f}% age_s={age_seconds:.1f} (rare opportunity capture)")
            _record_extreme_tp(symbol, unrealized_pnl_pct, age_seconds)
            # Allow take_profit to proceed, block others
            stop_loss = False
            drop = False
            flip = False
        elif age_seconds < effective_min_hold:
            # SAFETY OVERRIDE: Stop losses ALWAYS fire immediately (capital protection)
            if stop_loss:
                print(f"SAFETY_OVERRIDE: {symbol}_{timeframe} stop_loss firing immediately despite min_hold (capital protection)")
                # Allow stop_loss to proceed
                take_profit = False
                drop = False
                flip = False
            else:
                # LANE RULES: Block non-safety exits until minimum hold
                if take_profit or drop or flip:
                    print(f"CORE_MIN_HOLD_BLOCK: {symbol}_{timeframe} age_s={age_seconds:.1f} < min_s={effective_min_hold} (lane={lane_id}), blocking non-safety exit")
                take_profit = False
                drop = False
                flip = False

        # NEW: For tp/sl/drop/flip exits, require live price - no fallback allowed
        live_price = None
        live_price_meta = None
        if take_profit or stop_loss or drop or flip:
            try:
                from engine_alpha.data.price_feed_health import get_latest_trade_price
                px, meta = get_latest_trade_price(symbol)
                live_price_available = px is not None and px > 0
                live_price = px
                live_price_meta = meta
            except Exception as e:
                live_price_available = False
                print(f"EXIT_SKIP_NO_PRICE: {symbol}_{timeframe} price fetch failed: {e}")

            if not live_price_available:
                print(f"EXIT_SKIP_NO_PRICE: {symbol}_{timeframe} no live price available, skip exit (reason: {'tp' if take_profit else 'sl' if stop_loss else 'drop' if drop else 'reverse'})")
                take_profit = False
                stop_loss = False
                drop = False
                flip = False

        # Apply lane-specific minimum hold time enforcement
        # Prevent micro-churn by requiring minimum position hold times
        position_age_seconds = int((now - entry_ts_dt).total_seconds())

        # Load CORE minimum hold time from config
        core_min_hold_seconds = 900  # Default 15 minutes
        try:
            from engine_alpha.core.config_loader import load_engine_config
            cfg = load_engine_config()
            core_min_hold_seconds = cfg.get("core_min_hold_seconds", 900)
        except Exception:
            pass  # Use default

        # Lane-specific minimum hold times
        lane_min_hold_seconds_map = {
            "core": core_min_hold_seconds,  # Configurable for production trades
            "exploration": 15,              # 15 seconds minimum for exploration
            "recovery": 30,                 # 30 seconds for recovery
            "quarantine": 0,                # No minimum for quarantine
        }
        min_hold_required = lane_min_hold_seconds_map.get(lane_id, 0)

        # Calculate unrealized P&L for extreme TP check
        unrealized_pnl_pct = 0.0
        if pos_info.get("entry_px") and exit_price:
            try:
                entry_val = float(pos_info.get("entry_px"))
                exit_val = float(exit_price)
                dir_val = int(pos_info.get("dir", 1))
                if entry_val > 0:
                    raw_change = (exit_val - entry_val) / entry_val
                    signed_change = raw_change * dir_val
                    unrealized_pnl_pct = signed_change * 100  # Convert to percentage
            except (TypeError, ValueError):
                pass

        # Check extreme TP override for CORE take profits
        extreme_tp_override = False
        if take_profit and lane_id == "core":
            extreme_tp_override = _is_extreme_tp_override(
                lane_id=lane_id,
                unrealized_pnl_pct=unrealized_pnl_pct,
                time_held_seconds=position_age_seconds,
                regime=stored_regime or "unknown"
            )

        if extreme_tp_override:
            # EXTREME TP OVERRIDE: Allow immediate exit for exceptional moves
            print(f"EXTREME_TP_OVERRIDE: {symbol}_{timeframe} pnl={unrealized_pnl_pct:.2f}% age_s={position_age_seconds:.1f} (rare opportunity capture)")
            _record_extreme_tp(symbol, unrealized_pnl_pct, position_age_seconds)
            # Allow take_profit to proceed, block others
            stop_loss = False
            drop = False
            flip = False
        elif position_age_seconds < min_hold_required:
            # SAFETY OVERRIDE: Stop losses ALWAYS fire immediately (capital protection)
            if stop_loss:
                print(f"SAFETY_OVERRIDE: {symbol}_{timeframe} stop_loss firing immediately despite min_hold (capital protection)")
                # Allow stop_loss to proceed
                take_profit = False
                drop = False
                flip = False
            else:
                # LANE RULES: Block non-safety exits until minimum hold
                if take_profit or drop or flip:
                    print(f"EXIT_BLOCK_MIN_HOLD: {symbol}_{timeframe} age={position_age_seconds}s < min={min_hold_required}s (lane={lane_id}), blocking non-safety exit")
                take_profit = False
                drop = False
                flip = False

        # Evaluate exits - P&L-based exits (TP/SL) can fire anytime after min-hold, signal-based need min-hold
        exit_fired = False
        if take_profit:
            exit_fired = True
            print(f"EXIT-DEBUG: TP hit pct={current_pct:.4f} >= {profit_threshold:.4f} (P&L-based exit)")
        elif stop_loss:
            exit_fired = True
            print(f"EXIT-DEBUG: SL hit pct={current_pct:.4f} <= {loss_threshold:.4f} (P&L-based exit)")
        elif bars_open >= MIN_HOLD_BARS_LIVE:
            if drop or flip:
                exit_fired = True
                if drop:
                    if DEBUG_SIGNALS:
                        print(f"EXIT-DEBUG: EXIT-MIN hit conf={final['conf']:.4f} < exit_min_conf={gates_exit_min_conf:.4f}")
                elif flip:
                    print(f"EXIT-DEBUG: REVERSE hit dir={final['dir']} conf={final['conf']:.4f} >= reverse_min_conf={gates_reverse_min_conf:.4f}")
                    reopen_after_flip = flip and policy.get("allow_opens", True)
        
        # Decay exit is independent and only requires bars_open >= decay_bars
        if decay:
            exit_fired = True

        if exit_fired:
            # Determine exit_reason based on which condition triggered the exit
            exit_reason = "unknown"
            if decay:
                exit_reason = "decay"
            elif take_profit:
                exit_reason = "tp"
            elif stop_loss:
                exit_reason = "sl"
            elif flip:
                exit_reason = "reverse"
            elif drop:
                exit_reason = "drop"
            
            # Phase 51: Anti-Thrash Guardrails - Track bad exits for cluster guard
            if exit_reason in ("sl", "drop"):
                _LAST_BAR_STATE["recent_bad_exits"].append(now_dt)
                # Keep only recent exits (already pruned at start of function, but ensure we don't grow unbounded)
                _LAST_BAR_STATE["recent_bad_exits"] = [
                    exit_ts for exit_ts in _LAST_BAR_STATE["recent_bad_exits"]
                    if (now_dt - exit_ts).total_seconds() <= _BAD_EXIT_WINDOW_SECONDS
                ]
            
            # Get prices for price-based PnL calculation
            entry_price = live_pos.get("entry_px")
            exit_price = None
            exit_px_source = None
            pos_dir = live_pos.get("dir")

            # Get live trade price as exit_price (same as timeout closes use)
            try:
                from engine_alpha.data.price_feed_health import get_latest_trade_price
                px, meta = get_latest_trade_price(symbol)
                if px is not None and px > 0:
                    exit_price = float(px)
                    exit_px_source = meta.get("source_used") or meta.get("source") or "price_feed_health"
                else:
                    exit_px_source = "price_feed_health:unavailable"
            except Exception as e:
                exit_px_source = f"price_feed_health:exception:{str(e)}"
            
            # Debug logging for price extraction
            if os.getenv("DEBUG_SIGNALS") == "1":
                print(f"EXIT-PRICE-DEBUG: entry_price={entry_price}, exit_price={exit_price}, pos_dir={pos_dir}")
                if ohlcv_rows and len(ohlcv_rows) > 0:
                    print(f"EXIT-PRICE-DEBUG: latest_candle keys={list(ohlcv_rows[-1].keys())}")
            
            # Compute price-based pct
            price_based_pct = None
            if entry_price is not None and exit_price is not None and pos_dir is not None:
                try:
                    entry_val = float(entry_price)
                    exit_val = float(exit_price)
                    dir_val = int(pos_dir)
                    if entry_val > 0:
                        raw_change = (exit_val - entry_val) / entry_val
                        signed_change = raw_change * dir_val  # dir = +1 for LONG, -1 for SHORT
                        price_based_pct = signed_change * 100.0
                except (TypeError, ValueError):
                    pass
            
            # Use price-based pct if available, otherwise fallback to 0.0
            if price_based_pct is None:
                if entry_price is None or exit_price is None:
                    print("PNL-DEBUG: missing entry_price/exit_price, pct=0.0 fallback")
                    final_pct = 0.0
                else:
                    # Entry/exit prices exist but calculation failed - fallback to 0.0
                    final_pct = 0.0
            else:
                final_pct = price_based_pct
            
            # Get exit_conf (final_conf at exit time)
            exit_conf = final.get("conf")
            
            equity_before = position_sizing.read_equity_live()
            cap_adj = float(sizing_cfg.get("cap_adj_pct", 0.0) or 0.0)
            adj_pct = position_sizing.cap_pct(float(final_pct), cap_adj)
            fees_bps = float(sizing_cfg.get("fees_bps_default", 0.0))
            slip_bps = float(sizing_cfg.get("slip_bps_default", 0.0))
            pct_net = adj_pct - ((fees_bps + slip_bps) / 10000.0)
            fraction = float(position_sizing.risk_fraction(sizing_cfg))
            r_value = pct_net * fraction
            equity_live_value = max(0.0, float(equity_before) * (1.0 + r_value))
            
            # Call close_now with live price and regime for proper P&L calculation
            # Use live_price if available (from above), otherwise fallback to calculated exit_price
            actual_exit_price = live_price if 'live_price' in locals() and live_price is not None else exit_price
            actual_exit_px_source = live_price_meta.get("source_used") if 'live_price_meta' in locals() and live_price_meta else exit_px_source

            # Prefer stored regime from position, then current regime, then unknown
            stored_regime = live_pos.get("regime") or live_pos.get("regime_at_entry")
            exit_regime = stored_regime or regime or "unknown"

            # DEBUG: Log position regime data for debugging
            print(f"REGIME_DEBUG_CLOSE: {symbol}_{timeframe} live_pos_regime={live_pos.get('regime')} live_pos_regime_at_entry={live_pos.get('regime_at_entry')} current_regime={regime} exit_regime={exit_regime}")

            # Regression check: warn if we're closing with unknown regime but position had stored regime
            if exit_regime == "unknown" and (live_pos.get("regime") or live_pos.get("regime_at_entry")):
                print(f"REGIME_REGRESSION_WARNING: {symbol}_{timeframe} close with unknown regime but position had stored regime")

            # Ensure regime is passed to close event
            close_now(
                symbol=symbol,
                timeframe=timeframe,
                exit_reason=exit_reason,
                exit_price=(actual_exit_price, {"source_used": actual_exit_px_source}) if actual_exit_price else None,
                regime=exit_regime,
                position_data=live_pos,
                lane_id=lane_id
            )
            
            # Log council perf event for close
            _log_council_event({
                "event": "close",
                "ts": bar_ts or _now(),
                "regime": regime,
                "final_dir": int(final_dir),
                "final_conf": float(final_conf),
                "risk_band": adapter_band,
                "risk_mult": float(rmult),
                "pct": float(final_pct),
                "buckets": bucket_debug,
            })
            
            if allow_live_writes:
                position_sizing.write_equity_live(equity_live_value)
                _append_equity_live_record(bar_ts or _now(), equity_live_value, adj_pct, pct_net, r_value)
            try:
                pf_weighted.update(source="live")
            except Exception:
                pass
            clear_live_position()
            clear_position()
            if reopen_after_flip:
                _try_open(final["dir"], final["conf"], regime=regime)

    # Log council event for every bar (decision point) - not just opens/closes
    # This ensures reflection can analyze all decision points, not just trade events
    _log_council_event({
        "event": "bar",
        "ts": bar_ts or _now(),
        "regime": regime,
        "final_dir": int(final_dir),
        "final_conf": float(final_conf),
        "risk_band": adapter_band,
        "risk_mult": float(rmult),
        "buckets": bucket_debug,
    })

    update_pf_reports(
        TRADES_PATH,
        REPORTS / "pf_local.json",
        REPORTS / "pf_live.json",
    )

    equity_live_out = position_sizing.read_equity_live()
    
    # META-INTELLIGENCE: Detect Fair Value Gaps (Observer-only)
    # This identifies structural price dislocations for meta-analysis
    fvg_context = None
    try:
        # get_live_ohlcv is already imported at module level (line 32)
        ohlcv_result = get_live_ohlcv(symbol, timeframe)
        print(f"FVG_DEBUG: got OHLCV result type {type(ohlcv_result)}")
        if isinstance(ohlcv_result, tuple) and len(ohlcv_result) >= 1:
            candles_list = ohlcv_result[0]
            print(f"FVG_DEBUG: got {len(candles_list)} candles for {symbol}")
            if candles_list and len(candles_list) > 0:
                detected_gaps = detect_and_log_fvgs(
                    symbol=symbol,
                    candles=candles_list[-50:],  # Last 50 candles
                    current_regime=price_based_regime,
                    timeframe=timeframe
                )
                print(f"FVG_DEBUG: detected {len(detected_gaps)} gaps for {symbol}")
                if detected_gaps:
                    print(f"FVG_DEBUG: gap details - {detected_gaps[0].direction} {detected_gaps[0].gap_size_pct:.2f}%")

                # Build FVG context for meta-analysis
                from engine_alpha.reflect.fair_value_gaps import fvg_detector
                fvg_context = {
                    "detected_gaps": len(detected_gaps),
                    "recent_gaps": [gap._asdict() for gap in detected_gaps[-3:]],  # Last 3 gaps
                    "fvg_statistics": fvg_detector.get_fvg_statistics(symbol, days_back=7)
                }

    except Exception as e:
        # FVG detection failure shouldn't stop trading
        print(f"FVG_DETECTION_ERROR: {e}")

    # Record comprehensive meta-intelligence decision
    record_trading_decision(
        symbol=symbol,
        direction=final["dir"],
        confidence=final["conf"],
        regime=price_based_regime,
        entry_price=None,
        market_state={"regime": price_based_regime, "adapter_band": adapter_band},
        decision_type="entry_attempt",
        regime_uncertainty=None,  # TODO: Add regime uncertainty
        edge_strength=None,       # TODO: Add edge strength
        fvg_context=fvg_context
    )

    # Extract PnL from close event (only non-zero when a close happened)
    # final_pct is computed in the exit logic above if a close occurred
    pnl = 0.0
    # Update opportunity density tracking
    try:
        # Determine if this represents a trading opportunity
        # Opportunity exists when we have a clear directional signal with reasonable confidence
        is_opportunity = (
            final_dir != 0 and  # Clear direction
            final_conf >= 0.3 and  # Reasonable confidence threshold
            regime != "unknown"  # Valid regime classification
        )

        # Update opportunity state
        opp_state = load_state()
        current_ts = _now()
        opp_state, opp_metrics = update_opportunity_state(
            opp_state,
            current_ts,
            regime,
            is_eligible=is_opportunity,
            alpha=0.05
        )
        save_state(opp_state)

        # Log opportunity event for snapshot analysis
        from engine_alpha.core.atomic_io import atomic_append_jsonl
        opportunity_event = {
            "ts": current_ts,
            "symbol": symbol,
            "timeframe": timeframe,
            "regime": regime,
            "final_dir": final_dir,
            "final_conf": final_conf,
            "eligible": is_opportunity,
            "eligible_reason": "signal_ready" if is_opportunity else "low_confidence",
            "density_current": opp_metrics.get("density_current", 0.0),
        }
        atomic_append_jsonl(REPORTS / "opportunity_events.jsonl", opportunity_event)

    except Exception as e:
        # Opportunity tracking failure shouldn't stop trading
        print(f"OPPORTUNITY_UPDATE_ERROR: {e}")

    try:
        if 'final_pct' in locals() and final_pct is not None:
            # Convert pct (percentage) to decimal for equity calculation
            # final_pct is already in percentage form (0.0-100.0), convert to decimal (0.0-1.0)
            pnl = float(final_pct) / 100.0
    except (NameError, TypeError, ValueError):
        pass

    return {
        "ts": bar_ts or _now(),
        "regime": regime,
        "final": final,
        "policy": policy,
        "pa": {"armed": bool(pa_status.get("armed")), "rmult": float(pa_mult)},
        "risk_adapter": adapter,
        "context": out.get("context", {}),
        "equity_live": equity_live_out,
        "pnl": pnl,  # PnL as decimal (e.g., 0.05 for +5% move)
    }

def run_batch(n: int = 25):
    info = None
    sizing_cfg = position_sizing.cfg()
    start_line = 0
    normalize_enabled = bool(sizing_cfg.get("normalize_batch", False))
    if normalize_enabled:
        start_line = _count_lines(TRADES_PATH)
    for _ in range(n):
        info = run_step()
    if normalize_enabled:
        try:
            _build_normalized_batch_curve(sizing_cfg, start_index=start_line)
        except Exception:
            pass
    (REPORTS / "loop_health.json").write_text(json.dumps({
        "ts": _now(),
        "last": info
    }, indent=2))
    return info

def run_exit_evaluation_for_all_positions():
    """
    Evaluate exits for ALL open positions regardless of symbol/timeframe.
    This ensures positions on different symbols/timeframes get proper exit evaluation.
    """
    try:
        # Load all positions
        position_state_path = REPORTS / "position_state.json"
        if not position_state_path.exists():
            return

        with position_state_path.open("r", encoding="utf-8") as f:
            position_data = json.load(f)

        positions = position_data.get("positions", {})
        if not positions:
            return

        # For each position, run exit evaluation using its symbol/timeframe
        for pos_key, pos_info in positions.items():
            if not pos_info or not pos_info.get("dir"):
                continue

            # Extract symbol and timeframe from position key (format: SYMBOL_TIMEFRAME)
            if "_" not in pos_key:
                continue
            parts = pos_key.split("_", 1)
            if len(parts) != 2:
                continue
            symbol, timeframe = parts

            try:
                # Run exit evaluation for this specific position
                # This will check if the position should be closed and execute the close if needed
                _evaluate_single_position_exit(symbol, timeframe, pos_info)
            except Exception as e:
                print(f"EXIT_EVAL_ERROR for {pos_key}: {e}")
                import traceback
                traceback.print_exc()

    except Exception as e:
        print(f"EXIT_EVALUATION_ALL_POSITIONS_ERROR: {e}")


def _evaluate_single_position_exit(symbol: str, timeframe: str, pos_info: dict, lane_id: str = "unknown"):
    """
    Evaluate exit conditions for a single position.
    This replicates the exit logic from run_step_live but for a specific position.
    """
    # Get current decision for this symbol/timeframe
    out = get_signal_vector_live(symbol=symbol, timeframe=timeframe, limit=200)
    decision = decide(out["signal_vector"], out["raw_registry"])
    final = decision["final"]
    regime = decision["regime"]

    # Load exit config and policy
    exit_cfg = _load_exit_config()
    decay_bars = exit_cfg["DECAY_BARS"]
    take_profit_conf = exit_cfg["TAKE_PROFIT_CONF"]
    stop_loss_conf = exit_cfg["STOP_LOSS_CONF"]
    gates = decision.get("gates", {})
    gates_exit_min_conf = gates.get("exit_min_conf", 0.30)
    gates_reverse_min_conf = gates.get("reverse_min_conf", 0.60)

    policy = _load_policy()

    # Resolve execution lane using canonical logic
    from engine_alpha.risk.symbol_state import load_symbol_states
    symbol_states = load_symbol_states()
    sym_policy_map = symbol_states.get("symbols", {}) if isinstance(symbol_states, dict) else {}
    symbol_policy = sym_policy_map.get(symbol, {}) if isinstance(sym_policy_map, dict) else {}
    # Pass regime information for proper lane resolution (especially important for SCALP)
    lane_context = {"regime": regime}
    lane_id = resolve_lane(symbol, symbol_policy, lane_context)

    # Check exit conditions with P&L-based logic and time-based min-hold
    bars_open = pos_info.get("bars_open", 0)

    # Fetch live price for P&L calculations (only when needed for exits)
    live_price = None
    live_price_meta = None
    try:
        from engine_alpha.data.price_feed_health import get_latest_trade_price
        px, meta = get_latest_trade_price(symbol)
        if px is not None and px > 0:
            live_price = px
            live_price_meta = meta
    except Exception as e:
        print(f"EXIT_EVAL_PRICE_FETCH_FAILED: {symbol}_{timeframe} - {e}")

    # Calculate current P&L for exit decisions
    entry_price = pos_info.get("entry_px")
    current_pct = None
    if entry_price and live_price:
        try:
            entry_val = float(entry_price)
            exit_val = float(live_price)
            dir_val = int(pos_info.get("dir", 1))
            if entry_val > 0:
                raw_change = (exit_val - entry_val) / entry_val
                signed_change = raw_change * dir_val
                current_pct = signed_change  # As decimal
        except (TypeError, ValueError):
            pass

    # Exit conditions based on P&L thresholds (not signal direction)
    profit_threshold = 0.002  # 0.2% profit to take profits
    loss_threshold = -0.001   # -0.1% loss to cut losses

    take_profit = current_pct is not None and current_pct >= profit_threshold
    stop_loss = current_pct is not None and current_pct <= loss_threshold

    # Keep signal-based exits for flip/drop
    same_dir = final["dir"] != 0 and final["dir"] == pos_info["dir"]
    opposite_dir = final["dir"] != 0 and final["dir"] != pos_info["dir"]

    flip = (
        final["dir"] != 0
        and final["dir"] != pos_info["dir"]
        and final["conf"] >= gates_reverse_min_conf
    )
    drop = (final["conf"] < gates_exit_min_conf)
    decay = (bars_open >= decay_bars)

    # NEW: Time-based min-hold enforcement (seconds since entry)
    min_hold_seconds = 30  # 30 seconds minimum hold for normal/core positions
    age_seconds = 0
    entry_ts = pos_info.get("entry_ts")
    if entry_ts:
        try:
            entry_time = datetime.fromisoformat(entry_ts.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
            now_time = datetime.now(timezone.utc)
            age_seconds = (now_time - entry_time).total_seconds()
        except Exception:
            age_seconds = 0

    # Check time-based min-hold guard
    # P&L-based exits (TP, SL) can fire anytime when thresholds are hit
    # Only signal-based exits (drop, flip) need min-hold to prevent thrashing
    if age_seconds < min_hold_seconds:
        # P&L-based exits (TP, SL) can fire immediately when thresholds are hit
        # Only signal-based exits (drop, flip) must wait for min-hold
        if drop or flip:
            print(f"EXIT_SKIP_MIN_HOLD: {symbol}_{timeframe} age_s={age_seconds:.1f} < min_s={min_hold_seconds}, skip exit (reason: {'drop' if drop else 'reverse'})")
            drop = False
            flip = False
        # TP and SL are allowed (based on actual P&L, not signal timing)

    # NEW: For tp/sl/drop/flip exits, require live price - no fallback allowed
    live_price = None
    live_price_meta = None
    if take_profit or stop_loss or drop or flip:
        try:
            from engine_alpha.data.price_feed_health import get_latest_trade_price
            px, meta = get_latest_trade_price(symbol)
            live_price_available = px is not None and px > 0
            live_price = px
            live_price_meta = meta
        except Exception as e:
            live_price_available = False
            print(f"EXIT_SKIP_NO_PRICE: {symbol}_{timeframe} price fetch failed: {e}")

        if not live_price_available:
            print(f"EXIT_SKIP_NO_PRICE: {symbol}_{timeframe} no live price available, skip exit (reason: {'tp' if take_profit else 'sl' if stop_loss else 'drop' if drop else 'reverse'})")
            take_profit = False
            stop_loss = False
            drop = False
            flip = False

    # Determine if exit should fire
    exit_fired = take_profit or stop_loss or flip or drop or decay

    if exit_fired:
        # Determine exit reason
        exit_reason = "unknown"
        if decay:
            exit_reason = "decay"
        elif take_profit:
            exit_reason = "tp"
        elif stop_loss:
            exit_reason = "sl"
        elif flip:
            exit_reason = "reverse"
        elif drop:
            exit_reason = "drop"

        print(f"EXIT_CHECK: {symbol}_{timeframe} bars_open={bars_open} age_s={age_seconds:.1f} reason={exit_reason} conf={final['conf']:.2f}")

        # Execute the close with live price and stored regime
        stored_regime = pos_info.get("regime") or pos_info.get("regime_at_entry")


        # Track extreme TP override in trade metadata
        trade_metadata = {}
        if exit_reason == "tp" and lane_id == "core" and extreme_tp_override:
            trade_metadata.update({
                "exit_reason": "tp_override_extreme",
                "override_trigger": f"pnl_{unrealized_pnl_pct:.2f}%_time_{position_age_seconds}s",
                "time_held_s": position_age_seconds,
                "blocked_by_min_hold": False
            })

        # Ensure regime and lane are passed to close event
        close_now(
            symbol=symbol,
            timeframe=timeframe,
            exit_reason=trade_metadata.get("exit_reason", exit_reason),
            exit_price=(live_price, {"source_used": live_price_meta.get("source_used")}) if live_price else None,
            regime=stored_regime or "unknown",
            position_data=pos_info,
            lane_id=lane_id,
            **trade_metadata
        )

        # Phase 5J-R: Set chop exploration cooldown on qualifying exits
        trade_kind = pos_info.get("trade_kind", "normal")
        # For exploration lane trades, assume chop regime if stored regime is missing
        # (since exploration is typically used in chop when core is blocked)
        effective_regime = stored_regime or ("chop" if lane_id == "exploration" else None)
        if effective_regime == "chop" and lane_id == "exploration":
            # Reset cooldown on SL, micro-signal exits, or timeouts
            cooldown_reasons = {"sl", "drop", "decay", "timeout_max_hold", "review_bootstrap_timeout"}
            if exit_reason in cooldown_reasons:
                cooldown_until_dt = datetime.now(timezone.utc) + timedelta(minutes=CHOP_EXPLORATION_COOLDOWN_MINUTES)
                cooldown_until_iso = cooldown_until_dt.isoformat().replace("+00:00", "Z")
                _CHOP_EXPLORATION_COOLDOWN[symbol] = cooldown_until_iso
                _save_chop_cooldowns(_CHOP_EXPLORATION_COOLDOWN)
                print(f"CHOP_EXPLORATION_COOLDOWN_SET: {symbol} for {CHOP_EXPLORATION_COOLDOWN_MINUTES}min (reason: {exit_reason})")

        # Set CORE cooldown after closing a CORE position
        if lane_id == "core":
            try:
                from engine_alpha.core.config_loader import load_engine_config
                cfg = load_engine_config()
                core_cooldown_seconds = cfg.get("core_cooldown_seconds", 900)  # Default 15 minutes
                cooldown_until_dt = datetime.now(timezone.utc) + timedelta(seconds=core_cooldown_seconds)
                cooldown_until_iso = cooldown_until_dt.isoformat().replace("+00:00", "Z")
                _CORE_COOLDOWN[symbol] = cooldown_until_iso
                _save_core_cooldowns(_CORE_COOLDOWN)
                print(f"CORE_COOLDOWN_SET: {symbol} for {core_cooldown_seconds}s (reason: core_close)")
            except Exception as e:
                print(f"CORE_COOLDOWN_SET_ERROR: {symbol} {e}")

        # Clear the position
        clear_position()

        print(f"CLOSE-LOG EXECUTED: {symbol}_{timeframe} reason={exit_reason} live_px={live_price}")


def run_step_live_scheduled():
    """Scheduled version of run_step_live for continuous loop with multi-symbol support."""
    from engine_alpha.core.config_loader import load_engine_config
    from engine_alpha.risk.symbol_state import load_symbol_states

    cfg = load_engine_config()
    configured_symbol = cfg.get('symbol', 'ETHUSDT')
    timeframe = cfg.get('timeframe', '15m')

    # Load all symbol states to determine which symbols to process
    symbol_states = load_symbol_states()
    active_symbols = []

    if isinstance(symbol_states, dict) and 'symbols' in symbol_states:
        for symbol, state in symbol_states['symbols'].items():
            # Include symbols that are not explicitly disabled
            # This includes quarantined symbols that can go to recovery
            if not state.get('disabled', False):
                active_symbols.append(symbol)

    # If no symbols found, fall back to configured symbol
    if not active_symbols:
        active_symbols = [configured_symbol]

    print(f"MULTI_SYMBOL_PROCESSING: Processing {len(active_symbols)} symbols: {active_symbols[:5]}{'...' if len(active_symbols) > 5 else ''}")

    # Process each active symbol
    for symbol in active_symbols:
        try:
            print(f"PROCESSING_SYMBOL: {symbol}")
            # TEMPORARY: Lower entry threshold for chop regime testing
            run_step_live(symbol=symbol, timeframe=timeframe, entry_min_conf=0.30)
        except Exception as e:
            print(f"ERROR_PROCESSING_SYMBOL: {symbol} - {e}")
            # Continue processing other symbols even if one fails

