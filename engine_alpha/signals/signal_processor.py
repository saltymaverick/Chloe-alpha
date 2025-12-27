"""
Signal processor - Phase 1
Processes signals from registry and returns normalized signal vector.
"""

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

try:
    import pandas as pd  # type: ignore
except ImportError:  # pragma: no cover
    pd = None  # type: ignore

from engine_alpha.data.live_prices import get_live_ohlcv
from engine_alpha.data.funding_rates import get_funding_bias
from engine_alpha.signals import signal_fetchers
from engine_alpha.core.paths import CONFIG

# PCI imports (Phase 1 + 2)
try:
    from engine_alpha.signals.pre_candle_features import (
        compute_funding_velocity,
        compute_funding_acceleration,
        compute_oi_delta,
        compute_oi_acceleration,
        compute_oi_price_divergence,
        compute_orderbook_imbalance,
        compute_liquidity_decay_speed,
        compute_taker_imbalance,
    )
    from engine_alpha.signals.pre_candle_scoring import score_pre_candle
    from engine_alpha.signals.pre_candle_state import update_pci_state
    PCI_AVAILABLE = True
except ImportError:
    PCI_AVAILABLE = False


def _get_default_timeframe() -> str:
    """Load default timeframe from engine_config.json, fallback to '15m'."""
    try:
        config_path = CONFIG / "engine_config.json"
        if config_path.exists():
            with config_path.open() as f:
                cfg = json.load(f)
                return cfg.get("timeframe", "15m")
    except Exception:
        pass
    return "15m"


def _load_pci_config() -> Dict[str, Any]:
    """Load PCI config from engine_config.json, return defaults if not present."""
    default_config = {
        "enabled": False,
        "mode": "observe",
        "defensive_enabled": False,
        "amplify_enabled": False,
        "log_enabled": True,
        "thresholds": {
            "trap_block": 0.70,
            "fakeout_block": 0.65,
            "crowding_tighten": 0.70,
        },
        "confidence_adjust": {
            "crowding_add": 0.15,
        },
    }
    
    try:
        config_path = CONFIG / "engine_config.json"
        if config_path.exists():
            with config_path.open() as f:
                cfg = json.load(f)
                pci_cfg = cfg.get("pre_candle", {})
                # Merge with defaults
                result = default_config.copy()
                result.update(pci_cfg)
                if "thresholds" in pci_cfg:
                    result["thresholds"].update(pci_cfg["thresholds"])
                if "confidence_adjust" in pci_cfg:
                    result["confidence_adjust"].update(pci_cfg["confidence_adjust"])
                return result
    except Exception:
        pass
    
    return default_config


