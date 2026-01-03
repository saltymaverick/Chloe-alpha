"""
Auto-Governance for CORE Lane Access
=====================================

Single source of truth for CORE promotion and demotion rules.
Called by symbol_state_builder on every rebuild.

Design Principles:
- CORE is EARNED, not manually assigned
- Any symbol can reach CORE if performance warrants
- CORE is REVOCABLE when performance degrades
- Thresholds are conservative and testable
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple


# ============================================
# GOVERNANCE THRESHOLDS (single source of truth)
# ============================================

@dataclass(frozen=True)
class GovernanceThresholds:
    """Immutable thresholds for auto-governance decisions"""
    
    # CORE Promotion thresholds
    promote_min_pf_7d: float = 1.02       # Minimum PF to earn CORE
    promote_min_closes_7d: int = 30       # Minimum sample size
    promote_min_closes_30d: int = 50      # Longer-term sample requirement
    
    # CORE Demotion thresholds
    demote_pf_7d_floor: float = 0.95      # Demote if PF falls below
    demote_pf_30d_floor: float = 0.90     # Demote if 30d PF is very bad
    
    # Quarantine thresholds (more severe)
    quarantine_pf_7d_floor: float = 0.85  # Quarantine if PF is toxic
    quarantine_min_closes: int = 60       # Only quarantine with good sample
    
    # Sample building phase (no enforcement)
    sample_building_threshold: int = 30   # Closes needed before enforcement
    evaluation_threshold: int = 60        # Closes needed for full enforcement


# Default thresholds instance
DEFAULT_THRESHOLDS = GovernanceThresholds()


@dataclass
class GovernanceDecision:
    """Result of auto-governance evaluation"""
    allow_core: bool
    action: str  # "promote", "maintain", "demote", "quarantine", "sample_building"
    reason: str
    confidence: float  # 0-1, how confident we are in this decision
    metadata: Dict[str, Any]


def evaluate_core_eligibility(
    symbol: str,
    pf_7d: Optional[float],
    pf_30d: Optional[float],
    closes_7d: int,
    closes_30d: int,
    current_allow_core: bool,
    quarantined: bool,
    thresholds: GovernanceThresholds = DEFAULT_THRESHOLDS,
) -> GovernanceDecision:
    """
    Evaluate whether a symbol should have CORE access.
    
    This is the ONLY function that decides CORE eligibility.
    All promotion/demotion decisions flow through here.
    
    Args:
        symbol: Symbol name (for logging)
        pf_7d: 7-day profit factor (None if insufficient data)
        pf_30d: 30-day profit factor (None if insufficient data)
        closes_7d: Number of closes in last 7 days
        closes_30d: Number of closes in last 30 days
        current_allow_core: Current CORE permission state
        quarantined: Whether symbol is currently quarantined
        thresholds: Governance thresholds to use
    
    Returns:
        GovernanceDecision with allow_core, action, reason, and metadata
    """
    metadata = {
        "pf_7d": pf_7d,
        "pf_30d": pf_30d,
        "closes_7d": closes_7d,
        "closes_30d": closes_30d,
        "current_allow_core": current_allow_core,
        "quarantined": quarantined,
    }
    
    # Phase 1: Sample building (no enforcement yet)
    if closes_7d < thresholds.sample_building_threshold:
        return GovernanceDecision(
            allow_core=True,  # Allow CORE during sample building
            action="sample_building",
            reason=f"Sample building phase: {closes_7d}/{thresholds.sample_building_threshold} closes",
            confidence=0.9,
            metadata=metadata,
        )
    
    # Phase 2: Check for quarantine conditions (most severe)
    if (
        closes_7d >= thresholds.quarantine_min_closes
        and pf_7d is not None
        and pf_7d < thresholds.quarantine_pf_7d_floor
    ):
        return GovernanceDecision(
            allow_core=False,
            action="quarantine",
            reason=f"Quarantine: PF {pf_7d:.3f} < {thresholds.quarantine_pf_7d_floor} with {closes_7d} closes",
            confidence=0.95,
            metadata=metadata,
        )
    
    # Phase 3: Check for demotion conditions
    if current_allow_core and pf_7d is not None:
        # Demote if 7d PF is below floor
        if pf_7d < thresholds.demote_pf_7d_floor:
            return GovernanceDecision(
                allow_core=False,
                action="demote",
                reason=f"Demoted: PF {pf_7d:.3f} < {thresholds.demote_pf_7d_floor}",
                confidence=0.85,
                metadata=metadata,
            )
        
        # Also demote if 30d PF is very bad (sustained underperformance)
        if pf_30d is not None and pf_30d < thresholds.demote_pf_30d_floor:
            return GovernanceDecision(
                allow_core=False,
                action="demote",
                reason=f"Demoted: 30d PF {pf_30d:.3f} < {thresholds.demote_pf_30d_floor}",
                confidence=0.80,
                metadata=metadata,
            )
    
    # Phase 4: Check for promotion conditions
    if not current_allow_core and not quarantined:
        # Promote if 7d PF meets threshold with sufficient sample
        if (
            pf_7d is not None
            and pf_7d >= thresholds.promote_min_pf_7d
            and closes_7d >= thresholds.promote_min_closes_7d
        ):
            # Extra confidence boost if 30d PF is also good
            confidence = 0.85
            if pf_30d is not None and pf_30d >= 1.0:
                confidence = 0.95
            
            return GovernanceDecision(
                allow_core=True,
                action="promote",
                reason=f"Promoted: PF {pf_7d:.3f} >= {thresholds.promote_min_pf_7d} with {closes_7d} closes",
                confidence=confidence,
                metadata=metadata,
            )
    
    # Phase 5: Maintain current state
    pf_display = f"{pf_7d:.3f}" if pf_7d is not None else "N/A"
    
    if current_allow_core:
        return GovernanceDecision(
            allow_core=True,
            action="maintain",
            reason=f"Maintaining CORE: PF {pf_display} above demotion threshold",
            confidence=0.90,
            metadata=metadata,
        )
    else:
        return GovernanceDecision(
            allow_core=False,
            action="maintain",
            reason=f"Not yet eligible: PF {pf_display} below {thresholds.promote_min_pf_7d}",
            confidence=0.90,
            metadata=metadata,
        )


def apply_governance_to_policy(
    policy: Dict[str, Any],
    symbol: str,
    thresholds: GovernanceThresholds = DEFAULT_THRESHOLDS,
) -> Tuple[Dict[str, Any], GovernanceDecision]:
    """
    Apply auto-governance to a symbol policy dict.
    
    This is the main entry point called by symbol_state_builder.
    
    Args:
        policy: The policy dict being built for a symbol
        symbol: Symbol name
        thresholds: Governance thresholds to use
    
    Returns:
        (updated_policy, decision) tuple
    """
    # Extract metrics from policy
    pf_7d = policy.get("pf_7d")
    pf_30d = policy.get("pf_30d")
    closes_7d = policy.get("n_closes_7d", 0)
    closes_30d = policy.get("n_closes_30d", 0)
    current_allow_core = policy.get("allow_core", False)
    quarantined = policy.get("quarantined", False)
    
    # Evaluate
    decision = evaluate_core_eligibility(
        symbol=symbol,
        pf_7d=pf_7d,
        pf_30d=pf_30d,
        closes_7d=closes_7d,
        closes_30d=closes_30d,
        current_allow_core=current_allow_core,
        quarantined=quarantined,
        thresholds=thresholds,
    )
    
    # Apply decision to policy
    policy["allow_core"] = decision.allow_core
    
    # Update reasons
    reasons = policy.get("reasons", {})
    reasons["auto_governance"] = decision.reason
    reasons["governance_action"] = decision.action
    policy["reasons"] = reasons
    
    # Log significant changes
    if decision.action in ("promote", "demote", "quarantine"):
        print(f"AUTO_GOVERNANCE: {symbol} {decision.action.upper()} - {decision.reason}")
    
    return policy, decision


def get_governance_summary(states: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Generate a summary of current governance state.
    Useful for dashboards and debugging.
    """
    symbols_by_action = {
        "core": [],
        "promoted": [],
        "demoted": [],
        "quarantined": [],
        "sample_building": [],
        "not_eligible": [],
    }
    
    total_core_pf = 0.0
    core_count = 0
    
    for symbol, policy in states.items():
        allow_core = policy.get("allow_core", False)
        quarantined = policy.get("quarantined", False)
        pf_7d = policy.get("pf_7d")
        closes_7d = policy.get("n_closes_7d", 0)
        action = policy.get("reasons", {}).get("governance_action", "unknown")
        
        if quarantined:
            symbols_by_action["quarantined"].append(symbol)
        elif allow_core:
            symbols_by_action["core"].append(symbol)
            if pf_7d is not None:
                total_core_pf += pf_7d
                core_count += 1
        elif closes_7d < DEFAULT_THRESHOLDS.sample_building_threshold:
            symbols_by_action["sample_building"].append(symbol)
        else:
            symbols_by_action["not_eligible"].append(symbol)
    
    avg_core_pf = total_core_pf / core_count if core_count > 0 else None
    
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "core_symbols": symbols_by_action["core"],
        "core_count": len(symbols_by_action["core"]),
        "avg_core_pf": avg_core_pf,
        "quarantined_symbols": symbols_by_action["quarantined"],
        "sample_building_symbols": symbols_by_action["sample_building"],
        "not_eligible_symbols": symbols_by_action["not_eligible"],
        "thresholds": {
            "promote_min_pf_7d": DEFAULT_THRESHOLDS.promote_min_pf_7d,
            "demote_pf_7d_floor": DEFAULT_THRESHOLDS.demote_pf_7d_floor,
            "quarantine_pf_7d_floor": DEFAULT_THRESHOLDS.quarantine_pf_7d_floor,
        },
    }

