#!/usr/bin/env python3
"""
PnL diagnostic - Phase 14
Refreshes PF reports and equity curve from trades.jsonl.
"""

from __future__ import annotations

import json
import math

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


def _format_value(value):
    if isinstance(value, (int, float)):
        if math.isinf(value):
            return "∞"
        return f"{value:.4f}"
    return value


def main():
    trades_path = REPORTS / "trades.jsonl"
    update_pf_reports(
        trades_path,
        REPORTS / "pf_local.json",
        REPORTS / "pf_live.json",
    )

    pf_local = _read_json(REPORTS / "pf_local.json")
    pf_norm = _read_json(REPORTS / "pf_local_norm.json")
    pf_live_weighted = _read_json(REPORTS / "pf_local_live.json")

    pf_full = _format_value(pf_local.get("pf", "N/A"))
    pf_norm_val = _format_value(pf_norm.get("pf", "N/A"))
    pf_live_val = _format_value(pf_live_weighted.get("pf", "N/A"))

    last_equity_norm = _format_value(_last_equity(REPORTS / "equity_curve_norm.jsonl"))
    last_equity_live = _format_value(_last_equity(REPORTS / "equity_curve_live.jsonl"))

    print(
        f"PF_full={pf_full} | "
        f"PF_norm={pf_norm_val} | "
        f"PF_live={pf_live_val} | "
        f"last_equity_norm={last_equity_norm} | "
        f"last_equity_live={last_equity_live}"
    )


if __name__ == "__main__":
    main()
