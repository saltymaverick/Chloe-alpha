from __future__ import annotations
import json, time
from engine_alpha.signals.signal_processor import get_signal_vector
from engine_alpha.core.confidence_engine import decide
from engine_alpha.core.paths import REPORTS
from engine_alpha.core.profit_amplifier import evaluate as pa_evaluate, risk_multiplier as pa_rmult
from engine_alpha.loop.execute_trade import open_if_allowed, close_now
from engine_alpha.loop.position_manager import get_open_position, set_position
from engine_alpha.reflect.trade_analysis import update_pf_reports

def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def run_step(entry_min_conf: float = 0.58, exit_min_conf: float = 0.42, reverse_min_conf: float = 0.55):
    out = get_signal_vector()
    decision = decide(out["signal_vector"], out["raw_registry"])
    final = decision["final"]
    regime = decision["regime"]

    pa_status = pa_evaluate(REPORTS / "pa_status.json")
    rmult = pa_rmult(REPORTS / "pa_status.json")

    opened = open_if_allowed(final_dir=final["dir"],
                             final_conf=final["conf"],
                             entry_min_conf=entry_min_conf,
                             risk_mult=rmult)

    pos = get_open_position()
    if pos and pos.get("dir"):
        pos["bars_open"] = pos.get("bars_open", 0) + 1
        set_position(pos)
        flip  = (final["dir"] != 0 and final["dir"] != pos["dir"] and final["conf"] >= reverse_min_conf)
        drop  = (final["conf"] < exit_min_conf)
        decay = (pos["bars_open"] > 8)
        if drop or flip or decay:
            pnl = final["conf"] if final["dir"] == pos["dir"] else -final["conf"]
            close_now(pct=pnl)
            if flip:
                open_if_allowed(final_dir=final["dir"],
                                final_conf=final["conf"],
                                entry_min_conf=entry_min_conf,
                                risk_mult=rmult)

    update_pf_reports(REPORTS / "trades.jsonl",
                      REPORTS / "pf_local.json",
                      REPORTS / "pf_live.json")

    return {"ts": _now(),
            "regime": regime,
            "final": final,
            "pa": {"armed": bool(pa_status.get("armed")), "rmult": float(rmult)}}

def run_batch(n: int = 25):
    info = None
    for _ in range(n):
        info = run_step()
    (REPORTS / "loop_health.json").write_text(json.dumps({
        "ts": _now(),
        "last": info
    }, indent=2))
    return info
