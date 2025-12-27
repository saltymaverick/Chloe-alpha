"""
Signal Attribution Tracking for Promotions
Track which specific signals/triggers contribute to successful promotions.
"""
import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Set, Tuple
from datetime import datetime, timedelta
from collections import defaultdict, Counter
import dateutil.parser

from engine_alpha.core.paths import REPORTS
from engine_alpha.reflect.promotion_filters import is_promo_sample_close


class SignalAttributionTracker:
    """Track signal attribution for promotion analysis."""

    def __init__(self):
        self.attribution_data = {}
        self.signal_patterns = self._load_signal_patterns()

    def _load_signal_patterns(self) -> Dict[str, List[str]]:
        """Load signal pattern definitions for attribution."""
        return {
            'momentum': ['momentum', 'velocity', 'acceleration', 'trend_strength'],
            'mean_reversion': ['mean_rev', 'reversion', 'oversold', 'overbought', 'mr'],
            'breakout': ['breakout', 'break', 'support', 'resistance', 'level_break'],
            'volume': ['volume', 'vol_spike', 'volume_divergence'],
            'regime_adaptive': ['chop_adaptive', 'trend_adaptive', 'regime_switch'],
            'micro_signals': ['micro', 'small_edge', 'nuance', 'refinement'],
            'counterfactual': ['counterfactual', 'what_if', 'alternative_scenario'],
            'dream_weighted': ['dream', 'simulation', 'hypothetical', 'projected']
        }

    def analyze_signal_attribution(self, trades: List[Dict[str, Any]], lookback_days: int = 7) -> Dict[str, Any]:
        """
        Analyze which signals contributed to successful promotions.

        Args:
            trades: List of trade events
            lookback_days: Days to look back

        Returns:
            Signal attribution analysis
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

        # Collect successful promotion samples
        successful_trades = []
        failed_trades = []

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

            pct = trade.get('pct', 0)
            if pct > 0.001:  # Profitable trade
                successful_trades.append(trade)
            elif pct < -0.001:  # Losing trade
                failed_trades.append(trade)

        # Analyze signal attribution
        successful_signals = self._extract_signals_from_trades(successful_trades)
        failed_signals = self._extract_signals_from_trades(failed_trades)

        return {
            'successful_trades': len(successful_trades),
            'failed_trades': len(failed_trades),
            'signal_success_rates': self._calculate_signal_success_rates(
                successful_signals, failed_signals
            ),
            'top_performing_signals': self._rank_signals_by_performance(
                successful_signals, failed_signals
            ),
            'signal_clusters': self._identify_signal_clusters(successful_signals),
            'attribution_confidence': self._calculate_attribution_confidence(
                len(successful_trades), len(failed_trades)
            )
        }

    def _extract_signals_from_trades(self, trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract signal information from trades."""
        signal_data = []

        for trade in trades:
            signals = []

            # Extract from signal metadata if available
            if 'signals' in trade:
                signals.extend(trade['signals'])

            # Extract from trade metadata
            if 'signal_type' in trade:
                signals.append(trade['signal_type'])

            if 'trigger_reason' in trade:
                signals.append(trade['trigger_reason'])

            # Extract from exit reason (for closes)
            if 'exit_reason' in trade:
                signals.append(f"exit_{trade['exit_reason']}")

            # Extract from trade kind
            if 'trade_kind' in trade:
                signals.append(f"kind_{trade['trade_kind']}")

            # Extract from regime
            if 'regime' in trade:
                signals.append(f"regime_{trade['regime']}")

            # Categorize signals
            categorized_signals = self._categorize_signals(signals)

            signal_data.append({
                'trade_id': trade.get('id', f"{trade.get('symbol')}_{trade.get('ts')}"),
                'signals': signals,
                'categorized_signals': categorized_signals,
                'pnl': trade.get('pct', 0),
                'regime': trade.get('regime', 'unknown')
            })

        return signal_data

    def _categorize_signals(self, signals: List[str]) -> Dict[str, List[str]]:
        """Categorize signals into pattern groups."""
        categorized = defaultdict(list)

        for signal in signals:
            signal_lower = signal.lower()
            categorized_signal = False

            for category, patterns in self.signal_patterns.items():
                if any(pattern in signal_lower for pattern in patterns):
                    categorized[category].append(signal)
                    categorized_signal = True
                    break

            if not categorized_signal:
                categorized['other'].append(signal)

        return dict(categorized)

    def _calculate_signal_success_rates(self, successful_signals: List[Dict], failed_signals: List[Dict]) -> Dict[str, float]:
        """Calculate success rates for different signal categories."""
        successful_counts = Counter()
        failed_counts = Counter()

        # Count successful signal usage
        for trade_data in successful_signals:
            for category, signals in trade_data['categorized_signals'].items():
                successful_counts[category] += 1

        # Count failed signal usage
        for trade_data in failed_signals:
            for category, signals in trade_data['categorized_signals'].items():
                failed_counts[category] += 1

        # Calculate success rates
        success_rates = {}
        all_categories = set(successful_counts.keys()) | set(failed_counts.keys())

        for category in all_categories:
            successful = successful_counts[category]
            failed = failed_counts[category]
            total = successful + failed

            if total >= 5:  # Minimum sample size
                success_rates[category] = successful / total
            else:
                success_rates[category] = None  # Insufficient data

        return success_rates

    def _rank_signals_by_performance(self, successful_signals: List[Dict], failed_signals: List[Dict]) -> List[Dict[str, Any]]:
        """Rank individual signals by performance."""
        signal_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total_pnl': 0.0})

        # Aggregate successful signals
        for trade_data in successful_signals:
            for signals_list in trade_data['categorized_signals'].values():
                for signal in signals_list:
                    signal_stats[signal]['wins'] += 1
                    signal_stats[signal]['total_pnl'] += trade_data.get('pnl', 0)

        # Aggregate failed signals
        for trade_data in failed_signals:
            for signals_list in trade_data['categorized_signals'].values():
                for signal in signals_list:
                    signal_stats[signal]['losses'] += 1
                    signal_stats[signal]['total_pnl'] += trade_data.get('pnl', 0)

        # Calculate performance metrics
        ranked_signals = []
        for signal, stats in signal_stats.items():
            total_trades = stats['wins'] + stats['losses']
            if total_trades >= 3:  # Minimum sample size
                win_rate = stats['wins'] / total_trades
                avg_pnl = stats['total_pnl'] / total_trades

                ranked_signals.append({
                    'signal': signal,
                    'win_rate': win_rate,
                    'total_trades': total_trades,
                    'avg_pnl': avg_pnl,
                    'total_pnl': stats['total_pnl'],
                    'performance_score': (win_rate * 0.7) + (min(avg_pnl * 100, 0.3) * 0.3)  # Weighted score
                })

        # Sort by performance score
        ranked_signals.sort(key=lambda x: x['performance_score'], reverse=True)
        return ranked_signals[:20]  # Top 20 signals

    def _identify_signal_clusters(self, successful_signals: List[Dict]) -> List[Dict[str, Any]]:
        """Identify successful signal combinations."""
        clusters = []

        # Look for common signal combinations in successful trades
        for trade_data in successful_signals:
            signal_set = set()
            for signals_list in trade_data['categorized_signals'].values():
                signal_set.update(signals_list)

            if len(signal_set) >= 2:
                clusters.append({
                    'signals': sorted(signal_set),
                    'pnl': trade_data.get('pnl', 0),
                    'regime': trade_data.get('regime', 'unknown')
                })

        # Group similar clusters
        cluster_groups = defaultdict(list)
        for cluster in clusters:
            key = tuple(sorted(cluster['signals']))
            cluster_groups[key].append(cluster)

        # Find most successful combinations
        successful_clusters = []
        for signal_combo, instances in cluster_groups.items():
            if len(instances) >= 2:  # At least 2 occurrences
                avg_pnl = sum(inst['pnl'] for inst in instances) / len(instances)
                successful_clusters.append({
                    'signal_combination': list(signal_combo),
                    'occurrences': len(instances),
                    'avg_pnl': avg_pnl,
                    'total_pnl': sum(inst['pnl'] for inst in instances)
                })

        successful_clusters.sort(key=lambda x: x['avg_pnl'], reverse=True)
        return successful_clusters[:10]  # Top 10 combinations

    def _calculate_attribution_confidence(self, successful_trades: int, failed_trades: int) -> float:
        """Calculate confidence in signal attribution analysis."""
        total_trades = successful_trades + failed_trades
        if total_trades < 10:
            return 0.0  # Insufficient data

        # Confidence based on sample size and balance
        sample_confidence = min(total_trades / 100.0, 1.0)
        balance_confidence = 1.0 - abs(successful_trades - failed_trades) / total_trades

        return (sample_confidence * 0.7) + (balance_confidence * 0.3)


