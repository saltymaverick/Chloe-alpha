#!/usr/bin/env python3
"""
Risk adapter diagnostic - Phase 20
Evaluates drawdown-based risk multipliers.
"""

from __future__ import annotations

import json
from pathlib import Path

from engine_alpha.core.paths import REPORTS
from engine_alpha.core.risk_adapter import evaluate


def main():
    result = evaluate()
    dd = result.get("drawdown")
    dd_pct = f"{dd * 100:.2f}%" if isinstance(dd, (int, float)) else "N/A"
    print(
        "RISK: band={band}  mult={mult:.2f}  dd={dd}  equity={equity}  peak={peak}".format(
            band=result.get("band"),
            mult=float(result.get("mult", 1.0)),
            dd=dd_pct,
            equity=result.get("equity"),
            peak=result.get("peak"),
        )
    )
    log_path = REPORTS / "risk_adapter.jsonl"
    if log_path.exists():
        lines = log_path.read_text().splitlines()[-3:]
        print("Log tail:")
        for line in lines:
            try:
                print(json.loads(line))
            except Exception:
                print(line)


if __name__ == "__main__":
    main()
