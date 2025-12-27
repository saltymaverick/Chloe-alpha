"""
Regime-Specific Promotion Analysis
Enhanced promotion evaluation that considers performance by market regime.
"""
import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
import dateutil.parser

from engine_alpha.core.paths import REPORTS
from engine_alpha.reflect.promotion_filters import is_promo_sample_close


def analyze_regime_performance(trades: List[Dict[str, Any]], lookback_days: int = 7) -> Dict[str, Dict[str, Any]]:
    """
    Analyze trading performance broken down by market regime.

    Args:
        trades: List of trade events
        lookback_days: Days to look back from most recent trade

    Returns:
        Dict mapping regime -> performance metrics
    """
    if not trades:
        return {}

    # Find cutoff time
    latest_trade_time = None
    for trade in trades:
        if trade.get('ts'):
            try:
                ts = dateutil.parser.parse(trade['ts'].replace('Z', '+00:00'))
                if latest_trade_time is None or ts > latest_trade_time:
                    latest_trade_time = ts
            except:
                continue

    if not latest_trade_time:
        return {}

    cutoff_time = latest_trade_time - timedelta(days=lookback_days)

    # Group trades by regime
    regime_trades = defaultdict(list)

    for trade in trades:
        if trade.get('type') != 'close':
            continue

        # Check timestamp
        if trade.get('ts'):
            try:
                ts = dateutil.parser.parse(trade['ts'].replace('Z', '+00:00'))
                if ts < cutoff_time:
                    continue
            except:
                continue

        # Check if it's a promotion sample
        if not is_promo_sample_close(trade):
            continue

        regime = trade.get('regime', 'unknown')
        regime_trades[regime].append(trade)

    # Calculate performance by regime
    regime_performance = {}

    for regime, reg_trades in regime_trades.items():
        if not reg_trades:
            continue

        # Calculate metrics
        wins = [t for t in reg_trades if (t.get('pct') or 0) > 0]
        losses = [t for t in reg_trades if (t.get('pct') or 0) < 0]
        scratches = [t for t in reg_trades if abs(t.get('pct') or 0) < 1e-6]

        total_trades = len(reg_trades)
        win_rate = len(wins) / total_trades if total_trades > 0 else 0

        # P&L calculations
        gross_profit = sum(t.get('pct', 0) for t in wins)
        gross_loss = abs(sum(t.get('pct', 0) for t in losses))
        net_pnl = gross_profit - gross_loss

        pf = gross_profit / gross_loss if gross_loss > 0 else float('inf') if gross_profit > 0 else 0

        # Average return
        avg_return = sum(t.get('pct', 0) for t in reg_trades) / total_trades if total_trades > 0 else 0

        # Max drawdown (simplified - just max single loss)
        max_drawdown = min(t.get('pct', 0) for t in reg_trades) if reg_trades else 0

        regime_performance[regime] = {
            'n_closes': total_trades,
            'wins': len(wins),
            'losses': len(losses),
            'scratches': len(scratches),
            'win_rate': win_rate,
            'pf': pf,
            'gross_profit': gross_profit,
            'gross_loss': gross_loss,
            'net_pnl': net_pnl,
            'avg_return': avg_return,
            'max_drawdown': max_drawdown,
            'sample_quality': _calculate_sample_quality(reg_trades)
        }

    return regime_performance


def _calculate_sample_quality(trades: List[Dict[str, Any]]) -> float:
    """
    Calculate sample quality score based on trade characteristics.
    Higher scores indicate more reliable samples.
    """
    if not trades:
        return 0.0

    quality_score = 0.0

    # Prefer trades with meaningful hold times (not instant exits)
    meaningful_holds = sum(1 for t in trades if t.get('hold_time_minutes', 0) > 5)
    quality_score += (meaningful_holds / len(trades)) * 0.3

    # Prefer trades with diverse exit reasons (not all same exit type)
    exit_reasons = set(t.get('exit_reason') for t in trades if t.get('exit_reason'))
    diversity_score = min(len(exit_reasons) / 3.0, 1.0)  # Cap at 3 different exit types
    quality_score += diversity_score * 0.4

    # Prefer trades with non-zero P&L (avoid all scratches)
    non_scratch = sum(1 for t in trades if abs(t.get('pct', 0)) > 1e-6)
    non_scratch_ratio = non_scratch / len(trades) if trades else 0
    quality_score += non_scratch_ratio * 0.3

    return quality_score


