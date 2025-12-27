"""
Drift Detector - Module 7 (Drift Detection System)

Detects when trading edge is degrading by analyzing recent trade performance.
"""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import math


@dataclass
class DriftState:
    """State of drift detection."""
    pf_local: float
    drift_score: float  # 0 = stable/good, 1 = very bad
    confidence_return_corr: Optional[float]


def compute_drift(
    trades: List[Dict[str, Any]],
    window: int = 100,
) -> DriftState:
    """
    Compute PF over the last `window` trades, correlation between
    confidence and returns, and an overall drift score in [0, 1].
    
    Args:
        trades: List of trade dicts with at least "return" (or "pnl") and "confidence"
        window: Number of recent trades to analyze
    
    Returns:
        DriftState with pf_local, drift_score, confidence_return_corr
    """
    # Slice last window trades
    recent_trades = trades[-window:] if len(trades) > window else trades
    
    if len(recent_trades) == 0:
        return DriftState(
            pf_local=0.0,
            drift_score=1.0,  # No trades = bad state
            confidence_return_corr=None,
        )
    
    # Extract returns and confidence
    returns = []
    confidences = []
    
    for trade in recent_trades:
        # Try multiple keys for return/pnl
        ret = trade.get("return") or trade.get("pnl") or trade.get("pct")
        conf = trade.get("confidence")
        
        if ret is not None:
            try:
                ret_val = float(ret)
                returns.append(ret_val)
                if conf is not None:
                    try:
                        confidences.append(float(conf))
                    except (TypeError, ValueError):
                        pass
            except (TypeError, ValueError):
                pass
    
    # Compute PF_local
    positive_returns = [r for r in returns if r > 0]
    negative_returns = [r for r in returns if r < 0]
    
    gross_win = sum(positive_returns) if positive_returns else 0.0
    gross_loss = abs(sum(negative_returns)) if negative_returns else 0.0
    
    if gross_loss == 0:
        pf_local = 999.0 if gross_win > 0 else 0.0
    else:
        pf_local = gross_win / gross_loss
    
    # Compute confidence-return correlation
    confidence_return_corr = None
    if len(confidences) == len(returns) and len(returns) >= 2:
        try:
            # Simple correlation calculation
            mean_conf = sum(confidences) / len(confidences)
            mean_ret = sum(returns) / len(returns)
            
            cov = sum((confidences[i] - mean_conf) * (returns[i] - mean_ret) 
                     for i in range(len(returns))) / len(returns)
            
            var_conf = sum((c - mean_conf) ** 2 for c in confidences) / len(confidences)
            var_ret = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
            
            if var_conf > 0 and var_ret > 0:
                correlation = cov / math.sqrt(var_conf * var_ret)
                confidence_return_corr = correlation
        except Exception:
            pass
    
    # Compute drift_score
    # Target PF: 1.0 (break-even minimum)
    pf_target = 1.0
    pf_good = min(1.5, max(0.0, pf_local / pf_target)) / 1.5  # Normalize to [0, 1]
    
    # Correlation goodness: positive correlation is good
    if confidence_return_corr is not None:
        corr_good = (confidence_return_corr + 1.0) / 2.0  # Map [-1, 1] to [0, 1]
    else:
        corr_good = 0.5  # Neutral if no correlation data
    
    # Combine: drift increases when PF is low or correlation is poor
    drift_raw = 1.0 - (0.5 * pf_good + 0.5 * corr_good)
    drift_score = max(0.0, min(1.0, drift_raw))
    
    return DriftState(
        pf_local=pf_local,
        drift_score=drift_score,
        confidence_return_corr=confidence_return_corr,
    )

