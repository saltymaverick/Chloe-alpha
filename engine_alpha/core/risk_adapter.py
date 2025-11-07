"""
Risk adapter - Phase 20 (paper only)
Computes a drawdown-based risk multiplier from the equity curve.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from engine_alpha.core.paths import REPORTS

EQUITY_PATH = REPORTS / "equity_curve.jsonl"
JSON_PATH = REPORTS / "risk_adapter.json"
LOG_PATH = REPORTS / "risk_adapter.jsonl"

BANDS = (
    ("A", 0.05, 1.00),  # drawdown < 5%
    ("B", 0.10, 0.70),  # drawdown 5-10%
    ("C", float("inf"), 0.50),  # drawdown > 10%
)
MULT_MIN = 0.5
MULT_MAX = 1.25


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_equity() -> List[Dict[str, float]]:
    if not EQUITY_PATH.exists():
        return []
    rows: List[Dict[str, float]] = []
    for line in EQUITY_PATH.read_text().splitlines():
        try:
            obj = json.loads(line)
            rows.append({
                "ts": obj.get("ts"),
                "equity": float(obj.get("equity", float("nan"))),
            })
        except Exception:
            continue
    return rows


def _bounded(mult: float) -> float:
    return max(MULT_MIN, min(MULT_MAX, mult))


def evaluate() -> Dict[str, object]:
    data = _read_equity()
    if len(data) < 1:
        result = {
            "ts": _now(),
            "equity": None,
            "peak": None,
            "drawdown": None,
            "band": None,
            "mult": 1.0,
            "reason": "no_equity_curve",
        }
        JSON_PATH.write_text(json.dumps(result, indent=2))
        return result

    peak = float("-inf")
    last_equity = data[-1]["equity"]
    for entry in data:
        eq = entry.get("equity")
        if eq is None:
            continue
        if eq > peak:
            peak = eq
    if peak <= 0 or last_equity is None:
        drawdown = 0.0
    else:
        drawdown = max(0.0, 1.0 - (last_equity / peak))

    band = "A"
    mult = 1.0
    for name, threshold, value in BANDS:
        if drawdown < threshold:
            band = name
            mult = value
            break
    mult = _bounded(mult)

    result = {
        "ts": _now(),
        "equity": last_equity,
        "peak": peak,
        "drawdown": drawdown,
        "band": band,
        "mult": mult,
        "reason": "computed",
    }

    JSON_PATH.write_text(json.dumps(result, indent=2))
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(result) + "\n")

    return result
