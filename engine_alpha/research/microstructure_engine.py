"""
Microstructure Engine v1 - Bar-level microstructure feature extraction.

Computes bar-level features from OHLCV data to classify microstructure regimes:
- clean_trend: Strong directional movement with small wicks
- noisy: Large wicks relative to body, indicating indecision
- reversal_hint: Extreme wick imbalance suggesting potential reversal
- indecision: Very small body, indicating market uncertainty

All outputs are advisory-only and research-oriented.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

try:
    import numpy as np
except ImportError:
    np = None

from engine_alpha.core.paths import REPORTS, DATA
from engine_alpha.data.live_prices import get_live_ohlcv
from engine_alpha.data.historical_prices import load_ohlcv_csv

RESEARCH_DIR = REPORTS / "research"
MICROSTRUCTURE_SNAPSHOT_PATH = RESEARCH_DIR / "microstructure_snapshot_15m.json"


def _compute_bar_features(candle: Dict[str, Any], prev_close: Optional[float] = None) -> Dict[str, Any]:
    """
    Compute microstructure features for a single bar.
    
    Args:
        candle: Dict with open, high, low, close, volume
        prev_close: Previous bar's close price (for momentum/gap)
    
    Returns:
        Dict with microstructure features
    """
    open_price = float(candle.get("open", 0))
    high_price = float(candle.get("high", 0))
    low_price = float(candle.get("low", 0))
    close_price = float(candle.get("close", 0))
    
    # Basic bar geometry
    body = abs(close_price - open_price)
    range_size = high_price - low_price
    upper_wick = high_price - max(open_price, close_price)
    lower_wick = min(open_price, close_price) - low_price
    
    # Ratios (avoid division by zero)
    eps = 1e-12
    body_ratio = body / (range_size + eps)
    upper_wick_ratio = upper_wick / (range_size + eps)
    lower_wick_ratio = lower_wick / (range_size + eps)
    
    # Volatility (normalized range)
    volatility = None
    if prev_close and prev_close > 0:
        volatility = range_size / prev_close
    
    # Momentum and gap
    momentum = None
    gap = None
    if prev_close and prev_close > 0:
        momentum = (close_price - prev_close) / prev_close
        gap = (open_price - prev_close) / prev_close
    
    # Wick imbalance
    wick_imbalance = upper_wick_ratio - lower_wick_ratio
    
    # Trend direction
    if close_price > open_price:
        trend_bar = 1
    elif close_price < open_price:
        trend_bar = -1
    else:
        trend_bar = 0
    
    # Classify micro regime
    micro_regime = _classify_micro_regime(
        body_ratio, upper_wick_ratio, lower_wick_ratio, wick_imbalance, trend_bar
    )
    
    return {
        "body": body,
        "range": range_size,
        "upper_wick": upper_wick,
        "lower_wick": lower_wick,
        "body_ratio": body_ratio,
        "upper_wick_ratio": upper_wick_ratio,
        "lower_wick_ratio": lower_wick_ratio,
        "volatility": volatility,
        "momentum": momentum,
        "gap": gap,
        "wick_imbalance": wick_imbalance,
        "trend_bar": trend_bar,
        "micro_regime": micro_regime,
    }


def _classify_micro_regime_v2(
    avg_body_ratio: Optional[float],
    noise_score: Optional[float],
    trend_slope: Optional[float],
    trend_fit_r2: Optional[float],
    compression_score: Optional[float],
    expansion_score: Optional[float],
    regimes: List[str],
) -> str:
    """
    Classify micro regime using v2 features (improved classification).
    
    Args:
        avg_body_ratio: Average body ratio
        noise_score: Noise score (0-1)
        trend_slope: Trend slope from linear fit
        trend_fit_r2: R² of trend fit
        compression_score: ATR compression score
        expansion_score: ATR expansion score
        regimes: List of bar-level regimes (for fallback)
    
    Returns:
        One of: "clean_trend", "weak_trend", "indecision", "noisy"
    """
    # Fallback to dominant regime if v2 features unavailable
    if avg_body_ratio is None and noise_score is None:
        regime_counts = {}
        for r in regimes:
            regime_counts[r] = regime_counts.get(r, 0) + 1
        if regime_counts:
            return max(regime_counts.items(), key=lambda x: x[1])[0]
        return "unknown"
    
    # Use v2 features for classification
    body_ratio_val = avg_body_ratio if avg_body_ratio is not None else 0.5
    noise_val = noise_score if noise_score is not None else 0.5
    slope_abs = abs(trend_slope) if trend_slope is not None else 0.0
    r2_val = trend_fit_r2 if trend_fit_r2 is not None else 0.0
    
    # Clean trend: high slope, high R², low noise, high body_ratio
    if slope_abs > 0.001 and r2_val > 0.6 and noise_val < 0.4 and body_ratio_val > 0.5:
        return "clean_trend"
    
    # Weak trend: medium slope, medium R²
    if slope_abs > 0.0005 and r2_val > 0.3:
        return "weak_trend"
    
    # Indecision: high noise, low slope, low R²
    if noise_val > 0.6 and (slope_abs < 0.0005 or r2_val < 0.3):
        return "indecision"
    
    # Noisy: high noise score
    if noise_val > 0.5:
        return "noisy"
    
    # Default based on body_ratio
    if body_ratio_val > 0.4:
        return "clean_trend"
    else:
        return "indecision"


def _classify_micro_regime(
    body_ratio: float,
    upper_wick_ratio: float,
    lower_wick_ratio: float,
    wick_imbalance: float,
    trend_bar: int,
) -> str:
    """
    Classify bar into micro regime based on geometry.
    
    Returns:
        One of: "clean_trend", "noisy", "reversal_hint", "indecision"
    """
    # Indecision: very small body
    if body_ratio < 0.2:
        return "indecision"
    
    # Clean trend: high body ratio, small wicks
    if body_ratio > 0.6 and (upper_wick_ratio + lower_wick_ratio) < 0.3:
        return "clean_trend"
    
    # Reversal hint: extreme wick imbalance
    # Large upper wick in uptrend or large lower wick in downtrend
    if trend_bar > 0 and upper_wick_ratio > 0.5:
        return "reversal_hint"
    if trend_bar < 0 and lower_wick_ratio > 0.5:
        return "reversal_hint"
    
    # Noisy: large wicks relative to body
    if (upper_wick_ratio + lower_wick_ratio) > 0.5:
        return "noisy"
    
    # Default: clean_trend if body is dominant, otherwise noisy
    if body_ratio > 0.4:
        return "clean_trend"
    else:
        return "noisy"


def load_ohlcv_for_symbol(
    symbol: str,
    timeframe: str = "15m",
    max_bars: int = 500,
) -> List[Dict[str, Any]]:
    """
    Load OHLCV data for a symbol using the same loaders as ARE.
    
    Tries:
    1. Live OHLCV from exchanges (via get_live_ohlcv)
    2. Historical CSV files (via load_ohlcv_csv)
    
    Args:
        symbol: Symbol ID (e.g., "ETHUSDT")
        timeframe: Timeframe (default: "15m")
        max_bars: Maximum number of bars to return
    
    Returns:
        List of OHLCV candles (dicts with ts, open, high, low, close, volume)
    """
    candles: List[Dict[str, Any]] = []
    
    # Try live OHLCV first (returns list of dicts, not DataFrame)
    try:
        live_candles = get_live_ohlcv(symbol, timeframe, limit=max_bars)
        if live_candles and isinstance(live_candles, list):
            candles = live_candles[-max_bars:]  # Take last N bars
            if candles:
                return candles
    except Exception:
        pass
    
    # Fallback: try historical CSV
    try:
        csv_candles = load_ohlcv_csv(symbol, timeframe)
        if csv_candles:
            candles = csv_candles[-max_bars:]  # Take last N bars
            if candles:
                return candles
    except Exception:
        pass
    
    return candles


def compute_microstructure_for_symbol(
    symbol: str,
    timeframe: str = "15m",
    max_bars: int = 500,
) -> Dict[str, Dict[str, Any]]:
    """
    Compute microstructure features for a symbol.
    
    Args:
        symbol: Symbol ID (e.g., "ETHUSDT")
        timeframe: Timeframe (default: "15m")
        max_bars: Maximum number of bars to process (default: 500)
    
    Returns:
        Dict mapping timestamp -> microstructure features
    """
    features_by_ts: Dict[str, Dict[str, Any]] = {}
    
    # Load OHLCV data
    candles = load_ohlcv_for_symbol(symbol, timeframe, max_bars)
    
    if not candles:
        return features_by_ts
    
    # Sort by timestamp (ensure chronological order)
    candles.sort(key=lambda c: c.get("ts", ""))
    
    # Compute features for each bar
    prev_close = None
    for candle in candles:
        features = _compute_bar_features(candle, prev_close)
        ts = candle.get("ts", "")
        if ts:
            features_by_ts[ts] = features
            prev_close = float(candle.get("close", 0))
    
    return features_by_ts


def _compute_summary_metrics(
    features_by_ts: Dict[str, Dict[str, Any]],
    candles: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Compute summary microstructure metrics from bar-level features (v2).
    
    Args:
        features_by_ts: Dict mapping timestamp -> bar features
        candles: List of OHLCV candles (for close prices)
    
    Returns:
        Dict with summary metrics and dominant micro_regime (v2 enhanced)
    """
    if not features_by_ts or not candles:
        return {
            "micro_regime": "unknown",
            "metrics": {
                "spread": None,
                "wick_ratio": None,
                "volatility": None,
                "body_ratio": None,
                # v2 fields
                "noise_score": None,
                "compression_score": None,
                "expansion_score": None,
                "trend_slope": None,
                "trend_fit_r2": None,
                "delta_body_vs_volume": None,
            },
        }
    
    # Create a lookup for close prices by timestamp
    close_by_ts = {}
    for candle in candles:
        ts = candle.get("ts", "")
        if ts:
            close_by_ts[ts] = float(candle.get("close", 0.0))
    
    # Extract recent bars (last 100, or all if fewer)
    timestamps = sorted(features_by_ts.keys())
    recent_bars = timestamps[-100:] if len(timestamps) > 100 else timestamps
    
    if not recent_bars:
        return {
            "micro_regime": "unknown",
            "metrics": {
                "spread": None,
                "wick_ratio": None,
                "volatility": None,
                "body_ratio": None,
                # v2 fields
                "noise_score": None,
                "compression_score": None,
                "expansion_score": None,
                "trend_slope": None,
                "trend_fit_r2": None,
                "delta_body_vs_volume": None,
            },
        }
    
    # Collect metrics
    spreads = []
    wick_ratios = []
    volatilities = []
    body_ratios = []
    regimes = []
    
    # v2: Collect wick lengths and body sizes for wick_ratio calculation
    wick_lengths = []
    body_sizes = []
    
    # v2: Collect ranges for ATR calculation
    ranges = []
    
    # v2: Collect close prices for trend fitting
    close_prices = []
    time_indices = []
    
    # v2: Collect body sizes and volumes for delta_body_vs_volume
    body_volumes = []
    volumes = []
    
    for idx, ts in enumerate(recent_bars):
        features = features_by_ts.get(ts, {})
        
        # Spread = (high - low) / close (from bar geometry)
        range_size = features.get("range", 0.0)
        close_price = close_by_ts.get(ts, 0.0)
        if close_price > 0:
            spread = range_size / close_price
            spreads.append(spread)
            ranges.append(range_size)
            close_prices.append(close_price)
            time_indices.append(idx)
        
        # Wick ratio = upper_wick / (lower_wick + eps) - old calculation
        upper_wick = features.get("upper_wick", 0.0)
        lower_wick = features.get("lower_wick", 0.0)
        if lower_wick > 0 or upper_wick > 0:
            wick_ratio = upper_wick / (lower_wick + 1e-9)
            wick_ratios.append(wick_ratio)
        
        # v2: Collect wick lengths and body sizes
        total_wick = upper_wick + lower_wick
        body_size = features.get("body", 0.0)
        if body_size > 0:
            wick_lengths.append(total_wick)
            body_sizes.append(body_size)
        
        # v2: Collect volume for delta_body_vs_volume
        candle = next((c for c in candles if c.get("ts") == ts), None)
        if candle:
            volume = float(candle.get("volume", 0.0))
            if volume > 0 and body_size > 0:
                body_volumes.append(body_size)
                volumes.append(volume)
        
        # Volatility and body_ratio from features
        vol = features.get("volatility")
        if vol is not None:
            volatilities.append(vol)
        
        body_ratio = features.get("body_ratio")
        if body_ratio is not None:
            body_ratios.append(body_ratio)
        
        regime = features.get("micro_regime")
        if regime:
            regimes.append(regime)
    
    # Compute averages (existing v1 metrics)
    avg_spread = sum(spreads) / len(spreads) if spreads else None
    avg_wick_ratio = sum(wick_ratios) / len(wick_ratios) if wick_ratios else None
    avg_volatility = sum(volatilities) / len(volatilities) if volatilities else None
    avg_body_ratio = sum(body_ratios) / len(body_ratios) if body_ratios else None
    
    # v2: Compute wick_ratio (avg wick length vs body)
    avg_wick_length = sum(wick_lengths) / len(wick_lengths) if wick_lengths else 0.0
    avg_body_size = sum(body_sizes) / len(body_sizes) if body_sizes else 0.0
    wick_ratio_v2 = (avg_wick_length / (avg_body_size + 1e-9)) if avg_body_size > 0 else None
    
    # v2: Compute noise_score (0-1, where 1 = very noisy)
    # Based on wick-to-body ratio and body_ratio variability
    noise_score = None
    if body_ratios and len(body_ratios) > 1:
        # High noise if low avg body_ratio OR high variability in body_ratio
        avg_body_ratio_val = avg_body_ratio if avg_body_ratio is not None else 0.5
        body_ratio_std = math.sqrt(sum((br - avg_body_ratio_val) ** 2 for br in body_ratios) / len(body_ratios)) if len(body_ratios) > 1 else 0.0
        # Noise increases as body_ratio decreases and variability increases
        noise_score = min(1.0, (1.0 - avg_body_ratio_val) * 0.7 + body_ratio_std * 0.3)
    
    # v2: Compute compression/expansion scores (ATR-based)
    compression_score = None
    expansion_score = None
    if ranges and len(ranges) >= 20:
        # Short-term ATR (last 10 bars)
        short_atr = sum(ranges[-10:]) / min(10, len(ranges))
        # Medium-term ATR (last 20 bars)
        medium_atr = sum(ranges[-20:]) / min(20, len(ranges))
        # Long-term ATR (all bars)
        long_atr = sum(ranges) / len(ranges)
        
        # Compression: short ATR < medium ATR
        if medium_atr > 0:
            compression_score = max(0.0, 1.0 - (short_atr / medium_atr))
        
        # Expansion: recent ATR / long ATR
        if long_atr > 0:
            expansion_score = min(1.0, short_atr / long_atr)
    
    # v2: Compute delta_body_vs_volume (correlation or qualitative relationship)
    delta_body_vs_volume = None
    if body_volumes and volumes and len(body_volumes) >= 10 and np is not None:
        try:
            # Compute correlation between body size and volume
            body_arr = np.array(body_volumes)
            vol_arr = np.array(volumes)
            # Normalize both arrays
            body_norm = (body_arr - np.mean(body_arr)) / (np.std(body_arr) + 1e-9)
            vol_norm = (vol_arr - np.mean(vol_arr)) / (np.std(vol_arr) + 1e-9)
            # Correlation coefficient
            correlation = np.corrcoef(body_norm, vol_norm)[0, 1]
            delta_body_vs_volume = float(correlation) if not np.isnan(correlation) else None
        except Exception:
            pass
    
    # v2: Compute trend_slope and trend_fit_r2
    trend_slope = None
    trend_fit_r2 = None
    if close_prices and len(close_prices) >= 10 and np is not None:
        try:
            # Linear regression: price = slope * time + intercept
            x = np.array(time_indices)
            y = np.array(close_prices)
            
            # Fit linear trend
            coeffs = np.polyfit(x, y, 1)
            trend_slope = float(coeffs[0])  # Slope
            
            # Compute R²
            y_pred = np.polyval(coeffs, x)
            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = np.sum((y - np.mean(y)) ** 2)
            if ss_tot > 0:
                trend_fit_r2 = float(1.0 - (ss_res / ss_tot))
            else:
                trend_fit_r2 = 0.0
        except Exception:
            # If numpy fails or data is invalid, leave as None
            pass
    
    # v2: Improved micro_regime classification
    dominant_regime = _classify_micro_regime_v2(
        avg_body_ratio,
        noise_score,
        trend_slope,
        trend_fit_r2,
        compression_score,
        expansion_score,
        regimes
    )
    
    return {
        "micro_regime": dominant_regime,
        "metrics": {
            # v1 fields (backward compatible)
            "spread": round(avg_spread, 6) if avg_spread is not None else None,
            "wick_ratio": round(wick_ratio_v2, 4) if wick_ratio_v2 is not None else (round(avg_wick_ratio, 4) if avg_wick_ratio is not None else None),  # v2: avg wick length vs body
            "volatility": round(avg_volatility, 6) if avg_volatility is not None else None,
            "body_ratio": round(avg_body_ratio, 4) if avg_body_ratio is not None else None,
            # v2 fields (additive)
            "noise_score": round(noise_score, 4) if noise_score is not None else None,
            "compression_score": round(compression_score, 4) if compression_score is not None else None,
            "expansion_score": round(expansion_score, 4) if expansion_score is not None else None,
            "trend_slope": round(trend_slope, 8) if trend_slope is not None else None,
            "trend_fit_r2": round(trend_fit_r2, 4) if trend_fit_r2 is not None else None,
            "delta_body_vs_volume": round(delta_body_vs_volume, 4) if delta_body_vs_volume is not None else None,
        },
    }


