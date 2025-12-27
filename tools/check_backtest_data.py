#!/usr/bin/env python3
"""
Backtest Data Checker
Verifies historical CSV data availability and provides guidance.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from engine_alpha.core.paths import DATA
from engine_alpha.data.historical_prices import load_ohlcv_csv, _parse_ts


def check_data_availability(
    symbol: str = "ETHUSDT",
    timeframe: str = "1h",
    csv_path: Optional[str] = None,
    min_candles: int = 1000,
) -> dict:
    """
    Check if historical CSV data is available and sufficient for backtesting.
    Returns a dict with status and recommendations.
    """
    if csv_path:
        path = Path(csv_path)
    else:
        # Try standard naming convention
        fname = f"{symbol}_{timeframe}_2019_2025.csv"
        path = DATA / "ohlcv" / fname
        
        # Fallback to simpler name
        if not path.exists():
            simple_path = DATA / "ohlcv" / f"{symbol}_{timeframe}.csv"
            if simple_path.exists():
                path = simple_path

    result = {
        "csv_path": str(path),
        "exists": path.exists(),
        "candle_count": 0,
        "date_range": {},
        "sufficient": False,
        "recommendations": [],
    }

    if not path.exists():
        result["recommendations"].append(
            f"❌ CSV not found at {path}"
        )
        result["recommendations"].append(
            "💡 Download ETHUSDT 1h OHLCV from 2019-2025 and place at:"
        )
        result["recommendations"].append(
            f"   {DATA / 'ohlcv' / f'{symbol}_{timeframe}_2019_2025.csv'}"
        )
        return result

    try:
        # Load without date filtering to get full range
        candles = load_ohlcv_csv(symbol, timeframe, csv_path=str(path))
        result["candle_count"] = len(candles)

        if candles:
            first_ts = candles[0]["ts"]
            last_ts = candles[-1]["ts"]
            result["date_range"] = {
                "first": first_ts,
                "last": last_ts,
            }

            # Parse dates to calculate duration
            try:
                first_dt = _parse_ts(first_ts)
                last_dt = _parse_ts(last_ts)
                duration_days = (last_dt - first_dt).days
                result["date_range"]["duration_days"] = duration_days
            except Exception:
                pass

            # Check if sufficient
            if len(candles) >= min_candles:
                result["sufficient"] = True
                result["recommendations"].append(
                    f"✅ Found {len(candles):,} candles - sufficient for backtesting"
                )
            else:
                result["sufficient"] = False
                result["recommendations"].append(
                    f"⚠️  Found {len(candles):,} candles - need at least {min_candles:,} for meaningful backtest"
                )

            # Provide example backtest command
            if result["sufficient"]:
                # Suggest a reasonable date range
                start_year = first_dt.year if first_dt.year >= 2020 else 2020
                end_year = min(last_dt.year, 2023)
                result["recommendations"].append("")
                result["recommendations"].append("📊 Example backtest command:")
                result["recommendations"].append(
                    f"   python3 -m tools.backtest_harness \\"
                )
                result["recommendations"].append(
                    f"     --symbol {symbol} \\"
                )
                result["recommendations"].append(
                    f"     --timeframe {timeframe} \\"
                )
                result["recommendations"].append(
                    f"     --start {start_year}-01-01T00:00:00Z \\"
                )
                result["recommendations"].append(
                    f"     --end {end_year}-01-01T00:00:00Z \\"
                )
                result["recommendations"].append(
                    f"     --window 200 \\"
                )
                result["recommendations"].append(
                    f"     --csv {path}"
                )

        else:
            result["recommendations"].append(
                "⚠️  CSV exists but contains no valid candles"
            )

    except Exception as e:
        result["error"] = str(e)
        result["recommendations"].append(f"❌ Error reading CSV: {e}")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Check backtest data availability"
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="ETHUSDT",
        help="Trading symbol (default: ETHUSDT)",
    )
    parser.add_argument(
        "--timeframe",
        type=str,
        default="1h",
        help="Timeframe (default: 1h)",
    )
    parser.add_argument(
        "--csv",
        dest="csv_path",
        default=None,
        help="Path to CSV file (optional)",
    )
    parser.add_argument(
        "--min-candles",
        type=int,
        default=1000,
        help="Minimum candles required (default: 1000)",
    )

    args = parser.parse_args()

    result = check_data_availability(
        symbol=args.symbol,
        timeframe=args.timeframe,
        csv_path=args.csv_path,
        min_candles=args.min_candles,
    )

    print("=" * 70)
    print("📊 Backtest Data Availability Check")
    print("=" * 70)
    print(f"\nCSV Path: {result['csv_path']}")
    print(f"Exists:   {'✅ Yes' if result['exists'] else '❌ No'}")

    if result["exists"]:
        print(f"\nCandles:  {result['candle_count']:,}")
        if result.get("date_range"):
            dr = result["date_range"]
            print(f"First:    {dr.get('first', 'N/A')}")
            print(f"Last:     {dr.get('last', 'N/A')}")
            if "duration_days" in dr:
                print(f"Duration: {dr['duration_days']:,} days")
        print(f"\nStatus:   {'✅ Sufficient' if result['sufficient'] else '⚠️  Insufficient'}")

    if result.get("recommendations"):
        print("\n" + "\n".join(result["recommendations"]))

    if result.get("error"):
        print(f"\n❌ Error: {result['error']}")

    print("=" * 70)

    # Exit code: 0 if sufficient, 1 if not
    exit(0 if result.get("sufficient", False) else 1)


if __name__ == "__main__":
    main()





