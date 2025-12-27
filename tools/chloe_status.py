#!/usr/bin/env python3
"""
Chloe Status Report — dad-friendly summary of what Chloe is doing right now.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT_DIR / "config"
REPORTS_DIR = ROOT_DIR / "reports"
TRADES_PATH = REPORTS_DIR / "trades.jsonl"
PF_LOCAL_PATH = REPORTS_DIR / "pf_local.json"


def _load_json(path: Path) -> Dict:
    if not path.exists():
        return {}
    try:
        data = path.read_text().strip()
        if not data:
            return {}
        return json.loads(data)
    except Exception:
        return {}


def _count_trades(symbol: str) -> int:
    """Count real trades (close events) for a symbol, excluding ghost closes."""
    if not TRADES_PATH.exists():
        return 0

    count = 0
    want = symbol.upper()
    try:
        with TRADES_PATH.open("r") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    trade = json.loads(line)
                except json.JSONDecodeError:
                    continue

                trade_symbol = trade.get("symbol", "ETHUSDT").upper()
                if trade_symbol != want:
                    continue
                if trade.get("type") != "close":
                    continue
                if trade.get("is_scratch", False):
                    continue
                
                # Filter out ghost closes
                entry_px = trade.get("entry_px")
                exit_px = trade.get("exit_px")
                regime = trade.get("regime", "")
                pct = trade.get("pct", 0.0)
                
                # Reject ghost closes: no prices, unknown regime, or zero pct with no prices
                is_ghost = False
                if entry_px is None and exit_px is None:
                    is_ghost = True
                if regime == "unknown":
                    is_ghost = True
                if pct == 0.0 and entry_px is None and exit_px is None:
                    is_ghost = True
                
                if is_ghost:
                    continue
                
                count += 1
    except Exception:
        return 0

    return count


def main() -> None:
    assets = _load_json(CONFIG_DIR / "asset_registry.json")
    rollout = _load_json(CONFIG_DIR / "trading_enablement.json")
    pf_local = _load_json(PF_LOCAL_PATH)

    total_assets = len(assets)
    enabled_symbols: List[str] = [
        s.upper() for s in rollout.get("enabled_for_trading", [])
    ]
    phase = rollout.get("phase", "phase_0")
    pf_val = pf_local.get("pf")

    print("=" * 60)
    print("CHLOE STATUS")
    print("=" * 60)
    print(f"Phase              : {phase.replace('_', ' ').title()}")
    print(f"Total assets wired : {total_assets}")
    print()

    if enabled_symbols:
        print("Trading (paper)    :", ", ".join(enabled_symbols))
        for symbol in enabled_symbols:
            trades = _count_trades(symbol)
            pf_display = f"≈ {pf_val:.2f}" if isinstance(pf_val, (int, float)) else "No PF yet"
            print(f"  {symbol}: {trades} trades, PF {pf_display}")
    else:
        print("Trading (paper)    : None")
        print("  No trades yet")

    print()
    print("Other assets are collecting data and running research,")
    print("but trading is disabled for safety.")
    print("=" * 60)


if __name__ == "__main__":
    main()

