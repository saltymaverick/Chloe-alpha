#!/usr/bin/env python3
"""PF Doctor - quick PF summary from trades.jsonl."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from engine_alpha.core.paths import REPORTS

TRADES_PATH = REPORTS / "trades.jsonl"


def _load_trades(path: Path) -> list[Dict[str, Any]]:
    if not path.exists():
        return []
    trades: list[Dict[str, Any]] = []
    for raw in path.read_text().splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        trades.append(obj)
    return trades


def _summarize(trades: list[Dict[str, Any]]) -> Dict[str, Any]:
    open_count = 0
    close_count = 0
    sum_pos = 0.0
    sum_neg = 0.0

    for entry in trades:
        event_type = str(entry.get("type") or entry.get("event") or "").lower()
        if event_type == "open":
            open_count += 1
        elif event_type == "close":
            close_count += 1
            try:
                pct = float(entry.get("pct", 0.0))
            except Exception:
                pct = 0.0
            if pct > 0:
                sum_pos += pct
            elif pct < 0:
                sum_neg += abs(pct)

    if sum_neg == 0:
        if sum_pos > 0:
            pf = float("inf")
        else:
            pf = 0.0
    else:
        pf = sum_pos / sum_neg

    return {
        "opens": open_count,
        "closes": close_count,
        "sum_pos": sum_pos,
        "sum_neg": sum_neg,
        "pf": pf,
    }


def main() -> int:
    trades = _load_trades(TRADES_PATH)
    summary = _summarize(trades)

    print(f"Trades (open/close): {summary['opens']} / {summary['closes']}")
    print(f"Positive pct sum: {summary['sum_pos']:.6f}")
    print(f"Negative pct sum: {summary['sum_neg']:.6f}")
    pf = summary["pf"]
    if pf == float("inf"):
        print("PF: infinity (no losses)")
    else:
        print(f"PF: {pf:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
