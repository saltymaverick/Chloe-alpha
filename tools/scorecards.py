#!/usr/bin/env python3
"""
CLI helper to build and inspect scorecards.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT_DIR / "reports"
SCORECARD_DIR = REPORTS_DIR / "scorecards"
SCORECARD_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def main() -> None:
    from engine_alpha.metrics.scorecard_builder import (
        build_asset_scorecards,
        build_strategy_scorecards,
    )

    trades_path = REPORTS_DIR / "trades.jsonl"
    pf_path = REPORTS_DIR / "pf_local.json"
    asset_out = SCORECARD_DIR / "asset_scorecards.json"
    strat_out = SCORECARD_DIR / "strategy_scorecards.json"

    print("📊 Building scorecards...")
    build_asset_scorecards(trades_path=trades_path, pf_path=pf_path, output_path=asset_out)
    build_strategy_scorecards(trades_path=trades_path, output_path=strat_out)
    print("  ✅ Scorecards updated")

    assets = _load_json(asset_out).get("assets", [])
    strategies = _load_json(strat_out).get("overall", [])

    print("\nASSET SCORECARDS")
    print("----------------")
    if not assets:
        print("  (no trades yet)")
    else:
        for row in assets:
            pf_val = row.get("pf")
            pf_display = "∞" if pf_val is None and row.get("wins", 0) > 0 and row.get("losses", 0) == 0 else f"{pf_val:.2f}" if isinstance(pf_val, (int, float)) else "—"
            print(
                f"  {row['symbol']}: PF={pf_display}, trades={row['total_trades']} (wins={row['wins']}, losses={row['losses']})"
            )

    print("\nSTRATEGY SCORECARDS (overall)")
    print("-----------------------------")
    if not strategies:
        print("  (no strategy trades yet)")
    else:
        for row in strategies:
            pf_val = row.get("pf")
            pf_display = "∞" if pf_val is None and row.get("wins", 0) > 0 and row.get("losses", 0) == 0 else f"{pf_val:.2f}" if isinstance(pf_val, (int, float)) else "—"
            print(
                f"  {row['strategy']}: PF={pf_display}, trades={row['total_trades']} (wins={row['wins']}, losses={row['losses']})"
            )


if __name__ == "__main__":
    main()

