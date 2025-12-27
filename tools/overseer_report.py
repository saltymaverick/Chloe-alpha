#!/usr/bin/env python3
"""
CLI for generating and printing the Quant Overseer report.
"""

from __future__ import annotations

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]


def main() -> None:
    from engine_alpha.overseer.quant_overseer import build_overseer_report, DEFAULT_OUTPUT

    report = build_overseer_report(output_path=DEFAULT_OUTPUT)

    print("CHLOE OVERSEER REPORT")
    print("----------------------")
    phase = report.get("phase", "unknown")
    print(f"Phase: {phase}")
    print(report.get("global", {}).get("phase_comment", ""))
    print()

    assets = report.get("assets", {})
    if not assets:
        print("No asset data available.")
    else:
        for symbol, info in assets.items():
            print(f"{symbol}:")
            print(f"  Tier: {info.get('tier')}")
            print(f"  Trading enabled: {info.get('trading_enabled')}")
            pf_val = info.get("pf")
            pf_display = f"{pf_val:.2f}" if isinstance(pf_val, (int, float)) else "—"
            print(f"  Trades: {info.get('total_trades')}  PF: {pf_display}")
            print(f"  Comment: {info.get('overseer_comment')}")
            print()

    global_section = report.get("global", {})
    paper_candidates = global_section.get("ready_for_paper_promote", [])
    live_candidates = global_section.get("ready_for_live_promote", [])

    if paper_candidates:
        print("Recommended paper promotion candidates (advisory only):")
        for sym in paper_candidates:
            print(f"  - {sym}")
    else:
        print("No paper promotion candidates at this time.")

    if live_candidates:
        print("\nRecommended live promotion candidates (advisory only):")
        for sym in live_candidates:
            print(f"  - {sym}")
    else:
        print("\nNo live promotion candidates at this time.")


if __name__ == "__main__":
    main()

