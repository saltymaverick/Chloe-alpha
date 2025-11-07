from __future__ import annotations
import json, time
from pathlib import Path

from engine_alpha.signals.signal_processor import get_signal_vector
from engine_alpha.core.confidence_engine import decide
from engine_alpha.reflect.trade_analysis import update_pf_reports

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"
REPORTS.mkdir(parents=True, exist_ok=True)

# Minimal in-memory position & logging (paper)
_position = {"dir": 0, "entry_px": None, "bars_open": 0}
_stats = {"opens": 0, "closes": 0, "reversals": 0}

def _append_trade(event: dict):
    path = REPORTS / "trades.jsonl"
    with path.open("a") as f:
        f.write(json.dumps(event) + "\n")

def run_step():
    out = get_signal_vector()
    decision = decide(out["signal_vector"], out["raw_registry"])
    final = decision["final"]
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    global _position, _stats
    prev_dir = _position["dir"]
    new_dir = final["dir"]

    # entry logic (paper, size=1)
    if prev_dir == 0 and new_dir != 0 and final["conf"] >= 0.5:
        _position = {"dir": new_dir, "entry_px": 1.0, "bars_open": 0}
        _stats["opens"] += 1
        _append_trade({"ts": now, "type": "open", "dir": new_dir, "pct": 0.0})

    # exit/flip logic (confidence drop or flip strong enough)
    if _position["dir"] != 0:
        _position["bars_open"] += 1
        drop = final["conf"] < 0.42
        flip = (new_dir != 0 and new_dir != _position["dir"] and final["conf"] >= 0.55)
        decay = _position["bars_open"] > 8
        if drop or flip or decay:
            # simple P&L proxy: +conf when in same dir, -conf when against (demo only)
            pnl = final["conf"] if new_dir == _position["dir"] else -final["conf"]
            _append_trade({"ts": now, "type": "close", "dir": _position["dir"], "pct": pnl})
            _stats["closes"] += 1
            _position = {"dir": 0, "entry_px": None, "bars_open": 0}
            if flip:
                _stats["reversals"] += 1
                # open opposite immediately (paper)
                _position = {"dir": new_dir, "entry_px": 1.0, "bars_open": 0}
                _stats["opens"] += 1
                _append_trade({"ts": now, "type": "open", "dir": new_dir, "pct": 0.0})

def run_batch(n=25):
    for _ in range(n):
        run_step()

if __name__ == "__main__":
    run_batch(25)
    # write loop health
    (REPORTS / "loop_health.json").write_text(json.dumps({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "position": _position,
        "stats": _stats
    }, indent=2))
    # update PF reports
    update_pf_reports(REPORTS / "trades.jsonl", REPORTS / "pf_local.json", REPORTS / "pf_live.json")
    print("✅ Loop health written to:", REPORTS / "loop_health.json")
    print("✅ PF updated:", REPORTS / "pf_local.json", REPORTS / "pf_live.json")
