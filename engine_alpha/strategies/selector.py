# engine_alpha/strategies/selector.py

from __future__ import annotations

from typing import Optional
from .loader import load_all_strategies, filter_strategies, StrategyConfig

# Cache at module level
_ALL_STRATEGIES = load_all_strategies()


def choose_strategy(
    symbol: str,
    regime: str,
    timeframe: str,
    side: str
) -> Optional[StrategyConfig]:
    """
    Choose the highest-priority strategy that matches the given parameters.
    
    Args:
        symbol: Trading symbol (e.g., "ETHUSDT")
        regime: Market regime (e.g., "high_vol", "trend_down")
        timeframe: Timeframe (e.g., "5m", "1h")
        side: Trade direction ("long" or "short")
    
    Returns:
        StrategyConfig if a matching strategy is found, None otherwise
    """
    candidates = filter_strategies(_ALL_STRATEGIES, symbol, regime, timeframe, side)
    
    if not candidates:
        return None
    
    # For now, just pick the first (highest priority)
    return candidates[0]


def reload_strategies() -> None:
    """Reload strategies from disk (useful after adding new strategy files)."""
    global _ALL_STRATEGIES
    _ALL_STRATEGIES = load_all_strategies()


