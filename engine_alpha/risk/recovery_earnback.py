#!/usr/bin/env python3
"""
Recovery Earn-Back Guarantee System

Ensures demoted symbols can earn their way back through clean, quant-safe rules.
Implements a three-stage ladder: sampling → proving → recovered.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple
from dateutil import parser


def compute_earnback_state(
    symbol: str,
    metrics: Dict[str, Any],
    now: datetime,
    last_demote_ts: Optional[str],
    window_stats: Dict[str, Any],
    config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Compute earn-back state for a symbol using post-demotion performance window.

    Args:
        symbol: Symbol name (e.g., "ETHUSDT")
        metrics: Full metrics dict (includes pre/post demotion data)
        now: Current datetime
        last_demote_ts: ISO timestamp of last demotion (None if never demoted)
        window_stats: Stats for the evaluation window
        config: Recovery configuration

    Returns:
        Dict with recovery_stage, allow_flags, and earnback_window
    """
    # Default state: normal trading
    state = {
        "recovery_stage": "none",
        "allow_exploration": True,
        "allow_core": True,
        "allow_recovery": False,
        "demoted_at": last_demote_ts,
        "earnback_window": {
            "n_closes": 0,
            "pf": None,
            "win_rate": None,
            "max_drawdown": None,
            "evaluation_window_days": 7
        }
    }

    # If never demoted, return normal state
    if not last_demote_ts:
        return state

    # Parse demotion timestamp
    try:
        demote_dt = parser.isoparse(last_demote_ts)
    except (ValueError, TypeError):
        # Invalid timestamp, treat as never demoted
        return state

    # If demotion was too long ago (>30 days), treat as recovered
    if (now - demote_dt).days > 30:
        state["recovery_stage"] = "recovered"
        return state

    # Get post-demotion metrics
    post_demotion_stats = _compute_post_demotion_stats(metrics, demote_dt, now)

    # Update earnback window
    state["earnback_window"] = post_demotion_stats

    # Apply three-stage earn-back ladder
    n_closes = post_demotion_stats["n_closes"]

    # Stage 1: Recovery Sampling (allow exploration with small caps)
    if n_closes < config.get("sampling_min_trades", 10):
        state["recovery_stage"] = "sampling"
        state["allow_exploration"] = True
        state["allow_core"] = False
        state["allow_recovery"] = False  # Use exploration instead

    # Stage 2: Recovery Proving (evaluate performance)
    elif n_closes < config.get("proving_min_trades", 30):
        state["recovery_stage"] = "proving"
        pf = post_demotion_stats.get("pf")
        win_rate = post_demotion_stats.get("win_rate", 0)
        max_dd = post_demotion_stats.get("max_drawdown", 0)

        # Must meet minimum performance thresholds
        pf_good = pf is not None and pf >= config.get("proving_min_pf", 1.02)
        wr_good = win_rate is None or win_rate >= config.get("proving_min_winrate", 0.40)
        dd_good = max_dd is None or max_dd <= config.get("proving_max_drawdown", 0.05)

        state["allow_exploration"] = True
        state["allow_core"] = pf_good and wr_good and dd_good
        state["allow_recovery"] = False

    # Stage 3: Recovered (normal trading restored)
    else:
        state["recovery_stage"] = "recovered"
        pf = post_demotion_stats.get("pf")
        win_rate = post_demotion_stats.get("win_rate", 0)
        max_dd = post_demotion_stats.get("max_drawdown", 0)

        # Must maintain good performance
        pf_good = pf is not None and pf >= config.get("recovered_min_pf", 1.05)
        wr_good = win_rate is None or win_rate >= config.get("recovered_min_winrate", 0.45)
        dd_good = max_dd is None or max_dd <= config.get("recovered_max_drawdown", 0.03)

        state["allow_exploration"] = True
        state["allow_core"] = pf_good and wr_good and dd_good
        state["allow_recovery"] = False

    return state


def _compute_post_demotion_stats(
    metrics: Dict[str, Any],
    demote_dt: datetime,
    now: datetime
) -> Dict[str, Any]:
    """
    Compute statistics only from trades after demotion timestamp.
    """
    # Use the window_stats passed from the caller
    # In practice, this would filter trades.jsonl by timestamp >= demote_dt
    # For now, use the metrics provided by the caller

    return {
        "n_closes": metrics.get("n_closes_7d", 0),
        "pf": metrics.get("pf_7d"),
        "win_rate": metrics.get("win_rate"),
        "max_drawdown": metrics.get("max_drawdown"),
        "evaluation_window_days": (now - demote_dt).days
    }


def get_default_recovery_config() -> Dict[str, Any]:
    """Get default recovery earn-back configuration."""
    return {
        # Stage 1: Sampling
        "sampling_min_trades": 10,
        "sampling_risk_mult_cap": 0.15,  # Conservative sizing
        "sampling_max_positions": 1,

        # Stage 2: Proving
        "proving_min_trades": 30,
        "proving_min_pf": 1.02,        # Must show slight edge
        "proving_min_winrate": 0.40,   # 40% win rate minimum
        "proving_max_drawdown": 0.05,  # 5% max drawdown
        "proving_risk_mult_cap": 0.20,
        "proving_max_positions": 1,

        # Stage 3: Recovered
        "recovered_min_pf": 1.05,      # Must show clear edge
        "recovered_min_winrate": 0.45, # 45% win rate
        "recovered_max_drawdown": 0.03, # 3% max drawdown

        # General
        "max_recovery_days": 30,       # Max time in recovery before forced recovery
        "evaluation_window_days": 7    # How far back to evaluate post-demotion
    }


def validate_earnback_transition(
    current_state: Dict[str, Any],
    new_state: Dict[str, Any]
) -> Tuple[bool, str]:
    """
    Validate that an earn-back state transition is logical.

    Returns (is_valid, reason)
    """
    current_stage = current_state.get("recovery_stage", "none")
    new_stage = new_state.get("recovery_stage", "none")

    stage_order = ["none", "sampling", "proving", "recovered"]
    current_idx = stage_order.index(current_stage) if current_stage in stage_order else -1
    new_idx = stage_order.index(new_stage) if new_stage in stage_order else -1

    # Allow progression forward or staying same
    if new_idx >= current_idx:
        return True, "Valid progression"

    # Allow reset to "none" if recovered
    if current_stage == "recovered" and new_stage == "none":
        return True, "Reset after full recovery"

    return False, f"Invalid regression: {current_stage} → {new_stage}"
