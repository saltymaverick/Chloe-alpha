#!/usr/bin/env python3
"""
CLI wrapper for the regime drift monitor.
"""

from __future__ import annotations

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT_DIR / "reports"
RESEARCH_DIR = REPORTS_DIR / "research"


def main() -> None:
    from engine_alpha.metrics.drift_monitor import build_regime_drift_report

    output_path = RESEARCH_DIR / "regime_drift_report.json"
    report_path = build_regime_drift_report(
        stats_root=RESEARCH_DIR,
        history_root=RESEARCH_DIR / "history",
        output_path=output_path,
    )
    print(f"📈 Regime drift report updated at {report_path}")

    import json

    data = json.loads(report_path.read_text())
    symbols = data.get("symbols", {})
    print("\nREGIME DRIFT")
    print("------------")
    if not symbols:
        print("  No symbols processed.")
        return

    for symbol, regimes in symbols.items():
        if not regimes:
            continue
        print(f"  {symbol}:")
        for regime, entry in regimes.items():
            current_edge = entry.get("current_edge")
            delta = entry.get("delta")
            state = entry.get("state", "unknown")
            current_display = f"{current_edge:.6f}" if isinstance(current_edge, (int, float)) else "n/a"
            delta_display = f"{delta:+.6f}" if isinstance(delta, (int, float)) else "n/a"
            print(f"    - {regime}: {state} (edge {current_display}, Δ {delta_display})")


if __name__ == "__main__":
    main()

