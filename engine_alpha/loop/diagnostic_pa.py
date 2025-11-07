#!/usr/bin/env python3
"""
Profit Amplifier Diagnostic - Phase 5
Shows PA arm/disarm logic end-to-end (paper only).
"""

import argparse
import json
from pathlib import Path
from datetime import datetime, timezone
import random

from engine_alpha.core.paths import REPORTS
from engine_alpha.reflect.trade_analysis import update_pf_reports
from engine_alpha.core.profit_amplifier import evaluate


def _append_trade(event: dict) -> None:
    trades_path = REPORTS / "trades.jsonl"
    trades_path.parent.mkdir(parents=True, exist_ok=True)
    with open(trades_path, "a") as f:
        f.write(json.dumps(event) + "\n")


def _seed_synthetic_trades(target_count: int = 25) -> None:
    """Seed synthetic CLOSE trades to reach at least target_count closes."""
    trades_path = REPORTS / "trades.jsonl"
    # Count existing CLOSEs
    closes = 0
    if trades_path.exists():
        with open(trades_path, "r") as f:
            for line in f:
                try:
                    evt = json.loads(line)
                    if evt.get("event") == "CLOSE":
                        closes += 1
                except Exception:
                    pass
    needed = max(0, target_count - closes)
    if needed == 0:
        return
    random.seed(42)
    ts_base = datetime.now(timezone.utc)
    for i in range(needed):
        win = (i % 3) != 0  # 2 wins, 1 loss pattern
        pnl = 0.01 * random.uniform(0.3, 1.2) if win else -0.01 * random.uniform(0.3, 1.0)
        evt = {
            "event": "CLOSE",
            "direction": "LONG" if win else "SHORT",
            "entry_price": 3000.0,
            "exit_price": 3000.0 * (1.0 + pnl),
            "size": 1.0,
            "pnl_pct": pnl,
            "bars_open": 1,
            "entry_ts": (ts_base).isoformat(),
            "exit_ts": (ts_base).isoformat(),
            "reason": "SEED",
        }
        _append_trade(evt)


def _make_losing_tail(n: int = 10) -> None:
    """Append n losing CLOSE trades."""
    ts_base = datetime.now(timezone.utc)
    for i in range(n):
        pnl = -0.01 * (0.5)  # fixed -0.5%
        evt = {
            "event": "CLOSE",
            "direction": "LONG",
            "entry_price": 3000.0,
            "exit_price": 3000.0 * (1.0 + pnl),
            "size": 1.0,
            "pnl_pct": pnl,
            "bars_open": 1,
            "entry_ts": (ts_base).isoformat(),
            "exit_ts": (ts_base).isoformat(),
            "reason": "SEED_LOSS",
        }
        _append_trade(evt)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate", action="store_true", help="Generate synthetic trades for arm/disarm cases")
    args = parser.parse_args()

    trades_path = REPORTS / "trades.jsonl"

    if args.simulate:
        # Case A: Seed to reach >= 20 trades with pf_local >= 1.05
        _seed_synthetic_trades(target_count=25)
        update_pf_reports(trades_path, REPORTS / "pf_local.json", REPORTS / "pf_live.json")
        state_a = evaluate()
        print("Case A (arm):", json.dumps(state_a, indent=2))

        # Case B: Append 10 losing trades to force disarm
        _make_losing_tail(10)
        update_pf_reports(trades_path, REPORTS / "pf_local.json", REPORTS / "pf_live.json")
        state_b = evaluate()
        print("Case B (disarm):", json.dumps(state_b, indent=2))

        snapshot = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "case_a": state_a,
            "case_b": state_b,
        }
    else:
        # Non-simulated run: If file is too small, seed a small set
        _seed_synthetic_trades(target_count=20)
        update_pf_reports(trades_path, REPORTS / "pf_local.json", REPORTS / "pf_live.json")
        state = evaluate()
        print(json.dumps(state, indent=2))
        snapshot = {"ts": datetime.now(timezone.utc).isoformat(), "state": state}

    out_path = REPORTS / "pa_diag_snapshot.json"
    with open(out_path, "w") as f:
        json.dump(snapshot, f, indent=2)
    print(f"\n✅ PA diagnostic snapshot written to: {out_path}")


if __name__ == "__main__":
    main()
