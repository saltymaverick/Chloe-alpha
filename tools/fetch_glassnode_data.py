#!/usr/bin/env python3
"""
Manual Glassnode data fetcher.

Fetches and caches Glassnode metrics for configured symbols.
Usage:
    python3 -m tools.fetch_glassnode_data --symbol ETHUSDT
    python3 -m tools.fetch_glassnode_data --all
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from engine_alpha.data.glassnode_fetcher import fetch_glassnode_metrics_for_symbol
from engine_alpha.config.assets import get_enabled_assets


def main():
    parser = argparse.ArgumentParser(description="Fetch and cache Glassnode metrics")
    parser.add_argument("--symbol", type=str, help="Symbol to fetch (e.g. ETHUSDT)")
    parser.add_argument("--all", action="store_true", help="Fetch for all enabled assets")
    parser.add_argument("--days", type=int, default=365, help="Days of history to fetch (default: 365)")
    args = parser.parse_args()

    if not args.symbol and not args.all:
        parser.error("Specify --symbol SYMBOL or --all")

    symbols = []
    if args.symbol:
        symbols = [args.symbol.upper()]
    elif args.all:
        try:
            enabled = get_enabled_assets()
            symbols = [a.symbol for a in enabled]
            print(f"Found {len(symbols)} enabled assets: {', '.join(symbols)}")
        except Exception as e:
            print(f"⚠️  Failed to load enabled assets: {e}")
            print("   Falling back to BTCUSDT and ETHUSDT")
            symbols = ["BTCUSDT", "ETHUSDT"]

    for symbol in symbols:
        print(f"\n{'='*60}")
        print(f"Fetching Glassnode data for {symbol} ({args.days} days)")
        print(f"{'='*60}")
        try:
            df = fetch_glassnode_metrics_for_symbol(symbol, days_back=args.days)
            if not df.empty:
                print(f"✅ Success: {len(df)} rows, {len(df.columns)-1} metrics")
                print(f"   Columns: {', '.join([c for c in df.columns if c != 'ts'])}")
            else:
                print(f"⚠️  No data returned (check API key and symbol mapping)")
        except Exception as e:
            print(f"❌ Failed: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()


