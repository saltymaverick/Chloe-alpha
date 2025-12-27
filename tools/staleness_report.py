#!/usr/bin/env python3
"""
Generate per-asset staleness analysis.

Usage:
    python3 -m tools.staleness_report
"""

from __future__ import annotations

from engine_alpha.overseer.staleness_analyst import (
    build_staleness_report,
    format_human_report,
)


def main() -> None:
    report = build_staleness_report()
    human = format_human_report(report)
    print(human)


if __name__ == "__main__":
    main()

