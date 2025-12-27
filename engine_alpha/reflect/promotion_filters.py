#!/usr/bin/env python3
"""
Promotion sample filtering utilities.

Provides canonical definitions for what counts as a "promotion sample close"
across all promotion-related components.
"""

from typing import Dict, Any, Optional


# Canonical exclude set for promotion sample closes
# These are churn/forced exits that shouldn't count toward promotion statistics
PROMO_EXCLUDE_EXIT_REASONS = {
    "review_bootstrap_timeout",
    "review_bootstrap_timeout_manual",
    "timeout_max_hold",
    "timeout_max_hold_seconds",
    "timeout_max_hold_bars",
    "timeout",
    "max_hold_timeout",
    "trim_to_core_limit",
    "manual_reset_stuck_position",
    "manual_reset",
}


def is_promo_sample_close(event: Dict[str, Any], lane: Optional[str] = None) -> bool:
    """
    Check if a trade event counts as a promotion sample close.

    Args:
        event: Trade event dict
        lane: Optional lane filter ("exploration", "core", or None for any)

    Returns:
        True if this close counts for promotion statistics
    """
    # Must be a close event
    event_type = (event.get("type") or event.get("event") or "").lower()
    if event_type not in ("close", "exit"):
        return False

    # Must have finite pct
    pct = event.get("pct") or event.get("pnl_pct")
    if pct is None:
        return False
    try:
        import math
        if not math.isfinite(float(pct)):
            return False
    except (ValueError, TypeError):
        return False

    # Lane check if specified
    if lane is not None:
        trade_kind = (event.get("trade_kind") or "").lower()
        strategy = (event.get("strategy") or "").lower()

        lane_match = False
        if lane == "exploration":
            lane_match = trade_kind == "exploration"
        elif lane == "core":
            lane_match = (trade_kind == "normal" and strategy != "recovery_v2") or trade_kind == "core"
        elif lane == "recovery":
            lane_match = strategy == "recovery_v2" or trade_kind == "recovery_v2"

        if not lane_match:
            return False

    # Exclude forced/churn exits
    exit_reason = (event.get("exit_reason") or "").lower().strip()
    if exit_reason in PROMO_EXCLUDE_EXIT_REASONS:
        return False

    return True


def get_promotion_filter_metadata() -> Dict[str, Any]:
    """
    Get metadata about the current promotion filter for logging/transparency.
    """
    return {
        "promotion_sample_filter": {
            "exclude_exit_reasons": sorted(list(PROMO_EXCLUDE_EXIT_REASONS)),
            "version": "promo_filter_v1",
            "description": "Excludes churn/forced closes; counts real exit types (tp/sl/drop/flip/micro_signal)"
        }
    }
