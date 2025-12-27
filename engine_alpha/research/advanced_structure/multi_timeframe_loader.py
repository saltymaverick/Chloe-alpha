"""
Multi-Timeframe OHLCV Loader - Shared loader for ASE engines.

Loads 5m, 15m, and 1h OHLCV data for a symbol with consistent indexing.
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional
from pathlib import Path

from engine_alpha.data.live_prices import get_live_ohlcv
from engine_alpha.data.historical_prices import load_ohlcv_csv


def load_all_timeframes(
    symbol: str,
    max_bars_5m: int = 1000,
    max_bars_15m: int = 500,
    max_bars_1h: int = 200,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Load OHLCV data for 5m, 15m, and 1h timeframes.
    
    Args:
        symbol: Symbol ID (e.g., "ETHUSDT")
        max_bars_5m: Maximum bars for 5m timeframe
        max_bars_15m: Maximum bars for 15m timeframe
        max_bars_1h: Maximum bars for 1h timeframe
    
    Returns:
        {
            "5m": List[Dict[str, Any]],  # OHLCV candles
            "15m": List[Dict[str, Any]],
            "1h": List[Dict[str, Any]],
        }
    """
    result: Dict[str, List[Dict[str, Any]]] = {
        "5m": [],
        "15m": [],
        "1h": [],
    }
    
    # Load each timeframe
    for tf, max_bars in [("5m", max_bars_5m), ("15m", max_bars_15m), ("1h", max_bars_1h)]:
        candles: List[Dict[str, Any]] = []
        
        # Try live OHLCV first
        try:
            live_candles = get_live_ohlcv(symbol, tf, limit=max_bars)
            if live_candles and isinstance(live_candles, list):
                candles = live_candles[-max_bars:]  # Take last N bars
        except Exception:
            pass
        
        # Fallback: try historical CSV
        if not candles:
            try:
                csv_candles = load_ohlcv_csv(symbol, tf)
                if csv_candles:
                    candles = csv_candles[-max_bars:]
            except Exception:
                pass
        
        result[tf] = candles
    
    return result

