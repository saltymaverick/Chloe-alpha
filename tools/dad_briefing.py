#!/usr/bin/env python3
"""
Dad Briefing — 10-line summary you can read from the terminal.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT_DIR / "config"
REPORTS_DIR = ROOT_DIR / "reports"
TRADES_PATH = REPORTS_DIR / "trades.jsonl"
PF_LOCAL_PATH = REPORTS_DIR / "pf_local.json"


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = path.read_text().strip()
        if not payload:
            return {}
        return json.loads(payload)
    except Exception:
        return {}


def _count_eth_trades() -> int:
    if not TRADES_PATH.exists():
        return 0

    count = 0
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
                symbol = trade.get("symbol", "ETHUSDT").upper()
                if symbol != "ETHUSDT":
                    continue
                if trade.get("type") != "close":
                    continue
                if trade.get("is_scratch", False):
                    continue
                count += 1
    except Exception:
        return 0

    return count


def main() -> None:
    assets = _load_json(CONFIG_DIR / "asset_registry.json")
    enablement = _load_json(CONFIG_DIR / "trading_enablement.json")
    pf_local = _load_json(PF_LOCAL_PATH)

    watching = len(assets)
    trading = [s.upper() for s in enablement.get("enabled_for_trading", [])]
    pf_val = pf_local.get("pf")
    pf_display = f"{pf_val:.2f}" if isinstance(pf_val, (int, float)) else "N/A"

    eth_trades = _count_eth_trades()

    print("CHLOE BRIEFING FOR DAD")
    print("----------------------")
    print(f"Chloe is watching {watching} coins and learning their behavior.")
    if trading:
        joined = ", ".join(trading)
        print(f"She is only trading {joined} in paper (fake money) mode for safety.")
    else:
        print("She is not trading anything yet — still in learning mode.")

    print(f"So far she has made {eth_trades} ETH paper trades with PF {pf_display}.")
    if trading:
        print("Other coins remain in research-only mode while she studies them.")
    else:
        print("All coins are research-only until she proves herself.")


if __name__ == "__main__":
    main()

