#!/usr/bin/env python3
"""
OHLCV Downloader - Binance Public API
Downloads historical OHLCV data from Binance and saves to CSV.
Run once (NOT in live loop) to build your historical dataset.
"""

from __future__ import annotations

import csv
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import requests

from engine_alpha.core.paths import DATA

DATA_ROOT = DATA / "ohlcv"
DATA_ROOT.mkdir(parents=True, exist_ok=True)


def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> List[List]:
    """
    Fetch klines from Binance public API.
    Returns list of kline arrays: [open_time, open, high, low, close, volume, ...]
    """
    url = "https://api.binance.com/api/v3/klines"
    out: List[List] = []
    
    while start_ms < end_ms:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": 1000,
        }
        
        try:
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            klines = r.json()
            
            if not klines:
                break
            
            out.extend(klines)
            last_open_time = klines[-1][0]
            start_ms = last_open_time + 1
            
            # Rate limiting
            time.sleep(0.2)
            
        except requests.RequestException as e:
            print(f"⚠️  Error fetching klines: {e}")
            break
    
    return out


def interval_to_binance(interval: str) -> str:
    """Convert timeframe string to Binance interval format."""
    # Binance intervals: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M
    mapping = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "1h": "1h",
        "4h": "4h",
        "1d": "1d",
    }
    return mapping.get(interval, interval)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Download historical OHLCV data from Binance"
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
        "--start-year",
        type=int,
        default=2019,
        help="Start year (default: 2019)",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=2025,
        help="End year (default: 2025)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output CSV path (default: data/ohlcv/{symbol}_{timeframe}_{start_year}_{end_year}.csv)",
    )
    
    args = parser.parse_args()
    
    symbol = args.symbol.upper()
    timeframe = args.timeframe
    binance_interval = interval_to_binance(timeframe)
    
    start_dt = datetime(args.start_year, 1, 1, tzinfo=timezone.utc)
    end_dt = datetime(args.end_year, 1, 1, tzinfo=timezone.utc)
    
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)
    
    print("=" * 70)
    print("Binance OHLCV Downloader")
    print("=" * 70)
    print(f"Symbol:     {symbol}")
    print(f"Timeframe:  {timeframe} ({binance_interval})")
    print(f"Start:      {start_dt.isoformat()}")
    print(f"End:        {end_dt.isoformat()}")
    print()
    
    print("Fetching klines from Binance...")
    klines = fetch_klines(symbol, binance_interval, start_ms, end_ms)
    
    if not klines:
        print("❌ No klines returned")
        return
    
    print(f"   ✅ Fetched {len(klines)} klines")
    
    # Determine output path
    if args.output:
        out_path = Path(args.output)
    else:
        fname = f"{symbol}_{timeframe}_{args.start_year}_{args.end_year}.csv"
        out_path = DATA_ROOT / fname
    
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write CSV
    print(f"\nWriting to {out_path}...")
    with out_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ts", "open", "high", "low", "close", "volume"])
        
        for k in klines:
            # Binance kline format: [open_time, open, high, low, close, volume, ...]
            open_time_ms = k[0]
            ts = datetime.fromtimestamp(open_time_ms / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")
            writer.writerow([
                ts,
                k[1],  # open
                k[2],  # high
                k[3],  # low
                k[4],  # close
                k[5],  # volume
            ])
    
    print(f"   ✅ Wrote {len(klines)} candles to {out_path}")
    print("=" * 70)
    print(f"\n📊 Next steps:")
    print(f"   1. Verify CSV: head -n 5 {out_path}")
    print(f"   2. Run backtest:")
    print(f"      python3 -m tools.backtest_harness \\")
    print(f"        --symbol {symbol} \\")
    print(f"        --timeframe {timeframe} \\")
    print(f"        --start {start_dt.isoformat()} \\")
    print(f"        --end {end_dt.isoformat()} \\")
    print(f"        --csv {out_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()