def _compute_pci_features(
    symbol: str,
    timeframe: str,
    df: Optional["pd.DataFrame"],
    funding_bias: float,
    ctx: Optional[Dict[str, Any]] = None
) -> Dict[str, float]:
    """
    Compute PCI features from available data (Phase 2.5: with ring buffer).
    
    This function safely handles missing data and returns a feature dict
    that can be used for scoring. Missing features are set to 0.0.
    
    Args:
        symbol: Trading symbol
        timeframe: Timeframe (for ring buffer key)
        df: DataFrame with OHLCV data (optional)
        funding_bias: Current funding bias (normalized)
        ctx: Optional context dict
    
    Returns:
        Dict of computed features
    """
    features: Dict[str, float] = {}
    
    if not PCI_AVAILABLE:
        return features
    
    # Extract price series if available
    price_series: List[float] = []
    if df is not None and not df.empty and "close" in df.columns:
        price_series = df["close"].tolist()
    
    # Get timestamp (use context ts or current time)
    import time
    current_ts = None
    if ctx and "now" in ctx:
        try:
            from datetime import datetime
            current_ts = datetime.fromisoformat(ctx["now"].replace("Z", "+00:00")).timestamp()
        except Exception:
            current_ts = time.time()
    else:
        current_ts = time.time()
    
    # Update PCI state with current snapshot values
    # Note: funding_bias is normalized [-1, 1], we store it as-is
    # OI, orderbook_depth, taker_imbalance not available yet (will be None)
    try:
        series_dict = update_pci_state(
            symbol,
            timeframe,
            funding=funding_bias if funding_bias != 0.0 else None,
            oi=None,  # Not available from current pipeline
            orderbook_depth=None,  # Not available from current pipeline
            taker_imbalance=None,  # Not available from current pipeline
            ts=current_ts
        )
    except Exception:
        # Buffer update failure shouldn't break feature computation
        series_dict = {
            "funding_series": [],
            "oi_series": [],
            "orderbook_depth_series": [],
            "taker_imbalance_series": [],
            "timestamp_series": [],
        }
    
    # Extract series from buffer
    funding_series = series_dict.get("funding_series", [])
    oi_series = series_dict.get("oi_series", [])
    depth_series = series_dict.get("orderbook_depth_series", [])
    taker_imbalance_series = series_dict.get("taker_imbalance_series", [])
    
    # Compute funding features (will return 0.0 if insufficient data)
    features["funding_velocity"] = compute_funding_velocity(funding_series)
    features["funding_acceleration"] = compute_funding_acceleration(funding_series)
    
    # OI features
    features["oi_delta"] = compute_oi_delta(oi_series)
    features["oi_acceleration"] = compute_oi_acceleration(oi_series)
    
    # OI-Price divergence (requires both series)
    if len(price_series) >= 2 and len(oi_series) >= 2:
        features["oi_price_divergence"] = compute_oi_price_divergence(oi_series, price_series)
    else:
        features["oi_price_divergence"] = 0.0
    
    # Orderbook features
    # For imbalance, we'd need bid/ask separately, but for now use 0.0
    features["orderbook_imbalance"] = compute_orderbook_imbalance(
        bid_depth_near=0.0,
        ask_depth_near=0.0,
        bid_depth_far=None,
        ask_depth_far=None
    )
    # Liquidity decay from depth series
    features["liquidity_decay_speed"] = compute_liquidity_decay_speed(depth_series)
    
    # Taker imbalance (use most recent value if available)
    if taker_imbalance_series:
        # taker_imbalance_series contains imbalance values [-1, 1]
        # For compute_taker_imbalance, we need buy_vol and sell_vol
        # Since we only have imbalance, we'll compute a proxy
        latest_imbalance = taker_imbalance_series[-1]
        # Proxy: assume total volume = 1.0, then buy_vol = (1 + imbalance) / 2, sell_vol = (1 - imbalance) / 2
        buy_vol_proxy = (1.0 + latest_imbalance) / 2.0
        sell_vol_proxy = (1.0 - latest_imbalance) / 2.0
        features["taker_imbalance"] = compute_taker_imbalance(buy_vol_proxy, sell_vol_proxy)
    else:
        features["taker_imbalance"] = 0.0
    
    return features


def _compute_pci_scores(features: Dict[str, float]) -> Dict[str, Any]:
    """
    Compute PCI scores from features.
    
    Args:
        features: Dict of computed features
    
    Returns:
        Dict with "features" and "scores" keys, or empty dict if PCI unavailable
    """
    if not PCI_AVAILABLE:
        return {}
    
    try:
        scores = score_pre_candle(features)
        return {
            "features": features,
            "scores": scores,
        }
    except Exception:
        # On any error, return empty dict (safe fallback)
        return {}


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


def _rows_to_dataframe(rows: List[Dict[str, Any]]) -> Optional["pd.DataFrame"]:
    if pd is None or not rows:
        return None
    try:
        df = pd.DataFrame(rows)
        required_cols = {"open", "high", "low", "close", "volume"}
        if not required_cols.issubset(df.columns):
            return None
        if "ts" in df.columns:
            df["ts"] = pd.to_datetime(df["ts"])
            df = df.sort_values("ts")
            df = df.set_index("ts")
        float_cols = ["open", "high", "low", "close", "volume"]
        df[float_cols] = df[float_cols].astype(float)
        return df
    except Exception:
        return None


