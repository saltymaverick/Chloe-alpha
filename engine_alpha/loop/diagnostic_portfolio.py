#!/usr/bin/env python3
"""
Portfolio diagnostic - Phase 9
Runs the paper multi-asset portfolio orchestrator and prints summary.
"""

import json
from pathlib import Path

from engine_alpha.core.paths import REPORTS
from engine_alpha.loop.portfolio import run_portfolio


def main():
    result = run_portfolio()
    snapshot_path = REPORTS / "portfolio" / "portfolio_snapshot.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    with snapshot_path.open("w") as f:
        json.dump(result, f, indent=2)

    print("Portfolio run complete")
    print(f" Portfolio PF: {result.get('portfolio_pf')}")
    for symbol, data in result.get("summary", {}).items():
        print(f"  {symbol}: PF={data['pf']} opens={data['opens']} closes={data['closes']}")

    sample_symbol = result.get("symbols", ["ETHUSDT"])[0]
    trades_path = REPORTS / "portfolio" / f"{sample_symbol}_trades.jsonl"
    if trades_path.exists():
        print(f"Last trades for {sample_symbol}:")
        with trades_path.open("r") as f:
            lines = f.readlines()[-5:]
        for line in lines:
            print("  ", line.strip())


if __name__ == "__main__":
    main()
