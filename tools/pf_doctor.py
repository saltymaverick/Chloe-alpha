#!/usr/bin/env python3
"""PF Doctor - quick PF summary from trades.jsonl."""

from __future__ import annotations

import argparse
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


def _summarize(trades: list[Dict[str, Any]], include_scratch: bool = False) -> Dict[str, Any]:
    """
    Summarize trades, optionally filtering out scratch trades.
    
    Args:
        trades: List of trade events
        include_scratch: If False, exclude trades with is_scratch=True
    """
    open_count = 0
    close_count = 0
    scratch_count = 0
    sum_pos = 0.0
    sum_neg = 0.0

    for entry in trades:
        event_type = str(entry.get("type") or entry.get("event") or "").lower()
        if event_type == "open":
            open_count += 1
        elif event_type == "close":
            close_count += 1
            
            # Phase 1: Filter out scratch trades unless explicitly included
            is_scratch = entry.get("is_scratch", False)
            if not include_scratch and is_scratch:
                scratch_count += 1
                continue
            
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
        "scratch": scratch_count,
        "meaningful_closes": close_count - scratch_count,
        "sum_pos": sum_pos,
        "sum_neg": sum_neg,
        "pf": pf,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="PF Doctor - quick PF summary from trades.jsonl")
    parser.add_argument(
        "--include-scratch",
        action="store_true",
        help="Include scratch trades (default: exclude them from PF calculation)",
    )
    args = parser.parse_args()
    
    trades = _load_trades(TRADES_PATH)
    summary = _summarize(trades, include_scratch=args.include_scratch)

    print(f"Trades (open/close): {summary['opens']} / {summary['closes']}")
    
    # Phase 1: Show scratch summary
    if summary['scratch'] > 0:
        print(f"Scratch closes (excluded): {summary['scratch']}")
        print(f"Meaningful closes: {summary['meaningful_closes']}")
    else:
        print(f"Meaningful closes: {summary['meaningful_closes']}")
    
    print(f"Positive pct sum: {summary['sum_pos']:.6f}")
    print(f"Negative pct sum: {summary['sum_neg']:.6f}")
    pf = summary["pf"]
    if pf == float("inf"):
        print("PF (meaningful only): infinity (no losses)")
    else:
        print(f"PF (meaningful only): {pf:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