def _compute_core_live_signals(df: "pd.DataFrame") -> Dict[str, float]:
    if df is None or df.empty:
        return {}
    df = df.copy()
    close = df["close"]
    vol = df["volume"]

    # Ret_G5
    if len(close) >= 6:
        ret_g5 = (close.iloc[-1] - close.iloc[-6]) / close.iloc[-6] if close.iloc[-6] != 0 else 0.0
    else:
        ret_g5 = 0.0

    # RSI_14
    if len(close) >= 15:
        delta = close.diff()
        gain = np.where(delta > 0, delta, 0.0)
        loss = np.where(delta < 0, -delta, 0.0)
        roll_up = pd.Series(gain, index=close.index).rolling(14).mean().iloc[-1]
        roll_down = pd.Series(loss, index=close.index).rolling(14).mean().iloc[-1]
        if roll_down == 0:
            rsi_14 = 100.0 if roll_up > 0 else 50.0
        else:
            rs = roll_up / roll_down
            rsi_14 = 100.0 - (100.0 / (1.0 + rs))
    else:
        rsi_14 = 50.0

    # MACD Histogram
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    macd_hist = float((macd - signal).iloc[-1])

    # VWAP distance
    pv = close * vol
    cum_vol = vol.cumsum()
    vwap = (pv.cumsum() / cum_vol).iloc[-1] if cum_vol.iloc[-1] != 0 else close.iloc[-1]
    vwap_dist = (close.iloc[-1] - vwap) / vwap if vwap != 0 else 0.0

    # ATR%
    high = df["high"]
    low = df["low"]
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().iloc[-1] if len(tr) >= 14 else tr.iloc[-1]
    atrp = atr / close.iloc[-1] if close.iloc[-1] != 0 else 0.0

    # Bollinger Band Width
    if len(close) >= 20:
        ma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        upper = ma20 + 2 * std20
        lower = ma20 - 2 * std20
        bb_width = (upper.iloc[-1] - lower.iloc[-1]) / ma20.iloc[-1] if ma20.iloc[-1] != 0 else 0.0
    else:
        bb_width = 0.0

    # Volume delta
    if len(vol) >= 20:
        avg_vol = vol.rolling(20).mean().iloc[-1]
        vol_delta = (vol.iloc[-1] - avg_vol) / avg_vol if avg_vol != 0 else 0.0
    else:
        vol_delta = 0.0

    return {
        "Ret_G5": float(ret_g5),
        "RSI_14": float(rsi_14),
        "MACD_Hist": macd_hist,
        "VWAP_Dist": float(vwap_dist),
        "ATRp": float(atrp),
        "BB_Width": float(bb_width),
        "Vol_Delta": float(vol_delta),
    }


def _compute_expanded_signals(df: "pd.DataFrame") -> Dict[str, float]:
    if df is None or df.empty:
        return {}
    df = df.copy().sort_index()
    close = df["close"]
    high = df["high"]
    low = df["low"]
    vol = df["volume"]
    n = len(df)

    ret_1h = (close.iloc[-1] - close.iloc[-5]) / close.iloc[-5] if n >= 5 and close.iloc[-5] else 0.0
    ret_4h = (close.iloc[-1] - close.iloc[-17]) / close.iloc[-17] if n >= 17 and close.iloc[-17] else 0.0

    adx_14 = 0.0
    chop_14 = 50.0
    if n >= 15:
        prev_close = close.shift(1)
        plus_dm = high.diff()
        minus_dm = low.diff().mul(-1)
        plus_dm = np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0.0)
        minus_dm = np.where((minus_dm > plus_dm) & (minus_dm > 0), minus_dm, 0.0)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr14 = tr.rolling(14).mean()
        plus_di = 100 * (pd.Series(plus_dm, index=close.index).rolling(14).mean() / atr14)
        minus_di = 100 * (pd.Series(minus_dm, index=close.index).rolling(14).mean() / atr14)
        dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
        if dx.notna().iloc[-1]:
            adx_14 = float(dx.rolling(14).mean().iloc[-1])

        tr_sum = tr.rolling(14).sum()
        highest14 = high.rolling(14).max()
        lowest14 = low.rolling(14).min()
        denom = (highest14 - lowest14).replace(0, np.nan)
        ci = 100 * np.log10(tr_sum / denom) / np.log10(14)
        if ci.notna().iloc[-1]:
            chop_14 = float(ci.iloc[-1])

    returns = close.pct_change()
    realvol_15 = float(returns.iloc[-15:].std()) if n >= 15 and returns.iloc[-15:].notna().any() else 0.0
    realvol_60 = float(returns.iloc[-60:].std()) if n >= 60 and returns.iloc[-60:].notna().any() else 0.0

    if n >= 21:
        vol_mean = vol.rolling(20).mean().iloc[-1]
        vol_std = vol.rolling(20).std().iloc[-1]
        if vol_std and not np.isnan(vol_std):
            vol_z_20 = float((vol.iloc[-1] - vol_mean) / vol_std)
        else:
            vol_z_20 = 0.0
    else:
        vol_z_20 = 0.0

    body = (close - df["open"]).abs()
    up_wick = (high - close).where(close >= df["open"], high - df["open"])
    down_wick = (df["open"] - low).where(close >= df["open"], close - low)
    body_last = float(body.iloc[-1])
    total_wick = float(up_wick.iloc[-1] + down_wick.iloc[-1])

    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1]) if n >= 14 else float(tr.iloc[-1])
    atr = max(atr, 1e-9)

    body_pct = body_last / atr
    wick_ratio = total_wick / body_last if body_last != 0 else 0.0
    breakout_atr = body_last / atr

    return {
        "RET_1H": float(ret_1h),
        "RET_4H": float(ret_4h),
        "ADX_14": float(adx_14),
        "CHOP_14": float(chop_14),
        "REALVOL_15": float(realvol_15),
        "REALVOL_60": float(realvol_60),
        "VOL_Z_20": float(vol_z_20),
        "BODY_PCT": float(body_pct),
        "WICK_RATIO": float(wick_ratio),
        "BREAKOUT_ATR": float(breakout_atr),
    }


