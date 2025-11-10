#!/usr/bin/env python3
"""Diagnostic for risk-weighted execution state (Phase 33)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from engine_alpha.core import position_sizing
from engine_alpha.core.paths import REPORTS

EQUITY_CURVE_LIVE = REPORTS / "equity_curve_live.jsonl"
EQUITY_LIVE = REPORTS / "equity_live.json"


def _read_last_line(path: Path) -> Dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        lines: List[str] = [ln.strip() for ln in path.read_text().splitlines() if ln.strip()]
    except Exception:
        return None
    if not lines:
        return None
    try:
        return json.loads(lines[-1])
    except Exception:
        return None


def _read_equity_live() -> Dict[str, Any]:
    if not EQUITY_LIVE.exists():
        return {}
    try:
        data = json.loads(EQUITY_LIVE.read_text())
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def main() -> int:
    cfg = position_sizing.cfg()
    last_curve = _read_last_line(EQUITY_CURVE_LIVE)
    equity_live_state = _read_equity_live()

    print("== Chloe Risk Execution Diagnostic ==")
    print(json.dumps({"accounting": cfg}, indent=2))

    if last_curve:
        print("Last live equity curve entry:")
        print(json.dumps(last_curve, indent=2))
    else:
        print("No entries in equity_curve_live.jsonl")

    print("Current live equity snapshot:")
    print(json.dumps(equity_live_state or {"equity": position_sizing.read_equity_live()}, indent=2))
    print(f"risk_per_trade_bps: {cfg.get('risk_per_trade_bps')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
