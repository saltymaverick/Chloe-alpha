"""
Signal processor - Phase 1
Processes signals from registry and returns normalized signal vector.
"""

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine_alpha.data.live_prices import get_live_ohlcv
from engine_alpha.signals import signal_fetchers


def _load_registry() -> Dict[str, Any]:
    """Load signal registry from JSON file."""
    registry_path = Path(__file__).parent / "signal_registry.json"
    if not registry_path.exists():
        raise FileNotFoundError(f"Signal registry not found: {registry_path}")
    
    with open(registry_path, "r") as f:
        return json.load(f)


def _normalize_z_tanh(value: float, mean: float = 0.0, std: float = 1.0) -> float:
    """
    Normalize value using z-score then tanh.
    
    Args:
        value: Raw signal value
        mean: Mean for z-score (default: 0.0)
        std: Standard deviation for z-score (default: 1.0)
    
    Returns:
        Normalized value in [-1, 1]
    """
    if std == 0:
        return 0.0
    
    z_score = (value - mean) / std
    # Apply tanh to bound to [-1, 1]
    # Scale z-score by reasonable factor (e.g., 2) for better sensitivity
    return math.tanh(z_score / 2.0)


def _normalize_bounded(value: float, min_val: float, max_val: float, center: Optional[float] = None) -> float:
    """
    Normalize value using bounded mapping.
    
    Maps [min, max] to [-1, 1] with center mapped to 0.
    
    Args:
        value: Raw signal value
        min_val: Minimum value
        max_val: Maximum value
        center: Center value (defaults to midpoint)
    
    Returns:
        Normalized value in [-1, 1]
    """
    if center is None:
        center = (min_val + max_val) / 2.0
    
    # Clamp value to bounds
    value = max(min_val, min(max_val, value))
    
    # Map to [-1, 1]
    if value < center:
        # Map [min, center] to [-1, 0]
        if center == min_val:
            return 0.0
        return -1.0 * (1.0 - (value - min_val) / (center - min_val))
    else:
        # Map [center, max] to [0, 1]
        if center == max_val:
            return 0.0
        return (value - center) / (max_val - center)


def _normalize_signal(raw_value: float, signal_config: Dict[str, Any]) -> float:
    """
    Normalize a signal value based on its configuration.
    
    Args:
        raw_value: Raw signal value
        signal_config: Signal configuration from registry
    
    Returns:
        Normalized value in [-1, 1]
    """
    norm_method = signal_config.get("norm", "z-tanh")
    
    if norm_method == "bounded":
        bounds = signal_config.get("bounds", {})
        min_val = bounds.get("min", 0.0)
        max_val = bounds.get("max", 1.0)
        center = bounds.get("center", (min_val + max_val) / 2.0)
        return _normalize_bounded(raw_value, min_val, max_val, center)
    elif norm_method == "z-tanh":
        # For z-tanh, use a simple heuristic for stub
        # In production, you'd maintain rolling statistics
        # For Phase 1, use a fixed reasonable std based on typical value magnitude
        # Scale by a factor that maps typical ranges to reasonable z-scores
        if abs(raw_value) < 1e-6:
            return 0.0
        # Use a std that's roughly 1/3 of the absolute value for reasonable scaling
        typical_std = max(abs(raw_value) * 0.33, 0.01)
        return _normalize_z_tanh(raw_value, mean=0.0, std=typical_std)
    else:
        # Default: clamp to [-1, 1]
        return max(-1.0, min(1.0, raw_value))


def _build_signal_vector(symbol: str, timeframe: str, ctx: Optional[Dict[str, Any]] = None, ts_override: Optional[str] = None) -> Dict[str, Any]:
    # Load registry
    registry = _load_registry()
    signals = registry.get("signals", [])
    
    # Initialize results
    signal_vector: List[float] = []
    raw_registry: Dict[str, Any] = {}
    
    # Process each signal
    for signal_config in signals:
        signal_name = signal_config["name"]
        source_func_name = signal_config["source"]
        
        # Dynamically call fetcher function
        if hasattr(signal_fetchers, source_func_name):
            fetcher_func = getattr(signal_fetchers, source_func_name)
            try:
                # Call fetcher with symbol and timeframe
                raw_value = fetcher_func(symbol=symbol, timeframe=timeframe)
                
                # Store raw value
                raw_registry[signal_name] = {
                    "value": raw_value,
                    "source": source_func_name,
                    "category": signal_config.get("category", "unknown"),
                    "weight": signal_config.get("weight", 1.0)
                }
                
                # Normalize signal
                normalized_value = _normalize_signal(raw_value, signal_config)
                signal_vector.append(normalized_value)
                
            except Exception as e:
                # On error, use 0.0 as default
                raw_registry[signal_name] = {
                    "value": 0.0,
                    "error": str(e),
                    "source": source_func_name
                }
                signal_vector.append(0.0)
        else:
            # Fetcher function not found
            raw_registry[signal_name] = {
                "value": 0.0,
                "error": f"Fetcher function '{source_func_name}' not found",
                "source": source_func_name
            }
            signal_vector.append(0.0)
    
    ts = ts_override or datetime.now(timezone.utc).isoformat()
    if ctx:
        raw_registry["_ctx"] = ctx
    
    return {
        "signal_vector": signal_vector,
        "raw_registry": raw_registry,
        "ts": ts,
    }


def get_signal_vector(symbol: str = "ETHUSDT", timeframe: str = "1h") -> Dict[str, Any]:
    """
    Generate signal vector via stub fetchers (simulation/testing mode).
    """
    ctx = {
        "symbol": symbol,
        "timeframe": timeframe,
        "mode": "sim",
        "now": datetime.now(timezone.utc).isoformat(),
    }
    return _build_signal_vector(symbol, timeframe, ctx=ctx, ts_override=ctx["now"])


def get_signal_vector_live(symbol: str = "ETHUSDT", timeframe: str = "1h", limit: int = 200) -> Dict[str, Any]:
    """
    Generate signal vector using live OHLCV context (read-only).
    """
    rows = get_live_ohlcv(symbol, timeframe, limit=limit)
    ts = rows[-1]["ts"] if rows else datetime.now(timezone.utc).isoformat()
    ctx = {
        "symbol": symbol,
        "timeframe": timeframe,
        "mode": "live",
        "now": ts,
        "rows_available": len(rows),
        "limit": limit,
    }
    result = _build_signal_vector(symbol, timeframe, ctx=ctx, ts_override=ts)
    result["context"] = ctx
    return result

