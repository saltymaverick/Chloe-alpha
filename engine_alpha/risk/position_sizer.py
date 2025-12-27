"""
Position Sizer (Confidence-Weighted)
------------------------------------

Computes notional USD for PAPER exploit trades based on:
- Confidence level
- PF validity score
- Policy level
- Tier
- Capital mode

Safety:
- PAPER-only
- Restrictive-only (never increases risk beyond caps)
- Returns 0 if capital_mode != "normal"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, Optional


@dataclass
class SizingResult:
    """Result of position sizing calculation."""
    notional_usd: float
    raw_notional_usd: float
    confidence_mult: float
    validity_mult: float
    policy_mult: float
    tier_mult: float
    reason: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "notional_usd": self.notional_usd,
            "raw_notional_usd": self.raw_notional_usd,
            "confidence_mult": self.confidence_mult,
            "validity_mult": self.validity_mult,
            "policy_mult": self.policy_mult,
            "tier_mult": self.tier_mult,
            "reason": self.reason,
        }


def size_notional_usd(
    symbol: str,
    equity_usd: float,
    confidence: float,
    pf_validity: float,
    policy_level: str,
    tier: str,
    capital_mode: str,
    base_risk_bps: float = 10.0,  # 0.10% default
    max_notional_usd: float = 100.0,
    min_notional_usd: float = 5.0,
) -> SizingResult:
    """
    Compute notional USD for a PAPER exploit trade.
    
    Args:
        symbol: Trading symbol
        equity_usd: Total equity in USD
        confidence: Confidence level [0, 1]
        pf_validity: PF validity score [0, 1]
        policy_level: Policy level ("full", "reduced", "blocked")
        tier: Tier ("tier1", "tier2", "tier3")
        capital_mode: Capital protection mode ("normal", "de_risk", "halt_new_entries")
        base_risk_bps: Base risk in basis points (default: 10 bps = 0.10%)
        max_notional_usd: Maximum notional cap in USD
        min_notional_usd: Minimum notional floor in USD
    
    Returns:
        SizingResult with notional and multipliers
    """
    # Hard gate: capital mode must be normal
    if capital_mode != "normal":
        return SizingResult(
            notional_usd=0.0,
            raw_notional_usd=0.0,
            confidence_mult=0.0,
            validity_mult=0.0,
            policy_mult=0.0,
            tier_mult=0.0,
            reason=f"capital_mode={capital_mode} (not 'normal')",
        )
    
    # Hard gate: policy blocked
    if policy_level == "blocked":
        return SizingResult(
            notional_usd=0.0,
            raw_notional_usd=0.0,
            confidence_mult=0.0,
            validity_mult=0.0,
            policy_mult=0.0,
            tier_mult=0.0,
            reason=f"policy_level=blocked",
        )
    
    # Confidence multiplier: clamp(0.25 + 0.75*confidence, 0.25, 1.0)
    confidence_mult = max(0.25, min(1.0, 0.25 + 0.75 * confidence))
    
    # Validity multiplier: clamp(pf_validity, 0.0, 1.0)
    validity_mult = max(0.0, min(1.0, pf_validity))
    
    # Policy multiplier
    policy_mult_map = {
        "full": 1.0,
        "reduced": 0.6,
        "blocked": 0.0,
    }
    policy_mult = policy_mult_map.get(policy_level, 0.0)
    
    # Tier multiplier
    tier_mult_map = {
        "tier1": 1.0,
        "tier2": 0.8,
        "tier3": 0.4,
    }
    tier_mult = tier_mult_map.get(tier, 0.4)
    
    # Compute raw notional
    base_notional = equity_usd * (base_risk_bps / 10000.0)
    raw_notional_usd = base_notional * confidence_mult * validity_mult * policy_mult * tier_mult
    
    # Clamp to [min_notional_usd, max_notional_usd]
    notional_usd = max(min_notional_usd, min(max_notional_usd, raw_notional_usd))
    
    # Build reason string
    reason_parts = []
    if confidence_mult < 1.0:
        reason_parts.append(f"conf={confidence:.2f}")
    if validity_mult < 1.0:
        reason_parts.append(f"validity={pf_validity:.2f}")
    if policy_mult < 1.0:
        reason_parts.append(f"policy={policy_level}")
    if tier_mult < 1.0:
        reason_parts.append(f"tier={tier}")
    if notional_usd == max_notional_usd:
        reason_parts.append("capped_at_max")
    if notional_usd == min_notional_usd:
        reason_parts.append("floored_at_min")
    
    reason = "sized" + (": " + ", ".join(reason_parts) if reason_parts else "")
    
    return SizingResult(
        notional_usd=notional_usd,
        raw_notional_usd=raw_notional_usd,
        confidence_mult=confidence_mult,
        validity_mult=validity_mult,
        policy_mult=policy_mult,
        tier_mult=tier_mult,
        reason=reason,
    )


def compute_position_size(
    symbol: str,
    risk_inputs: Dict[str, Any],
) -> tuple[float, str]:
    """
    Compute position size for risk snapshot (compatibility wrapper).
    
    This is a compatibility wrapper for tools/run_risk_snapshot.py.
    It adapts the risk_inputs dict to size_notional_usd() parameters.
    
    Args:
        symbol: Trading symbol
        risk_inputs: Dict with keys:
            - tier: str ("tier1", "tier2", "tier3")
            - confidence: float [0, 1]
            - exploration_pf: float (optional)
            - normal_pf: float (optional)
            - ... (other fields ignored for sizing)
    
    Returns:
        (notional_usd, reason_string)
    """
    # Extract inputs with defaults
    tier = risk_inputs.get("tier", "tier3")
    confidence = risk_inputs.get("confidence", 0.7)
    
    # Use exploration_pf if available, else normal_pf, else default
    exploration_pf = risk_inputs.get("exploration_pf")
    normal_pf = risk_inputs.get("normal_pf")
    pf_validity = 1.0  # Default
    
    if exploration_pf is not None:
        # Convert PF to validity score: PF > 1.0 = valid, else scale down
        pf_validity = max(0.0, min(1.0, (exploration_pf - 0.9) / 0.1)) if exploration_pf < 1.0 else 1.0
    elif normal_pf is not None:
        pf_validity = max(0.0, min(1.0, (normal_pf - 0.9) / 0.1)) if normal_pf < 1.0 else 1.0
    
    # Policy level (default to "full" for risk snapshot)
    policy_level = risk_inputs.get("policy_level", "full")
    
    # Capital mode (default to "normal")
    capital_mode = risk_inputs.get("capital_mode", "normal")
    
    # Default equity (for PAPER mode)
    equity_usd = risk_inputs.get("equity_usd", 10000.0)
    
    # Call the actual sizing function
    result = size_notional_usd(
        symbol=symbol,
        equity_usd=equity_usd,
        confidence=confidence,
        pf_validity=pf_validity,
        policy_level=policy_level,
        tier=tier,
        capital_mode=capital_mode,
    )
    
    return result.notional_usd, result.reason


__all__ = ["size_notional_usd", "SizingResult", "compute_position_size"]
