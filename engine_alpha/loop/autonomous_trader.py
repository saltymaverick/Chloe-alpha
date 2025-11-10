from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict

import yaml

from engine_alpha.signals.signal_processor import get_signal_vector, get_signal_vector_live
from engine_alpha.core.confidence_engine import decide
from engine_alpha.core.paths import REPORTS, CONFIG
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
from engine_alpha.core import position_sizing

TRADES_PATH = REPORTS / "trades.jsonl"
ORCH_SNAPSHOT = REPORTS / "orchestrator_snapshot.json"
EQUITY_CURVE_LIVE_PATH = REPORTS / "equity_curve_live.jsonl"
PF_LIVE_PATH = REPORTS / "pf_local_live.json"


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


def _append_equity_live_record(ts: str, equity: float, adj_pct: float, risk_r: float) -> None:
    EQUITY_CURVE_LIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": ts,
        "equity": float(equity),
        "adj_pct": float(adj_pct),
        "risk_r": float(risk_r),
    }
    with EQUITY_CURVE_LIVE_PATH.open("a") as handle:
        handle.write(json.dumps(payload) + "\n")


def _update_pf_live() -> None:
    if not EQUITY_CURVE_LIVE_PATH.exists():
        return
    pos_sum = 0.0
    neg_sum = 0.0
    count = 0
    try:
        for raw in EQUITY_CURVE_LIVE_PATH.read_text().splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except Exception:
                continue
            adj = entry.get("adj_pct")
            if not isinstance(adj, (int, float)):
                continue
            adj_val = float(adj)
            if adj_val > 0:
                pos_sum += adj_val
            elif adj_val < 0:
                neg_sum += abs(adj_val)
            count += 1
    except Exception:
        return
    if count == 0:
        return
    if neg_sum > 0:
        pf_val = pos_sum / neg_sum
    elif pos_sum > 0:
        pf_val = float("inf")
    else:
        pf_val = 0.0
    PF_LIVE_PATH.write_text(json.dumps({"pf": pf_val, "count": count}, indent=2))


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


def run_step(entry_min_conf: float = 0.58, exit_min_conf: float = 0.42, reverse_min_conf: float = 0.55):
    exit_cfg = _load_exit_config()
    decay_bars = exit_cfg["DECAY_BARS"]
    take_profit_conf = exit_cfg["TAKE_PROFIT_CONF"]
    stop_loss_conf = exit_cfg["STOP_LOSS_CONF"]

    policy = _load_policy()

    out = get_signal_vector()
    decision = decide(out["signal_vector"], out["raw_registry"])
    final = decision["final"]
    regime = decision["regime"]

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
                                 entry_min_conf=entry_min_conf,
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
        flip = (final["dir"] != 0 and final["dir"] != pos["dir"] and final["conf"] >= reverse_min_conf)
        drop = (final["conf"] < exit_min_conf)
        decay = (pos["bars_open"] >= decay_bars)

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
                    entry_min_conf=entry_min_conf,
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


def run_step_live(symbol: str = "ETHUSDT",
                  timeframe: str = "1h",
                  limit: int = 200,
                  entry_min_conf: float = 0.58,
                  exit_min_conf: float = 0.42,
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

    def _try_open(direction: int, confidence: float) -> bool:
        if direction == 0:
            return False
        current_pos = get_live_position()
        current_r = float(current_pos.get("risk_r", 0.0)) if isinstance(current_pos, dict) else 0.0
        equity_live_value = position_sizing.read_equity_live()
        risk_r = position_sizing.compute_R(equity_live_value, sizing_cfg)
        if risk_r <= 0:
            return False
        gross_after = current_r + risk_r
        symbol_after = current_r + risk_r
        if not position_sizing.can_open(gross_after, symbol_after, sizing_cfg):
            return False
        spread_bps = _extract_spread_bps(context_meta)
        latency_ms = _extract_latency_ms(context_meta)
        if not position_sizing.pretrade_check(spread_bps, latency_ms, sizing_cfg):
            return False
        opened_local = open_if_allowed(
            final_dir=direction,
            final_conf=confidence,
            entry_min_conf=entry_min_conf,
            risk_mult=rmult,
        )
        if opened_local:
            ts_val = bar_ts or _now()
            new_pos = {
                "dir": direction,
                "bars_open": 0,
                "entry_px": 1.0,
                "last_ts": ts_val,
                "risk_r": risk_r,
            }
            set_live_position(new_pos)
            set_position(new_pos)
            _annotate_last_open(float(pa_mult), adapter, rmult)
        return opened_local

    if policy.get("allow_opens", True) and final["dir"] != 0:
        if not (live_pos and live_pos.get("dir") == final["dir"]):
            _try_open(final["dir"], final["conf"])

    live_pos = get_live_position()
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
            and final["conf"] >= reverse_min_conf
        )
        drop = (final["conf"] < exit_min_conf)
        decay = (live_pos["bars_open"] >= decay_bars)

        close_pct = None
        reopen_after_flip = False
        if take_profit:
            close_pct = abs(float(final.get("conf", 0.0)))
        elif stop_loss:
            close_pct = -abs(float(final.get("conf", 0.0)))
        elif drop or flip or decay:
            close_pct = float(final.get("conf", 0.0)) if same_dir else -float(final.get("conf", 0.0))
            reopen_after_flip = flip and policy.get("allow_opens", True)

        if close_pct is not None:
            risk_r = float(live_pos.get("risk_r", 0.0))
            slippage_cap = float(sizing_cfg.get("slippage_bps_cap", 50)) / 10000.0
            adj_pct = float(close_pct)
            if slippage_cap > 0:
                adj_pct = max(-slippage_cap, min(slippage_cap, adj_pct))
            close_now(pct=close_pct)
            equity_live_value = position_sizing.read_equity_live()
            equity_live_value = float(equity_live_value + adj_pct * risk_r)
            if allow_live_writes:
                position_sizing.write_equity_live(equity_live_value)
                _append_equity_live_record(bar_ts or _now(), equity_live_value, adj_pct, risk_r)
                _update_pf_live()
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
    for _ in range(n):
        info = run_step()
    (REPORTS / "loop_health.json").write_text(json.dumps({
        "ts": _now(),
        "last": info
    }, indent=2))
    return info
