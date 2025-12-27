"""
Volume Imbalance Engine - Computes delta, absorption, and exhaustion signals.

Analyzes OHLCV data to detect:
- Delta approximation (buy/sell volume imbalance)
- Absorption (large wick + opposite delta)
- Exhaustion (high volume + small body)
- CVD-style trend (cumulative volume delta)
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from collections import defaultdict

from engine_alpha.research.advanced_structure.multi_timeframe_loader import load_all_timeframes


def _compute_delta_approximation(candle: Dict[str, Any]) -> Dict[str, float]:
    """
    Approximate delta and buy/sell volume for a single candle.
    
    Args:
        candle: OHLCV candle dict
    
    Returns:
        {
            "delta": float,
            "buy_volume": float,
            "sell_volume": float,
            "imbalance": float,  # normalized imbalance
        }
    """
    open_price = float(candle.get("open", 0))
    close_price = float(candle.get("close", 0))
    volume = float(candle.get("volume", 0))
    
    if volume <= 0:
        return {
            "delta": 0.0,
            "buy_volume": 0.0,
            "sell_volume": 0.0,
            "imbalance": 0.0,
        }
    
    # Price change
    price_change = close_price - open_price
    
    # Delta approximation: price_change * volume
    delta = price_change * volume
    
    # Approximate buy/sell volume
    buy_volume = max(delta, 0.0)
    sell_volume = max(-delta, 0.0)
    
    # Normalized imbalance
    eps = 1e-12
    imbalance = (buy_volume - sell_volume) / max(volume, eps)
    
    return {
        "delta": delta,
        "buy_volume": buy_volume,
        "sell_volume": sell_volume,
        "imbalance": imbalance,
    }


def _detect_absorption(candle: Dict[str, Any], delta_info: Dict[str, float]) -> Optional[str]:
    """
    Detect absorption: large wick in one direction + delta in opposite direction.
    
    Returns:
        "bullish", "bearish", or None
    """
    open_price = float(candle.get("open", 0))
    high_price = float(candle.get("high", 0))
    low_price = float(candle.get("low", 0))
    close_price = float(candle.get("close", 0))
    
    range_size = high_price - low_price
    if range_size <= 0:
        return None
    
    body = abs(close_price - open_price)
    upper_wick = high_price - max(open_price, close_price)
    lower_wick = min(open_price, close_price) - low_price
    
    # Wick ratios
    upper_wick_ratio = upper_wick / range_size
    lower_wick_ratio = lower_wick / range_size
    
    delta = delta_info.get("delta", 0.0)
    
    # Bearish absorption: large upper wick + negative delta
    if upper_wick_ratio > 0.4 and delta < 0:
        return "bearish"
    
    # Bullish absorption: large lower wick + positive delta
    if lower_wick_ratio > 0.4 and delta > 0:
        return "bullish"
    
    return None


def _detect_exhaustion(candle: Dict[str, Any], rolling_volume_mean: float) -> bool:
    """
    Detect exhaustion: high volume + small body relative to range.
    
    Args:
        candle: OHLCV candle dict
        rolling_volume_mean: Rolling average volume for comparison
    
    Returns:
        True if exhaustion detected
    """
    if rolling_volume_mean <= 0:
        return False
    
    open_price = float(candle.get("open", 0))
    high_price = float(candle.get("high", 0))
    low_price = float(candle.get("low", 0))
    close_price = float(candle.get("close", 0))
    volume = float(candle.get("volume", 0))
    
    range_size = high_price - low_price
    if range_size <= 0:
        return False
    
    body = abs(close_price - open_price)
    body_ratio = body / range_size
    
    # Exhaustion: volume > 2x rolling mean AND body <= 0.25 of range
    volume_spike = volume > (2.0 * rolling_volume_mean)
    small_body = body_ratio <= 0.25
    
    return volume_spike and small_body


def _compute_cvd_trend(deltas: List[float], threshold: float = 0.1) -> str:
    """
    Compute CVD-style trend from cumulative delta.
    
    Args:
        deltas: List of delta values
        threshold: Threshold for trend classification
    
    Returns:
        "bullish", "bearish", or "neutral"
    """
    if not deltas:
        return "neutral"
    
    cumulative_delta = sum(deltas)
    
    # Normalize by number of candles
    avg_delta = cumulative_delta / len(deltas) if deltas else 0.0
    
    if avg_delta > threshold:
        return "bullish"
    elif avg_delta < -threshold:
        return "bearish"
    else:
        return "neutral"


def compute_volume_imbalance(
    symbol: str,
    lookback: int = 20,
) -> Dict[str, Dict[str, Any]]:
    """
    Compute volume imbalance metrics for a symbol.
    
    Args:
        symbol: Symbol ID (e.g., "ETHUSDT")
        lookback: Number of recent candles to analyze
    
    Returns:
        {
            "ETHUSDT": {
                "delta_5m": float or None,
                "delta_15m": float or None,
                "delta_1h": float or None,
                "avg_imbalance": float or None,
                "imbalance_strength": float (0.0-1.0),
                "absorption_count": int,
                "exhaustion_count": int,
                "cvd_trend": str,
                "notes": List[str],
            },
            ...
        }
    """
    result: Dict[str, Dict[str, Any]] = {}
    
    try:
        # Load multi-timeframe data
        tf_data = load_all_timeframes(symbol, max_bars_5m=500, max_bars_15m=300, max_bars_1h=100)
        
        candles_5m = tf_data.get("5m", [])
        candles_15m = tf_data.get("15m", [])
        candles_1h = tf_data.get("1h", [])
        
        # Use 15m as primary timeframe (most reliable)
        primary_candles = candles_15m if candles_15m else (candles_5m if candles_5m else candles_1h)
        
        if not primary_candles or len(primary_candles) < lookback:
            result[symbol] = {
                "delta_5m": None,
                "delta_15m": None,
                "delta_1h": None,
                "avg_imbalance": None,
                "imbalance_strength": 0.0,
                "absorption_count": 0,
                "exhaustion_count": 0,
                "cvd_trend": "neutral",
                "notes": ["Insufficient volume history"],
            }
            return result
        
        # Analyze primary timeframe (15m)
        recent = primary_candles[-lookback:]
        
        # Compute deltas and imbalances
        deltas: List[float] = []
        imbalances: List[float] = []
        absorption_count = 0
        exhaustion_count = 0
        
        # Compute rolling volume mean
        volumes = [float(c.get("volume", 0)) for c in recent]
        rolling_volume_mean = sum(volumes) / len(volumes) if volumes else 0.0
        
        for candle in recent:
            delta_info = _compute_delta_approximation(candle)
            deltas.append(delta_info["delta"])
            imbalances.append(delta_info["imbalance"])
            
            # Detect absorption
            absorption = _detect_absorption(candle, delta_info)
            if absorption:
                absorption_count += 1
            
            # Detect exhaustion
            if _detect_exhaustion(candle, rolling_volume_mean):
                exhaustion_count += 1
        
        # Aggregate metrics
        avg_imbalance = sum(imbalances) / len(imbalances) if imbalances else 0.0
        imbalance_strength_raw = abs(avg_imbalance)
        imbalance_strength = max(0.0, min(1.0, imbalance_strength_raw))  # Clamp to [0, 1]
        
        # CVD trend
        cvd_trend = _compute_cvd_trend(deltas, threshold=0.1)
        
        # Compute delta for other timeframes if available
        delta_5m = None
        delta_15m = None
        delta_1h = None
        
        if candles_5m and len(candles_5m) >= lookback:
            recent_5m = candles_5m[-lookback:]
            deltas_5m = [_compute_delta_approximation(c)["delta"] for c in recent_5m]
            delta_5m = sum(deltas_5m) / len(deltas_5m) if deltas_5m else 0.0
        
        if candles_15m and len(candles_15m) >= lookback:
            recent_15m = candles_15m[-lookback:]
            deltas_15m = [_compute_delta_approximation(c)["delta"] for c in recent_15m]
            delta_15m = sum(deltas_15m) / len(deltas_15m) if deltas_15m else 0.0
        
        if candles_1h and len(candles_1h) >= lookback:
            recent_1h = candles_1h[-lookback:]
            deltas_1h = [_compute_delta_approximation(c)["delta"] for c in recent_1h]
            delta_1h = sum(deltas_1h) / len(deltas_1h) if deltas_1h else 0.0
        
        # Build notes
        notes: List[str] = []
        if avg_imbalance > 0.1:
            notes.append(f"Bullish imbalance cluster (avg_imbalance={avg_imbalance:.2f})")
        elif avg_imbalance < -0.1:
            notes.append(f"Bearish imbalance cluster (avg_imbalance={avg_imbalance:.2f})")
        
        if cvd_trend != "neutral":
            notes.append(f"CVD {cvd_trend} trend over last {lookback} bars")
        
        if absorption_count > 0:
            notes.append(f"{absorption_count} absorption candle(s) detected")
        
        if exhaustion_count > 0:
            notes.append(f"{exhaustion_count} exhaustion candle(s) detected")
        
        if not notes:
            notes = ["Neutral volume profile"]
        
        result[symbol] = {
            "delta_5m": round(delta_5m, 4) if delta_5m is not None else None,
            "delta_15m": round(delta_15m, 4) if delta_15m is not None else None,
            "delta_1h": round(delta_1h, 4) if delta_1h is not None else None,
            "avg_imbalance": round(avg_imbalance, 4),
            "imbalance_strength": round(imbalance_strength, 2),
            "absorption_count": absorption_count,
            "exhaustion_count": exhaustion_count,
            "cvd_trend": cvd_trend,
            "notes": notes,
        }
        
    except Exception as e:
        result[symbol] = {
            "delta_5m": None,
            "delta_15m": None,
            "delta_1h": None,
            "avg_imbalance": None,
            "imbalance_strength": 0.0,
            "absorption_count": 0,
            "exhaustion_count": 0,
            "cvd_trend": "neutral",
            "notes": [f"Error: {str(e)}"],
        }
    
    return result


def run_volume_imbalance_scan() -> Dict[str, Dict[str, Any]]:
    """
    Computes per-symbol volume imbalance metrics and writes them
    to reports/research/volume_imbalance.json
    
    Returns:
        Dict mapping symbol to volume imbalance data
    """
    from engine_alpha.core.paths import REPORTS
    from pathlib import Path
    import json
    from datetime import datetime, timezone
    
    RESEARCH_DIR = REPORTS / "research"
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    
    OUTPUT_PATH = RESEARCH_DIR / "volume_imbalance.json"
    
    # Get enabled symbols (use same pattern as other research modules)
    try:
        from tools.intel_dashboard import load_symbol_registry
        symbols = load_symbol_registry()
    except Exception:
        # Fallback to common symbols
        symbols = [
            "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "AVAXUSDT",
            "LINKUSDT", "DOTUSDT", "ADAUSDT", "ATOMUSDT", "XRPUSDT", "DOGEUSDT"
        ]
    
    if not symbols:
        # Final fallback
        symbols = [
            "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "AVAXUSDT",
            "LINKUSDT", "DOTUSDT", "ADAUSDT", "ATOMUSDT", "XRPUSDT", "DOGEUSDT"
        ]
    
    # Compute for each symbol
    all_results: Dict[str, Dict[str, Any]] = {}
    
    for symbol in symbols:
        try:
            symbol_result = compute_volume_imbalance(symbol, lookback=20)
            all_results.update(symbol_result)
        except Exception as e:
            # Continue on error, add empty entry
            all_results[symbol] = {
                "delta_5m": None,
                "delta_15m": None,
                "delta_1h": None,
                "avg_imbalance": None,
                "imbalance_strength": 0.0,
                "absorption_count": 0,
                "exhaustion_count": 0,
                "cvd_trend": "neutral",
                "notes": [f"Error processing {symbol}: {str(e)}"],
            }
    
    # Normalize output structure and compute health
    normalized_results: Dict[str, Dict[str, Any]] = {}
    for symbol, data in all_results.items():
        normalized_results[symbol] = {
            "avg_imbalance": data.get("avg_imbalance", 0.0) if data.get("avg_imbalance") is not None else 0.0,
            "strength": max(0.0, min(1.0, data.get("imbalance_strength", 0.0))),  # Clamp to [0, 1]
            "cvd_trend": data.get("cvd_trend", "neutral"),
            "absorb_count": data.get("absorption_count", 0),
            "exhaust_count": data.get("exhaustion_count", 0),
        }
    
    # Compute health
    health_status = "ok"
    health_reasons = []
    
    all_strengths_zero = all(r.get("strength", 0.0) < 0.01 for r in normalized_results.values())
    all_neutral = all(r.get("cvd_trend", "neutral") == "neutral" for r in normalized_results.values())
    
    if all_strengths_zero and all_neutral and len(normalized_results) > 0:
        health_status = "degraded"
        health_reasons.append("no_significant_imbalance_detected")
    
    # Write output
    output_data = {
        "version": "v2.1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "health": {
            "status": health_status,
            "reasons": health_reasons,
        },
        "symbols": normalized_results,
    }
    
    try:
        OUTPUT_PATH.write_text(json.dumps(output_data, indent=2))
    except Exception as e:
        print(f"Warning: Failed to write volume_imbalance.json: {e}")
    
    return normalized_results

