"""
Risk Auto-Scaler - Position sizing based on PF, drawdown, edge, volatility, confidence
"""

from dataclasses import dataclass


@dataclass
class RiskContext:
    pf_local: float
    drawdown: float     # 0.15 for -15%
    edge: float         # expected return for this regime/conf
    volatility: float   # 0.0–1.0 normalized
    confidence: float   # 0.0–1.0


def compute_risk_multiplier(ctx: RiskContext) -> float:
    m = 1.0

    # PF-based scaling
    if ctx.pf_local > 1.2:
        m *= 1.2
    elif ctx.pf_local > 1.1:
        m *= 1.1
    elif ctx.pf_local < 0.95:
        m *= 0.7

    # Drawdown clamp
    if ctx.drawdown > 0.2:
        m *= 0.5
    elif ctx.drawdown > 0.1:
        m *= 0.7

    # Edge scaling
    if ctx.edge > 0.001:
        m *= 1.1
    elif ctx.edge < 0.0:
        m *= 0.8

    # Volatility scaling (high vol → smaller)
    if ctx.volatility > 0.8:
        m *= 0.6
    elif ctx.volatility > 0.5:
        m *= 0.8

    # Confidence gating
    if ctx.confidence < 0.5:
        m *= 0.7
    elif ctx.confidence > 0.8:
        m *= 1.1

    return max(0.2, min(m, 2.0))


