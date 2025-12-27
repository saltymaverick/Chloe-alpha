#!/usr/bin/env python3
"""
Phase 5J Promotion Gate Specification

Canonical specification for promotion eligibility across all components:
- auto_promotions
- promotion_advice
- shadow_promotion_queue
- future council/governance logic

This ensures no contradictions in promotion decisions.
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass
from engine_alpha.reflect.promotion_filters import PROMO_EXCLUDE_EXIT_REASONS


@dataclass
class PromotionGateSpec:
    """Phase 5J Promotion Gate Specification - Conservative, Regime-First Approach"""

    # Sample requirements
    min_exploration_closes_7d: int = 25  # Canonical exploration closes (exclude churn/forced)
    min_exploration_closes_14d: int = 40  # Alternative smoother window

    # Edge requirements (primary)
    min_exploration_pf: float = 1.15  # Profit factor on canonical exploration sample

    # Edge requirements (secondary - pick one)
    min_expectancy_pct: float = 0.02  # Mean pct return after fees/slip
    min_win_rate: float = 0.52  # Win rate threshold
    min_win_loss_ratio: float = 1.10  # avg_win / avg_loss ratio

    # Stability guards
    max_drawdown_multiple: float = 1.5  # Max DD ≤ 1.5 × |avg_loss| × 6
    max_loss_streak: int = 5  # No loss streaks ≥ 5
    min_regime_purity: float = 0.70  # ≥70% sample in promoted regime

    # Promotion sizing (probation)
    probation_risk_mult_cap: float = 0.05  # Conservative first promotion cap
    probation_max_positions: int = 1
    probation_ttl_hours: int = 48

    # Auto-demotion triggers (during probation)
    probation_min_pf: float = 0.95
    probation_max_loss_streak: int = 3

    # Scope
    promote_regime_first: bool = True  # Promote per-regime overlays vs global core
    lane_scope: str = "exploration_to_core"  # Only exploration → core promotions

    # Implementation notes
    sample_definition: str = "canonical_exploration_closes"
    exclude_reasons: list = None  # Will be set to PROMO_EXCLUDE_EXIT_REASONS

    def __post_init__(self):
        if self.exclude_reasons is None:
            self.exclude_reasons = list(PROMO_EXCLUDE_EXIT_REASONS)


# Singleton instance - import this everywhere
PHASE5J_PROMOTION_GATES = PromotionGateSpec()


def get_promotion_gate_spec() -> PromotionGateSpec:
    """Get the canonical Phase 5J promotion gate specification."""
    return PHASE5J_PROMOTION_GATES


def validate_promotion_candidate(
    exploration_metrics: Dict[str, Any],
    regime: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validate if exploration metrics meet Phase 5J promotion gates.

    Args:
        exploration_metrics: Dict with keys like 'n_closes', 'pf', 'max_drawdown', etc.
        regime: Optional regime filter

    Returns:
        Dict with 'eligible': bool and 'reasons': List[str]
    """
    spec = get_promotion_gate_spec()
    reasons = []
    eligible = True

    # Sample size
    n_closes = exploration_metrics.get('n_closes', 0)
    if n_closes < spec.min_exploration_closes_7d:
        eligible = False
        reasons.append(f"insufficient_sample<{spec.min_exploration_closes_7d}")

    # Primary edge: PF
    pf = exploration_metrics.get('pf')
    if pf is None or pf < spec.min_exploration_pf:
        eligible = False
        reasons.append(f"pf<{spec.min_exploration_pf}")

    # Secondary edge checks (implement as needed)
    # expectancy = exploration_metrics.get('avg_return')
    # win_rate = exploration_metrics.get('win_rate')
    # ... add secondary checks here

    # Stability guards
    mdd = exploration_metrics.get('max_drawdown', 0)
    avg_loss = abs(exploration_metrics.get('avg_loss', 0))
    max_allowed_dd = spec.max_drawdown_multiple * avg_loss * 6
    if mdd > max_allowed_dd:
        eligible = False
        reasons.append(f"drawdown_too_large>{max_allowed_dd:.3f}")

    # Loss streak check (would need loss_streak metric)
    # loss_streak = exploration_metrics.get('loss_streak', 0)
    # if loss_streak >= spec.max_loss_streak:
    #     eligible = False
    #     reasons.append(f"loss_streak>={spec.max_loss_streak}")

    # Regime purity (would need regime_mix metric)
    # regime_mix = exploration_metrics.get('regime_mix', {})
    # if regime and regime_mix.get(regime, 0) < spec.min_regime_purity:
    #     eligible = False
    #     reasons.append(f"regime_purity<{spec.min_regime_purity}")

    return {
        'eligible': eligible,
        'reasons': reasons,
        'spec_version': 'phase5j_v1'
    }


def get_promotion_gate_metadata() -> Dict[str, Any]:
    """Get metadata about promotion gates for logging/transparency."""
    spec = get_promotion_gate_spec()
    return {
        'promotion_gates': {
            'version': 'phase5j_v1',
            'spec': {
                'min_exploration_closes_7d': spec.min_exploration_closes_7d,
                'min_exploration_pf': spec.min_exploration_pf,
                'max_drawdown_multiple': spec.max_drawdown_multiple,
                'probation_risk_mult_cap': spec.probation_risk_mult_cap,
                'sample_definition': spec.sample_definition,
                'exclude_reasons': spec.exclude_reasons,
            },
            'description': 'Conservative Phase 5J gates: meaningful sample + proven edge + stability guards + probation'
        }
    }
