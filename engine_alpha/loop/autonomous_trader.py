from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Dict, Any, List

import yaml

from engine_alpha.signals.signal_processor import get_signal_vector, get_signal_vector_live
from engine_alpha.core.confidence_engine import decide
from engine_alpha.core.paths import REPORTS, CONFIG
from engine_alpha.data.live_prices import get_live_ohlcv
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

MIN_CONF_LIVE_DEFAULT = 0.55
MIN_CONF_LIVE = float(os.getenv("MIN_CONF_LIVE", MIN_CONF_LIVE_DEFAULT))

MIN_HOLD_BARS_LIVE_DEFAULT = 2
MIN_HOLD_BARS_LIVE = int(os.getenv("MIN_HOLD_BARS_LIVE", MIN_HOLD_BARS_LIVE_DEFAULT))


def _count_lines(path: Path) -> int:
    try:
        with path.open("r") as handle:
            return sum(1 for _ in handle)
    except Exception:
        return 0


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
        data = json.loads(ORCH_SNAPSHOT.read_text())
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
    take_profit_conf = float(max(0.0, _get_number("TAKE_PROFIT_CONF", 0.28)))
    stop_loss_conf = float(max(0.0, _get_number("STOP_LOSS_CONF", 0.12)))

    return {
        "DECAY_BARS": decay_bars,
        "TAKE_PROFIT_CONF": take_profit_conf,
        "STOP_LOSS_CONF": stop_loss_conf,
    }


