"""
Signal fetchers - Phase 1 (Stub/Sim only)
Provides deterministic stub functions for signal fetching.
"""

import random
import yaml
from pathlib import Path
from typing import Dict, Any, Optional


# Set seed for deterministic results
random.seed(42)


def _load_data_sources() -> Optional[Dict[str, Any]]:
    """Load data sources configuration if present."""
    config_path = Path("/root/engine_alpha/config/data_sources.yaml")
    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                return yaml.safe_load(f)
        except Exception:
            return None
    return None


def fetch_ret_g5(symbol: str = "ETHUSDT", timeframe: str = "1h") -> float:
    """
    Fetch 5-period return signal.
    
    Args:
        symbol: Trading symbol (default: ETHUSDT)
        timeframe: Timeframe (default: 1h)
    
    Returns:
        Simulated return value (typically -0.05 to 0.05)
    """
    data_sources = _load_data_sources()
    # Simulate return: range approximately -5% to +5%
    return random.uniform(-0.05, 0.05)


def fetch_rsi_14(symbol: str = "ETHUSDT", timeframe: str = "1h") -> float:
    """
    Fetch RSI(14) indicator value.
    
    Args:
        symbol: Trading symbol (default: ETHUSDT)
        timeframe: Timeframe (default: 1h)
    
    Returns:
        Simulated RSI value (0-100)
    """
    data_sources = _load_data_sources()
    # Simulate RSI: range 0-100, centered around 50
    return random.uniform(20, 80)


def fetch_macd_hist(symbol: str = "ETHUSDT", timeframe: str = "1h") -> float:
    """
    Fetch MACD histogram value.
    
    Args:
        symbol: Trading symbol (default: ETHUSDT)
        timeframe: Timeframe (default: 1h)
    
    Returns:
        Simulated MACD histogram value
    """
    data_sources = _load_data_sources()
    # Simulate MACD histogram: can be positive or negative
    return random.uniform(-50, 50)


def fetch_vwap_dist(symbol: str = "ETHUSDT", timeframe: str = "1h") -> float:
    """
    Fetch distance from VWAP.
    
    Args:
        symbol: Trading symbol (default: ETHUSDT)
        timeframe: Timeframe (default: 1h)
    
    Returns:
        Simulated VWAP distance (percentage)
    """
    data_sources = _load_data_sources()
    # Simulate VWAP distance: percentage deviation
    return random.uniform(-0.02, 0.02)


def fetch_atrp(symbol: str = "ETHUSDT", timeframe: str = "1h") -> float:
    """
    Fetch ATR percentage.
    
    Args:
        symbol: Trading symbol (default: ETHUSDT)
        timeframe: Timeframe (default: 1h)
    
    Returns:
        Simulated ATR percentage (0-10%)
    """
    data_sources = _load_data_sources()
    # Simulate ATR percentage: typically 0-10%
    return random.uniform(0.5, 5.0)


def fetch_bb_width(symbol: str = "ETHUSDT", timeframe: str = "1h") -> float:
    """
    Fetch Bollinger Bands width.
    
    Args:
        symbol: Trading symbol (default: ETHUSDT)
        timeframe: Timeframe (default: 1h)
    
    Returns:
        Simulated BB width
    """
    data_sources = _load_data_sources()
    # Simulate BB width: typically 0-5
    return random.uniform(0.5, 3.0)


def fetch_vol_delta(symbol: str = "ETHUSDT", timeframe: str = "1h") -> float:
    """
    Fetch volume delta.
    
    Args:
        symbol: Trading symbol (default: ETHUSDT)
        timeframe: Timeframe (default: 1h)
    
    Returns:
        Simulated volume delta
    """
    data_sources = _load_data_sources()
    # Simulate volume delta: can be positive or negative
    return random.uniform(-1000000, 1000000)


def fetch_funding_bias(symbol: str = "ETHUSDT", timeframe: str = "1h") -> float:
    """
    Fetch funding rate bias.
    
    Args:
        symbol: Trading symbol (default: ETHUSDT)
        timeframe: Timeframe (default: 1h)
    
    Returns:
        Simulated funding rate bias (-0.01 to 0.01)
    """
    data_sources = _load_data_sources()
    # Simulate funding bias: typically -0.01 to 0.01
    return random.uniform(-0.005, 0.005)


def fetch_oi_beta(symbol: str = "ETHUSDT", timeframe: str = "1h") -> float:
    """
    Fetch open interest beta.
    
    Args:
        symbol: Trading symbol (default: ETHUSDT)
        timeframe: Timeframe (default: 1h)
    
    Returns:
        Simulated OI beta value
    """
    data_sources = _load_data_sources()
    # Simulate OI beta: can vary significantly
    return random.uniform(-2.0, 2.0)


def fetch_session_heat(symbol: str = "ETHUSDT", timeframe: str = "1h") -> float:
    """
    Fetch session activity heat.
    
    Args:
        symbol: Trading symbol (default: ETHUSDT)
        timeframe: Timeframe (default: 1h)
    
    Returns:
        Simulated session heat (0-1)
    """
    data_sources = _load_data_sources()
    # Simulate session heat: 0-1 normalized
    return random.uniform(0.0, 1.0)


def fetch_event_cooldown(symbol: str = "ETHUSDT", timeframe: str = "1h") -> float:
    """
    Fetch event cooldown timer.
    
    Args:
        symbol: Trading symbol (default: ETHUSDT)
        timeframe: Timeframe (default: 1h)
    
    Returns:
        Simulated cooldown timer (0-24 hours)
    """
    data_sources = _load_data_sources()
    # Simulate event cooldown: 0-24 hours
    return random.uniform(0, 20)


def fetch_spread_normalized(symbol: str = "ETHUSDT", timeframe: str = "1h") -> float:
    """
    Fetch normalized bid-ask spread.
    
    Args:
        symbol: Trading symbol (default: ETHUSDT)
        timeframe: Timeframe (default: 1h)
    
    Returns:
        Simulated normalized spread (0-0.001)
    """
    data_sources = _load_data_sources()
    # Simulate spread: typically 0-0.001 (0-0.1%)
    return random.uniform(0.00005, 0.0005)

