#!/usr/bin/env python3
"""
tools/inspect_conf_ret_bins.py

Quick inspection tool for conf_ret_summary_multi.json.

Usage examples:

  # Trend-down, high confidence, all horizons
  python3 -m tools.inspect_conf_ret_bins --regime trend_down --min-conf 0.60

  # High-vol, conf >= 0.50
  python3 -m tools.inspect_conf_ret_bins --regime high_vol --min-conf 0.50

  # Trend-up, conf >= 0.60
  python3 -m tools.inspect_conf_ret_bins --regime trend_up --min-conf 0.60
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional


def load_summary(path: Path) -> dict:
    data = json.loads(path.read_text())
    if "bins" not in data:
        raise ValueError(f"No 'bins' key found in {path}")
    return data


def print_bins(
    summary_path: Path,
    regime: Optional[str] = None,
    min_conf: float = 0.0,
    horizons: Optional[list[int]] = None,
) -> None:
    data = load_summary(summary_path)
    bins = data["bins"]

    print(f"Summary file: {summary_path}")
    print(f"Regime filter: {regime or 'ALL'}")
    print(f"Min confidence: {min_conf:.2f}")
    if horizons:
        print(f"Horizons filter: {horizons}")
    print()

    header = (
        "regime   h  conf_range    count   pf    mean     p50      p75      p90"
    )
    print(header)
    print("-" * len(header))

    def horizon_ok(b: dict) -> bool:
        if horizons is None:
            return True
        return b.get("horizon") in horizons

    for b in bins:
        if regime and b["regime"] != regime:
            continue
        if not horizon_ok(b):
            continue
        if b["conf_min"] < min_conf:
            continue

        r = b["regime"]
        h = b.get("horizon", 1)
        cmin, cmax = b["conf_min"], b["conf_max"]
        count = b["count"]
        pf = b["pf"]
        mean_ret = b.get("mean_ret", 0.0)
        p50 = b.get("p50", 0.0)
        p75 = b.get("p75", 0.0)
        p90 = b.get("p90", 0.0)

        print(
            f"{r:<8} {h:<2} [{cmin:.2f},{cmax:.2f}) "
            f"{count:6d}  {pf:5.2f}  {mean_ret:7.5f}  "
            f"{p50:7.5f}  {p75:7.5f}  {p90:7.5f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--summary",
        type=str,
        default="reports/analysis/conf_ret_summary_multi.json",
        help="Path to conf_ret_summary_multi.json",
    )
    parser.add_argument(
        "--regime",
        type=str,
        default=None,
        help="Regime to filter (trend_down, trend_up, high_vol, chop)",
    )
    parser.add_argument(
        "--min-conf",
        type=float,
        default=0.0,
        help="Minimum conf_min to include (e.g., 0.60)",
    )
    parser.add_argument(
        "--horizons",
        type=str,
        default=None,
        help="Comma-separated list of horizons to include (e.g., '1,2,4')",
    )
    args = parser.parse_args()

    summary_path = Path(args.summary)
    horizons: Optional[list[int]] = None
    if args.horizons:
        horizons = [int(x) for x in args.horizons.split(",") if x.strip()]

    print_bins(
        summary_path=summary_path,
        regime=args.regime,
        min_conf=args.min_conf,
        horizons=horizons,
    )


if __name__ == "__main__":
    main()


