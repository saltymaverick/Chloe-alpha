#!/usr/bin/env python3
"""
Regime Snapshot Writer
-----------------------

Writes reports/regime_snapshot.json with current regime classification.
This ensures the packet builder always has fresh regime data.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.core.paths import REPORTS
from engine_alpha.data.live_prices import get_live_ohlcv
from engine_alpha.core.regime import classify_regime_simple


def compute_regime_snapshot(symbol: str = "ETHUSDT", timeframe: str = "15m") -> dict[str, any]:
    """
    Compute regime snapshot from current OHLCV data.
    
    Args:
        symbol: Trading symbol (default: ETHUSDT)
        timeframe: Timeframe (default: 15m)
    
    Returns:
        Dict with regime, symbol, timeframe, and metadata
    """
    now = datetime.now(timezone.utc)
    
    # Get OHLCV data
    try:
        rows, ohlcv_meta = get_live_ohlcv(symbol, timeframe, limit=100)
        
        if not rows or len(rows) < 20:
            return {
                "regime": "unknown",
                "symbol": symbol,
                "timeframe": timeframe,
                "source": "insufficient_data",
                "generated_at": now.isoformat(),
            }
        
        # Extract closes, highs, lows
        closes = [float(r.get("close", 0)) for r in rows if r.get("close")]
        highs = [float(r.get("high", 0)) for r in rows if r.get("high")] if rows[0].get("high") else None
        lows = [float(r.get("low", 0)) for r in rows if r.get("low")] if rows[0].get("low") else None
        
        if not closes or len(closes) < 20:
            return {
                "regime": "unknown",
                "symbol": symbol,
                "timeframe": timeframe,
                "source": "insufficient_closes",
                "generated_at": now.isoformat(),
            }
        
        # Classify regime
        regime = classify_regime_simple(closes, highs, lows)
        
        return {
            "regime": regime,
            "symbol": symbol,
            "timeframe": timeframe,
            "source": "ohlcv_classifier",
            "generated_at": now.isoformat(),
        }
    
    except Exception as e:
        return {
            "regime": "unknown",
            "symbol": symbol,
            "timeframe": timeframe,
            "source": f"error: {str(e)}",
            "generated_at": now.isoformat(),
        }


def main() -> int:
    """Main entry point."""
    result = compute_regime_snapshot()
    
    # Write to reports/regime_snapshot.json
    output_path = REPORTS / "regime_snapshot.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    
    print(f"Regime snapshot: regime={result.get('regime')}, symbol={result.get('symbol')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

