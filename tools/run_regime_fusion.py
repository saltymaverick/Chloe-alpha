#!/usr/bin/env python3
"""
CLI wrapper for Regime Awareness V2.

Usage (from repo root, venv active):
    python -m tools.run_regime_fusion --symbols ETHUSDT,BTCUSDT,SOLUSDT --timeframe 15m

This is PAPER-only and advisory-only – it only writes research reports.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine_alpha.core.regime_fusion import run_regime_fusion_for_universe


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run Regime Fusion V2 for a symbol universe.")
    p.add_argument(
        "--symbols",
        type=str,
        required=True,
        help="Comma-separated list of symbols, e.g. ETHUSDT,BTCUSDT,SOLUSDT",
    )
    p.add_argument(
        "--timeframe",
        type=str,
        default="15m",
        help="Timeframe key used in OHLCV filenames (default: 15m).",
    )
    p.add_argument(
        "--lookback",
        type=int,
        default=500,
        help="Number of candles to use for regime fusion (default: 500).",
    )
    p.add_argument(
        "--inertia",
        type=float,
        default=0.6,
        help="Inertia factor in [0,1]; higher = more regime stickiness.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    symbols: List[str] = [s.strip() for s in args.symbols.split(",") if s.strip()]
    
    if not symbols:
        print("Error: No symbols provided", file=sys.stderr)
        return 1
    
    try:
        results = run_regime_fusion_for_universe(
            symbols=symbols,
            timeframe=args.timeframe,
            lookback=args.lookback,
            inertia=args.inertia,
        )
        
        print(f"Regime Fusion V2 completed for {len(symbols)} symbols")
        print(f"Results written to: reports/research/regime_fusion.json")
        
        # Print summary
        print("\nSummary:")
        print("-" * 70)
        for key, data in sorted(results.items()):
            symbol = data.get("symbol", "unknown")
            label = data.get("fused_label", "unknown")
            conf = data.get("fused_confidence", 0.0)
            print(f"{symbol:<10} {label:<12} conf={conf:.3f}")
        
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

