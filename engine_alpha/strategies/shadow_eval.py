# engine_alpha/strategies/shadow_eval.py

from __future__ import annotations

from typing import Dict, Any
from .loader import StrategyConfig


def false_if_missing_or_too_wide(spread: Any, max_spread_bps: float) -> bool:
    """
    Helper: returns True if we should block due to missing or too-wide spread.
    """
    if spread is None:
        return True
    try:
        return float(spread) > float(max_spread_bps)
    except Exception:
        return True


def strategy_allows_entry(strategy: StrategyConfig, ctx: Dict[str, Any]) -> bool:
    """
    Evaluate whether a strategy would allow an entry given the current context.
    
    ctx can include keys like:
    - symbol, timeframe, regime, direction, side
    - confidence
    - spread_bps
    - volatility_band
    - swarm_state
    - any computed indicators (e.g. 'bollinger_upper_20_2', 'close', etc.)
    
    This runs in SHADOW MODE: it does not place trades or modify state.
    """
    entry = strategy.entry_logic or {}
    filters = entry.get("filters", {})
    trigger = entry.get("trigger", {})
    
    # 1) Trigger: basic example for 'metric' + 'relation'
    metric = trigger.get("metric")
    relation = trigger.get("relation")
    reference = trigger.get("reference")
    
    if metric == "regime" and relation == "equals":
        if ctx.get("regime") != reference:
            return False
    
    if metric == "close" and relation in ("above", "below", "cross_up", "cross_down"):
        close = ctx.get("close")
        ref_val = ctx.get(reference)
        
        if close is None or ref_val is None:
            return False
        
        if relation == "above" and not (close > ref_val):
            # You can extend this with more nuanced logic and min_distance_pct
            return False
        
        if relation == "below" and not (close < ref_val):
            return False
        
        # For simplicity, we leave cross_up/cross_down as TODO
    
    # 2) Confidence filter
    conf_min = filters.get("confidence_min")
    if conf_min is not None:
        conf = ctx.get("confidence", 0.0)
        if conf < conf_min:
            return False
    
    # 3) Spread filter
    max_spread_bps = filters.get("max_spread_bps")
    if max_spread_bps is not None:
        spread = ctx.get("spread_bps")
        if spread is None or spread > max_spread_bps:
            return false_if_missing_or_too_wide(spread, max_spread_bps)
    
    # 4) Volatility band
    vband = filters.get("volatility_band")
    if vband is not None:
        if ctx.get("volatility_band") != vband:
            return False
    
    # 5) SWARM state filter
    allowed_states = filters.get("swarm_required_state")
    if allowed_states:
        if ctx.get("swarm_state") not in allowed_states:
            return False
    
    # 6) On-chain filters (Glassnode metrics)
    onchain_filters = filters.get("onchain")
    if onchain_filters:
        if not _evaluate_onchain_filters(onchain_filters, ctx):
            return False
    
    return True


def _evaluate_onchain_filters(onchain_filters: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    """
    Evaluate on-chain filter conditions.
    
    Supported conditions:
    - "<= 0", ">= 0", "< 0", "> 0" - numeric comparisons
    - "increasing", "decreasing" - trend checks (requires lookback)
    - "> threshold", "< threshold" - custom thresholds
    
    Returns True if all conditions pass, False otherwise.
    """
    for metric_name, condition in onchain_filters.items():
        # Get metric value from context (e.g., "gn_exchange_netflow")
        metric_value = ctx.get(metric_name)
        
        if metric_value is None:
            # Metric not available - fail open (allow trade) for now
            # TODO: Could make this configurable (fail open vs fail closed)
            continue
        
        try:
            metric_val = float(metric_value)
        except (TypeError, ValueError):
            # Invalid metric value - fail open
            continue
        
        # Parse condition
        condition_str = str(condition).strip()
        
        # Numeric comparisons
        if condition_str == "<= 0":
            if not (metric_val <= 0):
                return False
        elif condition_str == ">= 0":
            if not (metric_val >= 0):
                return False
        elif condition_str == "< 0":
            if not (metric_val < 0):
                return False
        elif condition_str == "> 0":
            if not (metric_val > 0):
                return False
        elif condition_str.startswith(">="):
            threshold = float(condition_str[2:].strip())
            if not (metric_val >= threshold):
                return False
        elif condition_str.startswith("<="):
            threshold = float(condition_str[2:].strip())
            if not (metric_val <= threshold):
                return False
        elif condition_str.startswith(">"):
            threshold = float(condition_str[1:].strip())
            if not (metric_val > threshold):
                return False
        elif condition_str.startswith("<"):
            threshold = float(condition_str[1:].strip())
            if not (metric_val < threshold):
                return False
        elif condition_str == "increasing":
            # Check if metric is increasing (requires lookback)
            # For now, we'll need to add lookback data to context
            # TODO: Implement trend detection with lookback
            # For now, skip this check (fail open)
            pass
        elif condition_str == "decreasing":
            # Similar to increasing
            # TODO: Implement trend detection
            pass
        else:
            # Unknown condition - fail open (allow trade)
            pass
    
    return True

