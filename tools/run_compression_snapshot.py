#!/usr/bin/env python3
"""
Compression Snapshot Writer
----------------------------

Writes reports/compression_snapshot.json with current compression metrics.
This ensures the packet builder always has fresh compression data.
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


def compute_compression_metrics(rows: list[dict]) -> dict[str, any]:
    """
    Compute compression metrics from OHLCV rows.
    
    Uses same logic as live loop: ATR ratio and BB ratio.
    
    Args:
        rows: List of OHLCV dicts
    
    Returns:
        Dict with compression_score, atr_ratio, bb_ratio, etc.
    """
    if not rows or len(rows) < 20:
        return {
            "compression_score": None,
            "is_compressed": False,
            "atr_ratio": None,
            "bb_ratio": None,
            "error": "insufficient_data",
        }
    
    try:
        # Extract closes, highs, lows
        closes = [float(r.get("close", 0)) for r in rows if r.get("close")]
        highs = [float(r.get("high", 0)) for r in rows if r.get("high")] if rows[0].get("high") else None
        lows = [float(r.get("low", 0)) for r in rows if r.get("low")] if rows[0].get("low") else None
        
        if not closes or len(closes) < 20:
            return {
                "compression_score": None,
                "is_compressed": False,
                "atr_ratio": None,
                "bb_ratio": None,
                "error": "insufficient_closes",
            }
        
        # Compute ATR (simplified - use recent vs historical)
        def compute_atr(h_list, l_list, c_list, period):
            if not h_list or not l_list or len(c_list) < period + 1:
                return None
            trs = []
            for i in range(max(1, len(c_list) - period), len(c_list)):
                tr = max(
                    h_list[i] - l_list[i] if i < len(h_list) and i < len(l_list) else 0,
                    abs(c_list[i] - c_list[i-1]) if i > 0 else 0,
                )
                trs.append(tr)
            return sum(trs) / len(trs) if trs else None
        
        # Current ATR (last 14 bars)
        current_atr = compute_atr(highs, lows, closes, 14) if highs and lows else None
        
        # Historical ATR (bars 15-28, or use earlier period if available)
        hist_atr = None
        if len(closes) >= 28 and highs and lows:
            hist_highs = highs[-28:-14] if len(highs) >= 28 else None
            hist_lows = lows[-28:-14] if len(lows) >= 28 else None
            hist_closes = closes[-28:-14]
            hist_atr = compute_atr(hist_highs, hist_lows, hist_closes, 14) if hist_highs and hist_lows else None
        elif len(closes) >= 20 and highs and lows:
            # Fallback: use first half vs second half
            mid = len(closes) // 2
            hist_highs = highs[:mid] if len(highs) >= mid else None
            hist_lows = lows[:mid] if len(lows) >= mid else None
            hist_closes = closes[:mid]
            hist_atr = compute_atr(hist_highs, hist_lows, hist_closes, min(14, len(hist_closes) - 1)) if hist_highs and hist_lows else None
        
        # ATR ratio
        atr_ratio = (current_atr / hist_atr) if (current_atr and hist_atr and hist_atr > 0) else None
        
        # BB ratio (simplified - use std dev of closes)
        if len(closes) >= 20:
            recent_closes = closes[-20:]
            mean_close = sum(recent_closes) / len(recent_closes)
            std_close = (sum((c - mean_close) ** 2 for c in recent_closes) / len(recent_closes)) ** 0.5
            bb_ratio = (std_close / mean_close) if mean_close > 0 else None
        else:
            bb_ratio = None
        
        # Compression score (lower = more compressed)
        # Simplified: combine ATR and BB ratios
        compression_score = None
        if bb_ratio is not None:
            if atr_ratio is not None:
                # Normalize both to 0-1 range (rough approximation)
                atr_norm = min(1.0, max(0.0, atr_ratio / 2.0))  # Assume 2.0 is "high"
                bb_norm = min(1.0, max(0.0, bb_ratio * 100))  # Assume 0.01 is "high"
                compression_score = (atr_norm + bb_norm) / 2.0
            else:
                # Fallback: use BB ratio only (normalized)
                bb_norm = min(1.0, max(0.0, bb_ratio * 100))
                compression_score = bb_norm
        
        is_compressed = compression_score is not None and compression_score < 0.3
        
        return {
            "compression_score": compression_score,
            "is_compressed": is_compressed,
            "atr_ratio": atr_ratio,
            "bb_ratio": bb_ratio,
        }
    
    except Exception as e:
        return {
            "compression_score": None,
            "is_compressed": False,
            "atr_ratio": None,
            "bb_ratio": None,
            "error": str(e),
        }


def compute_compression_snapshot(symbol: str = "ETHUSDT", timeframe: str = "15m") -> dict[str, any]:
    """
    Compute compression snapshot from current OHLCV data.
    
    Args:
        symbol: Trading symbol (default: ETHUSDT)
        timeframe: Timeframe (default: 15m)
    
    Returns:
        Dict with compression metrics and metadata
    """
    now = datetime.now(timezone.utc)
    
    # Get OHLCV data
    try:
        rows, ohlcv_meta = get_live_ohlcv(symbol, timeframe, limit=100)
        
        metrics = compute_compression_metrics(rows)
        
        return {
            **metrics,
            "symbol": symbol,
            "timeframe": timeframe,
            "source": "ohlcv_computation",
            "generated_at": now.isoformat(),
        }
    
    except Exception as e:
        return {
            "compression_score": None,
            "is_compressed": False,
            "atr_ratio": None,
            "bb_ratio": None,
            "symbol": symbol,
            "timeframe": timeframe,
            "source": f"error: {str(e)}",
            "generated_at": now.isoformat(),
        }


def main() -> int:
    """Main entry point."""
    result = compute_compression_snapshot()
    
    # Write to reports/compression_snapshot.json
    output_path = REPORTS / "compression_snapshot.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    
    score_str = f"{result.get('compression_score'):.3f}" if result.get('compression_score') is not None else "None"
    print(f"Compression snapshot: score={score_str}, compressed={result.get('is_compressed')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

