from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List

import yaml

from engine_alpha.signals.signal_processor import get_signal_vector, get_signal_vector_live
from engine_alpha.core.confidence_engine import decide, COUNCIL_WEIGHTS, apply_bucket_mask, REGIME_BUCKET_MASK
from engine_alpha.core.paths import REPORTS, CONFIG
from engine_alpha.data.live_prices import get_live_ohlcv
from engine_alpha.core.regime import classify_regime
from engine_alpha.core.profit_amplifier import evaluate as pa_evaluate, risk_multiplier as pa_rmult
from engine_alpha.core.risk_adapter import evaluate as risk_eval
from engine_alpha.loop.execute_trade import open_if_allowed, close_now
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

# -----------------------------------------------------------------------------
# Entry threshold config (per-regime floors, tuned via tools/threshold_tuner.py)
# -----------------------------------------------------------------------------

ENTRY_THRESHOLDS_DEFAULT: dict[str, float] = {
    "trend_down": 0.50,
    "high_vol": 0.55,
    "trend_up": 0.60,
    "chop": 0.65,
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

_LAST_BAR_STATE = {
    "bar_ts": None,
    "opened_this_bar": False,
    "last_open_ts": None,
    "recent_bad_exits": [],  # List of datetime objects for SL/drop exits
}


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
    
    # Live/PAPER behavior
    return regime in ("trend_down", "high_vol")


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
    exit_cfg = _load_exit_config()
    decay_bars = exit_cfg["DECAY_BARS"]
    take_profit_conf = exit_cfg["TAKE_PROFIT_CONF"]
    stop_loss_conf = exit_cfg["STOP_LOSS_CONF"]

    policy = _load_policy()

    out = get_signal_vector()
    decision = decide(out["signal_vector"], out["raw_registry"])
    final = decision["final"]
    regime = decision["regime"]
    
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
    rmult = max(0.5, min(1.25, float(pa_mult) * adapter_mult))

    # PAPER + band C override: slightly softer entry threshold for learning
    effective_entry_min_conf = regime_entry_min_conf
    is_paper_mode = True  # run_step() is PAPER mode
    if is_paper_mode and adapter_band == "C":
        effective_entry_min_conf = max(0.0, regime_entry_min_conf - 0.03)
        print(f"ENTRY-DEBUG: PAPER band=C using softened entry_min_conf={effective_entry_min_conf:.2f} (final_conf={final['conf']:.2f})")

    opened = False
    if policy.get("allow_opens", True):
        opened = open_if_allowed(final_dir=final["dir"],
                                 final_conf=final["conf"],
                                 entry_min_conf=effective_entry_min_conf,
                                 risk_mult=rmult,
                                 regime=regime,  # Pass regime for observability
                                 risk_band=adapter_band,  # Pass risk_band for observability
                                 symbol=symbol,
                                 timeframe=timeframe)
        if opened:
            _annotate_last_open(float(pa_mult), adapter, rmult)

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
            close_now(pct=close_pct)
            clear_position()
            if flip and policy.get("allow_opens", True):
                if open_if_allowed(
                    final_dir=final["dir"],
                    final_conf=final["conf"],
                    entry_min_conf=effective_entry_min_conf,
                    risk_mult=rmult,
                    regime=regime,  # Pass regime for observability
                    risk_band=adapter_band,  # Pass risk_band for observability
                    symbol=symbol,
                    timeframe=timeframe,
                ):
                    _annotate_last_open(float(pa_mult), adapter, rmult)

    update_pf_reports(TRADES_PATH,
                      REPORTS / "pf_local.json",
                      REPORTS / "pf_live.json")

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
        entry_min_conf: Minimum confidence for entry (legacy, now computed internally)
        exit_min_conf: Minimum confidence for exit
        reverse_min_conf: Minimum confidence for reversal
        bar_ts: Bar timestamp string (for logging)
        now: Current time as datetime (for cooldown/guardrails). If None, uses datetime.utcnow()
    """
    # Phase 51: Anti-Thrash Guardrails - Reset per-bar state
    global _LAST_BAR_STATE
    
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
    
    # Extract volatility metrics for Phase 54
    atr_pct = regime_metrics.get("atr_pct", 0.0)
    vol_expansion = regime_metrics.get("vol_expansion", 1.0)
    slope = regime_metrics.get("slope", 0.0)
    
    # Phase: Stabilization - Unified regime classification (no special modes)
    # Regime is determined purely from price data, same for all modes

    out = get_signal_vector_live(symbol=symbol, timeframe=timeframe, limit=limit)
    # Pass price-based regime to decide() so council aggregation uses correct regime
    decision = decide(out["signal_vector"], out["raw_registry"], regime_override=price_based_regime)
    final = decision["final"]
    # Use price-based regime (already passed to decide(), but keep for consistency)
    regime = price_based_regime
    
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
            bucket_weight_adj["meanrev"] = 1.10
            bucket_weight_adj["flow"] = 0.90
        
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
    
    # Apply neutral zone logic: if final_score magnitude is below threshold, set dir=0
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
            f"final_score={final_score:.4f} final_dir={effective_final_dir} final_conf={effective_final_conf:.2f}"
        )
        if effective_final_dir == 0:
            print(f"SIGNAL-DEBUG: neutralized final_score={final_score:.4f} < NEUTRAL_THRESHOLD={NEUTRAL_THRESHOLD:.2f}")
    
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
        print(f"EXIT-THRESHOLDS: regime={regime} tp_conf={take_profit_conf:.2f} sl_conf={stop_loss_conf:.2f}")
    adapter["mult"] = adapter_mult
    adapter["band"] = adapter_band
    rmult = max(0.5, min(1.25, float(pa_mult) * adapter_mult))
    
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
            timeframe=timeframe
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
    if allow_opens and effective_final_dir != 0 and effective_final_conf < effective_min_conf_live:
        if DEBUG_SIGNALS:
            print(f"ENTRY-THRESHOLD: skip trade dir={effective_final_dir} conf={effective_final_conf:.2f} < entry_min={effective_min_conf_live:.2f}")
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
    
    # Step 3: Attempt to open (regime gate and threshold checks passed)
    can_open = (allow_opens and effective_final_dir != 0 and effective_final_conf >= effective_min_conf_live)
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
        same_dir = final["dir"] != 0 and final["dir"] == live_pos["dir"]
        opposite_dir = final["dir"] != 0 and final["dir"] != live_pos["dir"]
        take_profit = same_dir and final["conf"] >= take_profit_conf
        stop_loss = opposite_dir and final["conf"] >= stop_loss_conf
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
        
        # Check min-hold guard
        # Allow TP to bypass min-hold if confidence is very high (>= 0.70) - captures strong moves early
        # This increases TP exits and reduces drop/decay exits by allowing early TP captures
        high_conf_tp = take_profit and final["conf"] >= 0.70
        if bars_open < MIN_HOLD_BARS_LIVE:
            # Critical exits (stop_loss) and high-confidence TP (>= 0.70) can fire immediately
            # Non-critical exits (drop, reverse, low-conf take_profit) must wait for min-hold
            if take_profit and not high_conf_tp:
                # Low-confidence TP must wait for min-hold
                if DEBUG_SIGNALS:
                    print(f"LIVE-GUARD: min-hold active (bars_open={bars_open} < MIN_HOLD_BARS_LIVE={MIN_HOLD_BARS_LIVE}), skip TP (conf={final['conf']:.2f} < 0.70)")
                take_profit = False
            elif drop or flip:
                if DEBUG_SIGNALS:
                    print(f"LIVE-GUARD: min-hold active (bars_open={bars_open} < MIN_HOLD_BARS_LIVE={MIN_HOLD_BARS_LIVE}), skip non-critical exit (reason: {'drop' if drop else 'reverse'})")
                # Reset exit flags for non-critical exits
                drop = False
                flip = False
            # stop_loss and high_conf_tp are allowed (critical/high-confidence exits) - handle below
        
        # Evaluate exits - determine which exit reason fired
        # We'll compute price-based P&L below, not confidence-based
        exit_fired = False
        if stop_loss:
            exit_fired = True
        elif take_profit:
            # TP can fire if: (1) min-hold met OR (2) high confidence (>= 0.70) bypasses min-hold
            if bars_open >= MIN_HOLD_BARS_LIVE or high_conf_tp:
                exit_fired = True
                if high_conf_tp and bars_open < MIN_HOLD_BARS_LIVE:
                    print(f"EXIT-DEBUG: TP hit (high-conf bypass) conf={final['conf']:.4f} >= 0.70, bars_open={bars_open}")
                else:
                    print(f"EXIT-DEBUG: TP hit conf={final['conf']:.4f} >= take_profit_conf={take_profit_conf:.4f}")
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
            pos_dir = live_pos.get("dir")
            
            # Get latest bar's close price as exit_price
            # This works for both live (real API) and backtest (mocked OHLCV)
            ohlcv_rows = get_live_ohlcv(symbol=symbol, timeframe=timeframe, limit=1)
            if ohlcv_rows and len(ohlcv_rows) > 0:
                latest_candle = ohlcv_rows[-1]
                exit_price = latest_candle.get("close")
                # Try alternative field names if "close" is missing
                if exit_price is None:
                    exit_price = latest_candle.get("c") or latest_candle.get("close_price")
            
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
            
            # Call close_now with extended fields for reflection analysis
            close_now(
                pct=final_pct,
                entry_price=entry_price,
                exit_price=exit_price,
                dir=pos_dir,
                exit_reason=exit_reason,
                exit_conf=exit_conf,
                regime=regime,
                risk_band=adapter_band,
                risk_mult=rmult,
                max_adverse_pct=None,  # TODO: compute max adverse excursion if bar-level prices available
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
    
    # Extract PnL from close event (only non-zero when a close happened)
    # final_pct is computed in the exit logic above if a close occurred
    pnl = 0.0
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
