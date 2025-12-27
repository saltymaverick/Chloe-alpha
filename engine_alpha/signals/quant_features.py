# engine_alpha/signals/quant_features.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any

import numpy as np
import pandas as pd


@dataclass
class QuantFeatureConfig:
    """
    Configuration for feature extraction.
    You can extend this later with more lookbacks or toggles.
    """
    r_short: int = 1     # 1h return
    r_med: int = 4       # 4h return
    r_long: int = 24     # 24h return
    vol_win_short: int = 14
    vol_win_long: int = 50
    rsi_period: int = 14
    bb_window: int = 20
    bb_std: float = 2.0
    kc_window: int = 20
    kc_mult: float = 1.5


def _safe_pct_change(series: pd.Series, periods: int) -> pd.Series:
    return series.pct_change(periods=periods).replace([np.inf, -np.inf], np.nan)


def compute_quant_features(
    df: pd.DataFrame,
    cfg: Optional[QuantFeatureConfig] = None,
) -> pd.DataFrame:
    """
    Compute a set of quantitative features over an OHLCV DataFrame.

    Expected columns:
      - 'open', 'high', 'low', 'close', optionally 'volume'

    Returns a DataFrame with the same index and additional columns.
    """
    if cfg is None:
        cfg = QuantFeatureConfig()

    df = df.copy()

    # Basic returns
    df["ret_1h"] = _safe_pct_change(df["close"], cfg.r_short)
    df["ret_4h"] = _safe_pct_change(df["close"], cfg.r_med)
    df["ret_24h"] = _safe_pct_change(df["close"], cfg.r_long)

    # Volatility: realized stdev and ATR-like range
    df["vol_14"] = df["ret_1h"].rolling(cfg.vol_win_short).std()
    df["vol_50"] = df["ret_1h"].rolling(cfg.vol_win_long).std()

    hl_range = (df["high"] - df["low"]).abs()
    df["atr_14"] = hl_range.rolling(cfg.vol_win_short).mean()
    df["atr_50"] = hl_range.rolling(cfg.vol_win_long).mean()

    # Trend: EMA slopes
    ema_fast = df["close"].ewm(span=10, adjust=False).mean()
    ema_slow = df["close"].ewm(span=30, adjust=False).mean()
    df["ema_fast"] = ema_fast
    df["ema_slow"] = ema_slow
    df["ema_fast_slope"] = ema_fast.diff()
    df["ema_slow_slope"] = ema_slow.diff()

    # RSI-like oscillator
    delta = df["close"].diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.rolling(cfg.rsi_period).mean()
    avg_loss = loss.rolling(cfg.rsi_period).mean()
    rs = avg_gain / (avg_loss + 1e-12)
    df["rsi"] = 100.0 - (100.0 / (1.0 + rs))

    # Bollinger Bands
    bb_mid = df["close"].rolling(cfg.bb_window).mean()
    bb_std = df["close"].rolling(cfg.bb_window).std()
    df["bb_mid"] = bb_mid
    df["bb_width"] = (bb_std * cfg.bb_std * 2.0) / (bb_mid + 1e-12)  # normalized width

    # Keltner Channels (using ATR_14)
    kc_mid = df["close"].rolling(cfg.kc_window).mean()
    kc_band = df["atr_14"] * cfg.kc_mult
    df["kc_mid"] = kc_mid
    df["kc_width"] = (kc_band * 2.0) / (kc_mid + 1e-12)

    # "Squeeze": BB inside KC => contraction
    df["squeeze_on"] = (df["bb_width"] < df["kc_width"]).astype(int)

    # Normalize some features to guard extremes
    df["ret_1h_clipped"] = df["ret_1h"].clip(-0.2, 0.2)
    df["ret_4h_clipped"] = df["ret_4h"].clip(-0.5, 0.5)
    df["ret_24h_clipped"] = df["ret_24h"].clip(-1.0, 1.0)

    return df