def _compute_direction_conf_edge(signals: Dict[str, float]) -> Dict[str, float]:
    ret_g5 = signals.get("Ret_G5", 0.0)
    rsi = signals.get("RSI_14", 50.0)
    macd_hist = signals.get("MACD_Hist", 0.0)
    atrp = max(abs(signals.get("ATRp", 0.0)), 1e-6)

    score = 0.0
    score += math.tanh(ret_g5 / atrp) * 0.6
    score += math.tanh((rsi - 50.0) / 15.0) * 0.3
    score += math.tanh(macd_hist * 5.0) * 0.2

    dir_ = 0
    if score > 0.05:
        dir_ = 1
    elif score < -0.05:
        dir_ = -1

    conf = min(abs(score), 1.0)
    combined_edge = ret_g5
    return {"dir": dir_, "conf": conf, "combined_edge": combined_edge}


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

        if source_func_name == "live_core_only":
            raw_registry[signal_name] = {
                "value": 0.0,
                "source": "live_core_only",
                "note": "live-only signal (populated in get_signal_vector_live)",
                "category": signal_config.get("category", "unknown"),
                "weight": signal_config.get("weight", 1.0),
            }
            signal_vector.append(0.0)
            continue
        
        # Dynamically call fetcher function
        if hasattr(signal_fetchers, source_func_name):
            fetcher_func = getattr(signal_fetchers, source_func_name)
            try:
                # Call fetcher with symbol, timeframe, and context
                fetcher_result = fetcher_func(symbol=symbol, timeframe=timeframe, context=ctx)
                
                # Handle flow signals (dict) vs traditional signals (float)
                norm_method = signal_config.get("norm", "z-tanh")
                
                if norm_method == "flow_dict" and isinstance(fetcher_result, dict):
                    # Flow signal: extract components
                    raw_value = fetcher_result.get("raw", 0.0)
                    z_score = fetcher_result.get("z_score", 0.0)
                    direction_prob = fetcher_result.get("direction_prob", {"up": 0.5, "down": 0.5})
                    confidence = fetcher_result.get("confidence", 0.5)
                    drift = fetcher_result.get("drift", 0.0)
                    
                    # Store full flow signal dict in raw_registry
                    raw_registry[signal_name] = {
                        "value": raw_value,  # For backward compatibility
                        "raw": raw_value,
                        "z_score": z_score,
                        "direction_prob": direction_prob,
                        "confidence": confidence,
                        "drift": drift,
                        "source": source_func_name,
                        "category": signal_config.get("category", "flow"),
                        "weight": signal_config.get("weight", 1.0),
                        "type": "flow_dict"
                    }
                    
                    # Use z_score for signal vector (already normalized)
                    # Apply tanh to bound to [-1, 1]
                    normalized_value = math.tanh(z_score / 2.0)
                    signal_vector.append(normalized_value)
                    
                else:
                    # Traditional signal: single float value
                    raw_value = fetcher_result if isinstance(fetcher_result, (int, float)) else float(fetcher_result)
                    
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
                error_msg = str(e)
                raw_registry[signal_name] = {
                    "value": 0.0,
                    "error": error_msg,
                    "source": source_func_name
                }
                signal_vector.append(0.0)
                
                # Log MATIC signal errors for debugging
                if symbol == "MATICUSDT":
                    import logging
                    matic_logger = logging.getLogger("matic_decisions")
                    if not matic_logger.handlers:
                        from engine_alpha.logging_utils import get_matic_logger
                        matic_logger = get_matic_logger()
                    matic_logger.info(
                        f"MATIC_SIGNAL_ERROR symbol=MATICUSDT signal={signal_name} "
                        f"fetcher={source_func_name} error={error_msg[:100]}"
                    )
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
    
    result = {
        "signal_vector": signal_vector,
        "raw_registry": raw_registry,
        "ts": ts,
    }
    
    # PCI computation for stub mode (Phase 2.5: compute + log only)
    pci_config = _load_pci_config()
    if pci_config.get("log_enabled", True) and PCI_AVAILABLE:
        try:
            # In stub mode, we don't have real data, so features will be mostly 0.0
            # But ring buffer will accumulate if we get any funding values
            pci_features = _compute_pci_features(symbol, timeframe, None, 0.0, ctx)
            pci_output = _compute_pci_scores(pci_features)
            if pci_output:
                result["pre_candle"] = pci_output
        except Exception:
            # PCI computation failed - silently skip in stub mode
            pass
    
    return result


