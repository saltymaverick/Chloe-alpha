#!/usr/bin/env python3
"""
Debug tool for Price Feed Health.

Shows feed health status for tracked symbols.
"""

from __future__ import annotations

import sys
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine_alpha.data.price_feed_health import is_price_feed_ok, get_latest_price, get_latest_candle_ts
from engine_alpha.core.paths import REPORTS


def main() -> int:
    """Print price feed health for symbols."""
    parser = argparse.ArgumentParser(description="Debug price feed health")
    parser.add_argument("--symbol", type=str, help="Specific symbol to check (e.g., SOLUSDT)")
    args = parser.parse_args()
    
    # Default symbols to check
    if args.symbol:
        symbols = [args.symbol.upper()]
    else:
        # Get symbols from recovery_ramp_v2 or use defaults
        recovery_ramp_v2_path = REPORTS / "risk" / "recovery_ramp_v2.json"
        symbols = []
        
        if recovery_ramp_v2_path.exists():
            import json
            try:
                with recovery_ramp_v2_path.open("r") as f:
                    data = json.load(f)
                    symbols_data = data.get("symbols", {})
                    symbols = list(symbols_data.keys())[:20]  # Limit to first 20
            except Exception:
                pass
        
        if not symbols:
            # Fallback to common symbols
            symbols = ["SOLUSDT", "BNBUSDT", "AVAXUSDT", "ETHUSDT", "BTCUSDT"]
    
    print("=" * 100)
    print("PRICE FEED HEALTH DEBUG")
    print("=" * 100)
    print()
    
    for symbol in symbols:
        print(f"Symbol: {symbol}")
        print("-" * 100)
        
        # Check feed health
        is_ok, meta = is_price_feed_ok(symbol, max_age_seconds=600, require_price=True)
        
        print(f"  OK: {is_ok}")
        print(f"  Source: {meta.get('source_used', 'unknown')}")
        print(f"  Age (seconds): {meta.get('age_seconds', 'N/A')}")
        print(f"  Latest TS: {meta.get('latest_ts', 'N/A')}")
        print(f"  Latest Price: {meta.get('latest_price', 'N/A')}")
        print(f"  Is Stale: {meta.get('is_stale', 'N/A')}")
        
        errors = meta.get("errors", [])
        if errors:
            print(f"  Errors: {errors[:5]}")  # Limit to first 5 errors
        
        # If specific symbol requested, show detailed meta
        if args.symbol:
            print()
            print("  Detailed Meta:")
            import json
            print(json.dumps(meta, indent=4, default=str))
        
        print()
    
    print("=" * 100)
    return 0


if __name__ == "__main__":
    sys.exit(main())