def generate_signal_attributed_promotion_advice(
    signal_analysis: Dict[str, Any],
    base_metrics: Dict[str, Any],
    symbol: str
) -> Dict[str, Any]:
    """
    Generate promotion advice enhanced with signal attribution.

    Args:
        signal_analysis: Signal attribution analysis results
        base_metrics: Base promotion metrics
        symbol: Symbol being evaluated

    Returns:
        Enhanced promotion advice with signal attribution
    """
    advice = {
        'symbol': symbol,
        'signal_attribution': signal_analysis,
        'top_signals': signal_analysis.get('top_performing_signals', [])[:5],
        'signal_clusters': signal_analysis.get('signal_clusters', [])[:3],
        'attribution_confidence': signal_analysis.get('attribution_confidence', 0.0),
        'signal_based_recommendations': []
    }

    # Generate signal-based recommendations
    success_rates = signal_analysis.get('signal_success_rates', {})

    # Find strong signals for this symbol
    strong_signals = [
        signal for signal, rate in success_rates.items()
        if rate and rate > 0.65 and signal_analysis.get('attribution_confidence', 0) > 0.6
    ]

    if strong_signals:
        advice['signal_based_recommendations'].append({
            'type': 'promote_strong_signals',
            'signals': strong_signals,
            'reason': f'High-performing signals detected: {", ".join(strong_signals)}'
        })

    # Find weak signals to avoid
    weak_signals = [
        signal for signal, rate in success_rates.items()
        if rate and rate < 0.35 and signal_analysis.get('attribution_confidence', 0) > 0.6
    ]

    if weak_signals:
        advice['signal_based_recommendations'].append({
            'type': 'avoid_weak_signals',
            'signals': weak_signals,
            'reason': f'Underperforming signals to avoid: {", ".join(weak_signals)}'
        })

    return advice
