#!/usr/bin/env python3
"""
Generate and display market state summary.

Usage:
    python3 -m tools.market_state_summary
"""

from __future__ import annotations

from engine_alpha.overseer.market_state_summarizer import summarize_market_state


def main() -> None:
    report = summarize_market_state()
    print("MARKET STATE SUMMARY")
    print("--------------------")
    print(f"Generated at: {report.get('generated_at', 'unknown')}")
    print(f"Timeframe   : {report.get('timeframe', 'unknown')}")
    print()

    assets = report.get("assets", {})
    for symbol, info in assets.items():
        print(f"{symbol}:")
        print(f"  Regime      : {info.get('regime', 'unknown')}")
        print(f"  Slope5/20   : {info.get('slope_5')} / {info.get('slope_20')}")
        print(f"  ATR rel     : {info.get('atr_rel')}")
        print(f"  Feed state  : {info.get('feed_state', 'unknown')}")
        print(f"  Expect freq : {info.get('expected_trade_frequency', 'unknown')}")
        print(f"  Comment     : {info.get('comment', '')}")
        print()


if __name__ == "__main__":
    main()

