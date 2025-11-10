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
)
from engine_alpha.reflect.trade_analysis import update_pf_reports

TRADES_PATH = REPORTS / "trades.jsonl"
ORCH_SNAPSHOT = REPORTS / "orchestrator_snapshot.json"


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


def _load_decay_bars() -> int:
    gates_path = CONFIG / "gates.yaml"
    try:
        with gates_path.open("r") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception:
        data = {}
    exit_cfg = data.get("EXIT") or data.get("exit")
    value = None
    if isinstance(exit_cfg, dict):
        value = exit_cfg.get("DECAY_BARS") or exit_cfg.get("decay_bars")
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 8


DECAY_BARS = _load_decay_bars()


def run_step(entry_min_conf: float = 0.58, exit_min_conf: float = 0.42, reverse_min_conf: float = 0.55):
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
        flip = (final["dir"] != 0 and final["dir"] != pos["dir"] and final["conf"] >= reverse_min_conf)
        drop = (final["conf"] < exit_min_conf)
        decay = (pos["bars_open"] >= DECAY_BARS)
        if drop or flip or decay:
            pnl = final["conf"] if final["dir"] == pos["dir"] else -final["conf"]
            close_now(pct=pnl)
            if flip and policy.get("allow_opens", True):
                if open_if_allowed(final_dir=final["dir"],
                                   final_conf=final["conf"],
                                   entry_min_conf=entry_min_conf,
                                   risk_mult=rmult):
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

    if policy.get("allow_opens", True):
        if not (live_pos and live_pos.get("dir") == final["dir"]):
            opened = open_if_allowed(
                final_dir=final["dir"],
                final_conf=final["conf"],
                entry_min_conf=entry_min_conf,
                risk_mult=rmult,
            )
            if opened:
                set_live_position({
                    "dir": final["dir"],
                    "bars_open": 0,
                    "entry_px": 1.0,
                    "last_ts": bar_ts or _now(),
                })
                _annotate_last_open(float(pa_mult), adapter, rmult)

    live_pos = get_live_position()
    if live_pos and live_pos.get("dir"):
        live_pos["bars_open"] = live_pos.get("bars_open", 0) + 1
        live_pos["last_ts"] = bar_ts or _now()
        set_live_position(live_pos)
        flip = (
            final["dir"] != 0
            and final["dir"] != live_pos["dir"]
            and final["conf"] >= reverse_min_conf
        )
        drop = (final["conf"] < exit_min_conf)
        decay = (live_pos["bars_open"] >= DECAY_BARS)
        if drop or flip or decay:
            pnl = final["conf"] if final["dir"] == live_pos["dir"] else -final["conf"]
            close_now(pct=pnl)
            clear_live_position()
            if flip and policy.get("allow_opens", True):
                if open_if_allowed(
                    final_dir=final["dir"],
                    final_conf=final["conf"],
                    entry_min_conf=entry_min_conf,
                    risk_mult=rmult,
                ):
                    set_live_position({
                        "dir": final["dir"],
                        "bars_open": 0,
                        "entry_px": 1.0,
                        "last_ts": bar_ts or _now(),
                    })
                    _annotate_last_open(float(pa_mult), adapter, rmult)

    update_pf_reports(
        TRADES_PATH,
        REPORTS / "pf_local.json",
        REPORTS / "pf_live.json",
    )

    return {
        "ts": bar_ts or _now(),
        "regime": regime,
        "final": final,
        "policy": policy,
        "pa": {"armed": bool(pa_status.get("armed")), "rmult": float(pa_mult)},
        "risk_adapter": adapter,
        "context": out.get("context", {}),
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