def compute_microstructure_snapshot(
    symbols: Optional[List[str]] = None,
    timeframe: str = "15m",
) -> Dict[str, Any]:
    """
    Compute microstructure snapshot for all enabled symbols.
    
    Args:
        symbols: List of symbols to process (if None, load from symbol registry)
        timeframe: Timeframe (default: "15m")
    
    Returns:
        Dict with structure:
        {
            "generated_at": "...",
            "timeframe": "15m",
            "symbols": {
                "ETHUSDT": {
                    "micro_regime": "expansion",
                    "metrics": {
                        "spread": 0.0023,
                        "wick_ratio": 1.4,
                        "volatility": 0.007,
                        "body_ratio": 0.55
                    }
                },
                ...
            }
        }
    """
    # Load symbols if not provided
    if symbols is None:
        try:
            from engine_alpha.core.symbol_registry import load_symbol_registry
            symbols = load_symbol_registry()
        except Exception:
            # Fallback to known symbols
            symbols = [
                "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "AVAXUSDT",
                "LINKUSDT", "DOTUSDT", "ADAUSDT", "ATOMUSDT", "XRPUSDT", "DOGEUSDT"
            ]
    
    snapshot: Dict[str, Any] = {
        "version": "v2.1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timeframe": timeframe,
        "health": {
            "status": "ok",
            "reasons": [],
        },
        "symbols": {},
    }
    
    for symbol in symbols:
        # Load OHLCV data
        candles = load_ohlcv_for_symbol(symbol, timeframe)
        
        if candles:
            # Compute bar-level features
            features_by_ts = compute_microstructure_for_symbol(symbol, timeframe)
            
            if features_by_ts:
                # Compute summary metrics (pass candles for close prices)
                summary = _compute_summary_metrics(features_by_ts, candles)
                snapshot["symbols"][symbol] = summary
    
    # Compute health
    if len(snapshot["symbols"]) == 0:
        snapshot["health"]["status"] = "stale"
        snapshot["health"]["reasons"].append("no_symbols")
    else:
        # Check for missing core fields
        missing_metrics_count = 0
        for sym_data in snapshot["symbols"].values():
            if not isinstance(sym_data, dict):
                missing_metrics_count += 1
                continue
            if "micro_regime" not in sym_data or "metrics" not in sym_data:
                missing_metrics_count += 1
                continue
            metrics = sym_data.get("metrics", {})
            if metrics.get("volatility") is None:
                missing_metrics_count += 1
        
        if missing_metrics_count > len(snapshot["symbols"]) * 0.5:  # More than 50% missing
            snapshot["health"]["status"] = "degraded"
            snapshot["health"]["reasons"].append(f"missing_metrics_for_{missing_metrics_count}_symbols")
    
    return snapshot


def load_microstructure_snapshot(timeframe: str = "15m") -> Dict[str, Any]:
    """
    Load existing microstructure snapshot from disk.
    
    Args:
        timeframe: Timeframe (default: "15m")
    
    Returns:
        Dict with microstructure snapshot, or empty dict if not found
    """
    if timeframe == "15m":
        path = MICROSTRUCTURE_SNAPSHOT_PATH
    else:
        path = RESEARCH_DIR / f"microstructure_snapshot_{timeframe}.json"
    
    if not path.exists():
        return {}
    
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def save_microstructure_snapshot(snapshot: Dict[str, Any], timeframe: str = "15m") -> Path:
    """
    Save microstructure snapshot to disk.
    
    Args:
        snapshot: Microstructure snapshot dict
        timeframe: Timeframe (default: "15m")
    
    Returns:
        Path to saved file
    """
    if timeframe == "15m":
        path = MICROSTRUCTURE_SNAPSHOT_PATH
    else:
        path = RESEARCH_DIR / f"microstructure_snapshot_{timeframe}.json"
    
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2))
    return path