def get_signal_vector(symbol: str = "ETHUSDT", timeframe: str = None) -> Dict[str, Any]:
    """
    Generate signal vector via stub fetchers (simulation/testing mode).
    """
    if timeframe is None:
        timeframe = _get_default_timeframe()
    ctx = {
        "symbol": symbol,
        "timeframe": timeframe,
        "mode": "sim",
        "now": datetime.now(timezone.utc).isoformat(),
    }
    return _build_signal_vector(symbol, timeframe, ctx=ctx, ts_override=ctx["now"])


def get_signal_vector_live(symbol: str = "ETHUSDT", timeframe: str = None, limit: int = 200) -> Dict[str, Any]:
    """
    Generate signal vector using live OHLCV context (read-only).
    
    If live feed is unavailable or stale, returns neutral signal vector (all zeros)
    and logs an error instead of using stale data.
    """
    import logging
    
    if timeframe is None:
        timeframe = _get_default_timeframe()
    
    rows, _ = get_live_ohlcv(symbol, timeframe, limit=limit)
    
    # Check if feed is unavailable
    if not rows:
        # Log feed unavailability
        feed_logger = logging.getLogger("live_feeds")
        if not feed_logger.handlers:
            from engine_alpha.logging_utils import get_matic_logger
            feed_logger = logging.getLogger("live_feeds")
            feed_logger.setLevel(logging.WARNING)
        
        feed_logger.warning(
            f"SIGNAL_FEED_UNAVAILABLE symbol={symbol} timeframe={timeframe} "
            f"reason=No fresh OHLCV data available"
        )
        
        # Return neutral signal vector (all zeros) instead of using stale data
        registry = _load_registry()
        signals = registry.get("signals", [])
        signal_vector = [0.0] * len(signals)
        raw_registry = {
            "_feed_unavailable": True,
            "_symbol": symbol,
            "_timeframe": timeframe
        }
        
        ts = datetime.now(timezone.utc).isoformat()
        ctx = {
            "symbol": symbol,
            "timeframe": timeframe,
            "mode": "live",
            "now": ts,
            "rows_available": 0,
            "limit": limit,
            "feed_unavailable": True
        }
        
        return {
            "signal_vector": signal_vector,
            "raw_registry": raw_registry,
            "ts": ts,
            "context": ctx
        }
    
    # Defensive timestamp extraction - crash-proof (never use direct indexing)
    ts = None
    if rows and len(rows) > 0:
        last_row = rows[-1]
        if isinstance(last_row, dict):
            ts = (
                last_row.get("ts")
                or last_row.get("timestamp")
                or last_row.get("open_time")
                or last_row.get("close_time")
                or last_row.get("time")
            )
            # Convert numeric timestamp to ISO if needed
            if ts and isinstance(ts, (int, float)):
                if ts > 1e10:  # Assume milliseconds
                    ts = ts / 1000
                ts_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                ts = ts_dt.isoformat()
    
    # Fallback to current time if no valid timestamp found
    if not ts:
        ts = datetime.now(timezone.utc).isoformat()
    ctx = {
        "symbol": symbol,
        "timeframe": timeframe,
        "mode": "live",
        "now": ts,
        "rows_available": len(rows),
        "limit": limit,
    }
    df = _rows_to_dataframe(rows)
    if df is None or len(df) < 25:
        result = _build_signal_vector(symbol, timeframe, ctx=ctx, ts_override=ts)
        result["context"] = ctx
        result["dir"] = 0
        result["conf"] = 0.0
        result["combined_edge"] = 0.0
        
        # PCI computation for insufficient data case (Phase 2.5: compute + log only)
        pci_config = _load_pci_config()
        if pci_config.get("log_enabled", True) and PCI_AVAILABLE:
            try:
                funding_bias = get_funding_bias(symbol) if df is not None else 0.0
                pci_features = _compute_pci_features(symbol, timeframe, df, funding_bias, ctx)
                pci_output = _compute_pci_scores(pci_features)
                if pci_output:
                    result["pre_candle"] = pci_output
            except Exception:
                pass
        
        return result

    core_signals = _compute_core_live_signals(df)
    expanded_signals = _compute_expanded_signals(df)
    all_signals = {**core_signals, **expanded_signals}
    try:
        all_signals["Funding_Bias"] = get_funding_bias(symbol)
    except Exception:
        all_signals["Funding_Bias"] = 0.0

    registry = _load_registry()
    signals_cfg = registry.get("signals", [])
    signal_vector: List[float] = []
    raw_registry: Dict[str, Any] = {}
    for sig_cfg in signals_cfg:
        name = sig_cfg["name"]
        raw_val = all_signals.get(name, 0.0)
        raw_registry[name] = {
            "value": raw_val,
            "source": "live_core",
            "category": sig_cfg.get("category", "unknown"),
            "weight": sig_cfg.get("weight", 1.0),
        }
        signal_vector.append(_normalize_signal(raw_val, sig_cfg))

    decision_inputs = _compute_direction_conf_edge(all_signals)
    result = {
        "signal_vector": signal_vector,
        "raw_registry": raw_registry,
        "ts": ts,
        "context": ctx,
        "dir": decision_inputs["dir"],
        "conf": float(decision_inputs["conf"]),
        "combined_edge": float(decision_inputs["combined_edge"]),
    }

    # PCI computation (Phase 1 + 2: compute + log only, no gating)
    pci_config = _load_pci_config()
    if pci_config.get("log_enabled", True) and PCI_AVAILABLE:
        try:
            funding_bias = all_signals.get("Funding_Bias", 0.0)
            pci_features = _compute_pci_features(symbol, timeframe, df, funding_bias, ctx)
            pci_output = _compute_pci_scores(pci_features)
            if pci_output:
                result["pre_candle"] = pci_output
        except Exception as e:
            # PCI computation failed - log but don't break signal processing
            pci_logger = logging.getLogger("pci")
            if not pci_logger.handlers:
                pci_logger.setLevel(logging.WARNING)
            pci_logger.warning(
                f"PCI_COMPUTE_ERROR symbol={symbol} error={str(e)[:100]}"
            )

    if raw_registry and all(abs(v["value"]) < 1e-9 for v in raw_registry.values()):
        logging.getLogger("signals").warning(
            "LIVE_SIGNAL_SANITY: symbol=%s timeframe=%s produced all-zero signals; check live signal wiring.",
            symbol,
            timeframe,
        )

    return result