def generate_regime_specific_promotion_advice(
    base_metrics: Dict[str, Any],
    regime_performance: Dict[str, Dict[str, Any]],
    symbol: str,
    current_action: str
) -> Dict[str, Any]:
    """
    Generate promotion advice that considers regime-specific performance.

    Args:
        base_metrics: Base promotion metrics (global performance)
        regime_performance: Performance broken down by regime
        symbol: Symbol being evaluated
        current_action: Current promotion action (hold/promote/demote)

    Returns:
        Enhanced promotion advice with regime analysis
    """
    advice = {
        'symbol': symbol,
        'current_action': current_action,
        'regime_analysis': {},
        'regime_specific_recommendation': current_action,
        'regime_confidence': 0.5,
        'regime_factors': []
    }

    if not regime_performance:
        advice['regime_factors'].append('insufficient_regime_data')
        return advice

    # Analyze each regime
    regime_scores = {}
    total_samples = sum(reg_perf['n_closes'] for reg_perf in regime_performance.values())

    for regime, reg_perf in regime_performance.items():
        if reg_perf['n_closes'] < 5:  # Minimum sample size
            continue

        # Calculate regime-specific promotion score
        score = _calculate_regime_promotion_score(reg_perf, base_metrics)
        regime_scores[regime] = score

        advice['regime_analysis'][regime] = {
            'performance': reg_perf,
            'promotion_score': score,
            'recommendation': _regime_score_to_action(score),
            'confidence': min(reg_perf['n_closes'] / 50.0, 1.0)  # Confidence based on sample size
        }

    # Determine overall regime-specific recommendation
    if regime_scores:
        # Weight by sample size and performance
        weighted_scores = {}
        for regime, score in regime_scores.items():
            weight = regime_performance[regime]['n_closes'] / total_samples
            weighted_scores[regime] = score * weight

        overall_score = sum(weighted_scores.values())

        # Determine if regime analysis changes the recommendation
        regime_recommendation = _overall_score_to_action(overall_score)

        if regime_recommendation != current_action:
            advice['regime_specific_recommendation'] = regime_recommendation
            advice['regime_factors'].append(f'regime_analysis_suggests_{regime_recommendation}')
            advice['regime_confidence'] = min(sum(reg_perf['sample_quality'] for reg_perf in regime_performance.values()) / len(regime_performance), 1.0)

    return advice


def _calculate_regime_promotion_score(reg_perf: Dict[str, Any], base_metrics: Dict[str, Any]) -> float:
    """
    Calculate promotion score for a specific regime.
    Returns value between -1 (demote) and +1 (promote).
    """
    score = 0.0

    # PF relative to baseline
    base_pf = base_metrics.get('pf', 1.0)
    reg_pf = reg_perf.get('pf', 1.0)

    if reg_pf > base_pf * 1.2:  # Significantly better
        score += 0.4
    elif reg_pf > base_pf * 1.05:  # Moderately better
        score += 0.2
    elif reg_pf < base_pf * 0.8:  # Significantly worse
        score -= 0.4
    elif reg_pf < base_pf * 0.95:  # Moderately worse
        score -= 0.2

    # Win rate
    win_rate = reg_perf.get('win_rate', 0.5)
    if win_rate > 0.6:
        score += 0.3
    elif win_rate < 0.4:
        score -= 0.3

    # Sample quality
    sample_quality = reg_perf.get('sample_quality', 0.5)
    score += (sample_quality - 0.5) * 0.4  # ±0.2 based on quality

    # Sample size (prefer more data)
    sample_size = reg_perf.get('n_closes', 0)
    if sample_size > 100:
        score += 0.1
    elif sample_size < 20:
        score -= 0.1

    return max(-1.0, min(1.0, score))  # Clamp to [-1, 1]


def _regime_score_to_action(score: float) -> str:
    """Convert regime score to action."""
    if score > 0.3:
        return 'promote'
    elif score < -0.3:
        return 'demote'
    else:
        return 'hold'


def _overall_score_to_action(score: float) -> str:
    """Convert overall regime score to action."""
    if score > 0.2:
        return 'promote'
    elif score < -0.2:
        return 'demote'
    else:
        return 'hold'
