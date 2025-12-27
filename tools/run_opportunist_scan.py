#!/usr/bin/env python3
"""
Run the opportunist scanner + micro research + paper trader in one shot.
"""

from __future__ import annotations

from datetime import datetime, timezone

from engine_alpha.opportunist.micro_research import run_micro_research
from engine_alpha.opportunist.opportunist_trader import run_opportunist_trader
from engine_alpha.opportunist.scanner import scan_opportunist_candidates


def main() -> None:
    print("OPPORTUNIST SCAN")
    print("================")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print()

    print("➡ Scanning Bybit USDT spot universe for candidates...")
    scan_result = scan_opportunist_candidates()
    candidate_count = len(scan_result.get("candidates", []))
    print(
        f"  - Universe={scan_result.get('universe_size', 0)} symbols, "
        f"selected {candidate_count} candidate(s)."
    )

    print("\n➡ Running micro-research on top candidates...")
    research_result = run_micro_research()
    research_count = len(research_result.get("results", []))
    print(f"  - Micro-research completed for {research_count} symbol(s).")

    print("\n➡ Running opportunist trader (paper-only)...")
    trades_result = run_opportunist_trader()
    trade_count = len(trades_result.get("trades", []))
    print(f"  - Paper trades executed: {trade_count}. Logged to reports/opportunist.")

    print("\nOPPORTUNIST SCAN COMPLETE\n")


if __name__ == "__main__":
    main()