def run_step(entry_min_conf: float = 0.66, exit_min_conf: float = 0.32, reverse_min_conf: float = 0.55):
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

    opened = False
    if policy.get("allow_opens", True):
        opened = open_if_allowed(final_dir=final["dir"],
                                 final_conf=final["conf"],
                                 entry_min_conf=regime_entry_min_conf,
                                 risk_mult=rmult)
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
            close_pct = abs(float(final.get("conf", 0.0)))
        elif stop_loss:
            close_pct = -abs(float(final.get("conf", 0.0)))
        elif drop or flip or decay:
            close_pct = float(final.get("conf", 0.0)) if same_dir else -float(final.get("conf", 0.0))

        if close_pct is not None:
            close_now(pct=close_pct)
            clear_position()
            if flip and policy.get("allow_opens", True):
                if open_if_allowed(
                    final_dir=final["dir"],
                    final_conf=final["conf"],
                    entry_min_conf=regime_entry_min_conf,
                    risk_mult=rmult,
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
                  entry_min_conf: float = 0.66,
                  exit_min_conf: float = 0.32,
                  reverse_min_conf: float = 0.55,
                  bar_ts: str | None = None):
    exit_cfg = _load_exit_config()
    decay_bars = exit_cfg["DECAY_BARS"]
    take_profit_conf = exit_cfg["TAKE_PROFIT_CONF"]
    stop_loss_conf = exit_cfg["STOP_LOSS_CONF"]

    policy = _load_policy()

    out = get_signal_vector_live(symbol=symbol, timeframe=timeframe, limit=limit)
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

    live_pos = get_live_position()

    sizing_cfg = position_sizing.cfg()
    allow_live_writes = bool(sizing_cfg.get("write_live_equity", True))
    context_meta = out.get("context", {}) if isinstance(out.get("context", {}), dict) else {}

    equity_live_value = position_sizing.read_equity_live()
    if allow_live_writes and not EQUITY_LIVE_PATH.exists():
        position_sizing.write_equity_live(equity_live_value)

    final_dir = final["dir"]
    final_conf = final["conf"]
    allow_opens = policy.get("allow_opens", True)

    # DEBUG: force a single tiny test trade when FORCE_TEST_TRADE=1
    if os.getenv("FORCE_TEST_TRADE", "0") == "1":
        print("DEBUG: Forcing test trade (LONG, conf=0.55, size=0.01)")
        # Note: execute_trade doesn't exist, using open_if_allowed as fallback
        # This will only work if policy allows opens and no duplicate position
        open_if_allowed(final_dir=1, final_conf=0.55, entry_min_conf=0.55, risk_mult=1.0)

    def _try_open(direction: int, confidence: float) -> bool:
        if direction == 0:
            return False
        current_pos = get_live_position()
        current_r = float(current_pos.get("risk_r", 0.0)) if isinstance(current_pos, dict) else 0.0
        equity_live_snapshot = position_sizing.read_equity_live()
        risk_r = position_sizing.compute_R(equity_live_snapshot, sizing_cfg)
        if risk_r <= 0:
            print(f"LIVE-DEBUG: skip trade dir={direction} conf={confidence:.4f} - risk_r={risk_r:.2f} <= 0")
            return False
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
            print(f"LIVE-DEBUG: skip trade dir={direction} conf={confidence:.4f} - pretrade check failed: spread={spread_bps}bps latency={latency_ms}ms")
            return False
        opened_local = open_if_allowed(
            final_dir=direction,
            final_conf=confidence,
            entry_min_conf=regime_entry_min_conf,
            risk_mult=rmult,
        )
        if not opened_local:
            print(f"LIVE-DEBUG: skip trade dir={direction} conf={confidence:.4f} - open_if_allowed returned False")
            return False
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
        return opened_local

    if allow_opens and final_dir != 0 and final_conf < MIN_CONF_LIVE:
        print(f"LIVE-DEBUG: skip trade dir={final_dir} conf={final_conf:.4f} < MIN_CONF_LIVE={MIN_CONF_LIVE:.2f}")

    if allow_opens and final_dir != 0 and final_conf >= MIN_CONF_LIVE:
        if not (live_pos and live_pos.get("dir") == final_dir):
            _try_open(final_dir, final_conf)

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
        drop = (final["conf"] < gates_exit_min_conf)
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
        # Gate normal exits (TP, SL, reverse, drop) with minimum hold time
        # Decay is handled separately as it has its own gate (bars_open >= decay_bars)
        if bars_open < MIN_HOLD_BARS_LIVE:
            if take_profit or stop_loss or flip or drop:
                print(f"LIVE-DEBUG: skip exit bars_open={bars_open} < MIN_HOLD_BARS_LIVE={MIN_HOLD_BARS_LIVE}")
        else:
            # Normal exits allowed once minimum hold time is met
            if take_profit:
                close_pct = abs(float(final.get("conf", 0.0)))
            elif stop_loss:
                close_pct = -abs(float(final.get("conf", 0.0)))
            elif drop or flip:
                close_pct = float(final.get("conf", 0.0)) if same_dir else -float(final.get("conf", 0.0))
                reopen_after_flip = flip and policy.get("allow_opens", True)
        # Decay exit is independent and only requires bars_open >= decay_bars
        if decay and close_pct is None:
            close_pct = float(final.get("conf", 0.0)) if same_dir else -float(final.get("conf", 0.0))

        if close_pct is not None:
            # Get prices for price-based PnL calculation
            entry_price = live_pos.get("entry_px")
            exit_price = None
            pos_dir = live_pos.get("dir")
            
            # Get latest bar's close price as exit_price
            ohlcv_rows = get_live_ohlcv(symbol=symbol, timeframe=timeframe, limit=1)
            if ohlcv_rows and len(ohlcv_rows) > 0:
                exit_price = ohlcv_rows[-1].get("close")
            
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
            
            equity_before = position_sizing.read_equity_live()
            cap_adj = float(sizing_cfg.get("cap_adj_pct", 0.0) or 0.0)
            adj_pct = position_sizing.cap_pct(float(final_pct), cap_adj)
            fees_bps = float(sizing_cfg.get("fees_bps_default", 0.0))
            slip_bps = float(sizing_cfg.get("slip_bps_default", 0.0))
            pct_net = adj_pct - ((fees_bps + slip_bps) / 10000.0)
            fraction = float(position_sizing.risk_fraction(sizing_cfg))
            r_value = pct_net * fraction
            equity_live_value = max(0.0, float(equity_before) * (1.0 + r_value))
            close_now(pct=final_pct, entry_price=entry_price, exit_price=exit_price, dir=pos_dir)
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
                _try_open(final["dir"], final["conf"])

    update_pf_reports(
        TRADES_PATH,
        REPORTS / "pf_local.json",
        REPORTS / "pf_live.json",
    )

    equity_live_out = position_sizing.read_equity_live()

    return {
        "ts": bar_ts or _now(),
        "regime": regime,
        "final": final,
        "policy": policy,
        "pa": {"armed": bool(pa_status.get("armed")), "rmult": float(pa_mult)},
        "risk_adapter": adapter,
        "context": out.get("context", {}),
        "equity_live": equity_live_out,
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
