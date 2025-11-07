#!/usr/bin/env python3
"""
PnL diagnostic - Phase 14
Refreshes PF reports and equity curve from trades.jsonl.
"""

from __future__ import annotations

import json

from engine_alpha.core.paths import REPORTS
from engine_alpha.reflect.trade_analysis import update_pf_reports


def _read_json(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _last_equity(curve_path):
    if not curve_path.exists():
        return None
    try:
        with curve_path.open("r") as f:
            lines = f.readlines()
        if not lines:
            return None
        return json.loads(lines[-1]).get("equity")
    except Exception:
        return None


def main():
    trades_path = REPORTS / "trades.jsonl"
    update_pf_reports(
        trades_path,
        REPORTS / "pf_local.json",
        REPORTS / "pf_live.json",
    )

    pf_local = _read_json(REPORTS / "pf_local.json")
    pf_live = _read_json(REPORTS / "pf_live.json")
    pf_local_adj = _read_json(REPORTS / "pf_local_adj.json")
    pf_live_adj = _read_json(REPORTS / "pf_live_adj.json")
    last_equity = _last_equity(REPORTS / "equity_curve.jsonl")

    pf = pf_local.get("pf", "N/A")
    pf_adj = pf_local_adj.get("pf", "N/A")
    count = pf_live.get("count", 0)
    print(f"PF: {pf}  |  PF_adj: {pf_adj}  |  points: {count}  |  last_equity: {last_equity}")


if __name__ == "__main__":
    main()
