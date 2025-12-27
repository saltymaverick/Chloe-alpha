"""
Enhanced Promotion Advice Generator
Integrates regime-specific, signal-attributed, and dream-weighted promotion analysis.
"""
import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import dateutil.parser

from engine_alpha.core.paths import REPORTS
from engine_alpha.reflect.regime_promotion_analyzer import (
    analyze_regime_performance,
    generate_regime_specific_promotion_advice
)
from engine_alpha.reflect.signal_attribution_tracker import (
    SignalAttributionTracker,
    generate_signal_attributed_promotion_advice
)
from engine_alpha.reflect.dream_weighted_promotions import (
    DreamWeightedPromoter,
    generate_dream_weighted_promotion_advice
)


class EnhancedPromotionAdvisor:
    """Generate comprehensive promotion advice with multiple analysis layers."""

    def __init__(self):
        self.regime_analyzer = None
        self.signal_tracker = SignalAttributionTracker()
        self.dream_promoter = DreamWeightedPromoter()

    def generate_comprehensive_promotion_advice(
        self,
        trades: List[Dict[str, Any]],
        lookback_days: int = 7
    ) -> Dict[str, Any]:
        """
        Generate comprehensive promotion advice with all analysis layers.

        Args:
            trades: List of trade events
            lookback_days: Days to look back for analysis

        Returns:
            Comprehensive promotion advice with all enhancements
        """
        # Load dream analysis once
        dream_analysis = self.dream_promoter.load_dream_results(lookback_days * 2)  # Longer lookback for dream

        # Group trades by symbol
        symbol_trades = defaultdict(list)
        for trade in trades:
            symbol = trade.get('symbol')
            if symbol:
                symbol_trades[symbol].append(trade)

        # Generate advice for each symbol
        symbols_advice = {}
        global_summary = {
            'total_symbols': len(symbol_trades),
            'analysis_timestamp': datetime.now(timezone.utc).isoformat(),
            'lookback_days': lookback_days,
            'features_enabled': {
                'regime_specific': True,
                'signal_attribution': True,
                'dream_weighted': dream_analysis.get('dream_weight_available', False)
            }
        }

        for symbol, sym_trades in symbol_trades.items():
            if len(sym_trades) < 5:  # Skip symbols with insufficient data
                continue

            # Perform all analyses
            regime_performance = analyze_regime_performance(sym_trades, lookback_days)
            signal_analysis = self.signal_tracker.analyze_signal_attribution(sym_trades, lookback_days)

            # Calculate base metrics for this symbol
            base_metrics = self._calculate_base_metrics(sym_trades, lookback_days)
            current_action = self._determine_current_action(base_metrics)

            # Generate enhanced advice
            regime_advice = generate_regime_specific_promotion_advice(
                base_metrics, regime_performance, symbol, current_action
            )

            signal_advice = generate_signal_attributed_promotion_advice(
                signal_analysis, base_metrics, symbol
            )

            dream_advice = generate_dream_weighted_promotion_advice(
                dream_analysis, base_metrics, symbol
            )

            # Combine all analyses into final recommendation
            final_advice = self._combine_analyses(
                symbol, base_metrics, regime_advice, signal_advice, dream_advice
            )

            symbols_advice[symbol] = final_advice

        # Generate global insights
        global_insights = self._generate_global_insights(symbols_advice, dream_analysis)

        return {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'window': {
                'lookback_days': lookback_days,
                'lookback_hours': lookback_days * 24
            },
            'global': global_summary,
            'global_insights': global_insights,
            'symbols': symbols_advice
        }

    def _calculate_base_metrics(self, trades: List[Dict[str, Any]], lookback_days: int) -> Dict[str, Any]:
        """Calculate base promotion metrics for a symbol."""
        # Filter to recent trades
        cutoff_time = datetime.now() - timedelta(days=lookback_days)
        recent_trades = []

        for trade in trades:
            if trade.get('ts'):
                try:
                    ts = dateutil.parser.parse(trade['ts'].replace('Z', '+00:00'))
                    if ts >= cutoff_time:
                        recent_trades.append(trade)
                except:
                    continue

        if not recent_trades:
            return {'n_closes': 0, 'pf': 1.0, 'win_rate': 0.0}

        # Calculate basic metrics
        closes = [t for t in recent_trades if t.get('type') == 'close' and t.get('pct') is not None]
        if not closes:
            return {'n_closes': 0, 'pf': 1.0, 'win_rate': 0.0}

        wins = [t for t in closes if t['pct'] > 0.001]
        losses = [t for t in closes if t['pct'] < -0.001]

        win_rate = len(wins) / len(closes) if closes else 0

        gross_profit = sum(t['pct'] for t in wins)
        gross_loss = abs(sum(t['pct'] for t in losses))

        pf = gross_profit / gross_loss if gross_loss > 0 else float('inf') if gross_profit > 0 else 0

        return {
            'n_closes': len(closes),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': win_rate,
            'pf': pf,
            'gross_profit': gross_profit,
            'gross_loss': gross_loss,
            'avg_return': sum(t['pct'] for t in closes) / len(closes) if closes else 0
        }

    def _determine_current_action(self, metrics: Dict[str, Any]) -> str:
        """Determine current promotion action based on base metrics."""
        if metrics['n_closes'] < 10:
            return 'insufficient_data'

        pf = metrics['pf']
        win_rate = metrics['win_rate']

        if pf > 1.2 and win_rate > 0.55:
            return 'promote'
        elif pf < 0.9 or win_rate < 0.45:
            return 'demote'
        else:
            return 'hold'

    def _combine_analyses(
        self,
        symbol: str,
        base_metrics: Dict[str, Any],
        regime_advice: Dict[str, Any],
        signal_advice: Dict[str, Any],
        dream_advice: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Combine all analyses into final promotion recommendation."""

        # Start with base action
        base_action = self._determine_current_action(base_metrics)
        confidence_scores = []
        factors = []
        recommendations = []

        # Collect recommendations from each analysis
        recommendations.append(('base', base_action, 0.5))

        if regime_advice.get('regime_specific_recommendation') != base_action:
            recommendations.append(('regime', regime_advice['regime_specific_recommendation'], regime_advice.get('regime_confidence', 0.5)))
            factors.extend(regime_advice.get('regime_factors', []))

        if signal_advice.get('signal_based_recommendations'):
            for rec in signal_advice['signal_based_recommendations']:
                if 'promote' in rec.get('type', ''):
                    recommendations.append(('signal', 'promote', signal_advice.get('attribution_confidence', 0.5)))
                elif 'avoid' in rec.get('type', ''):
                    recommendations.append(('signal', 'demote', signal_advice.get('attribution_confidence', 0.5)))
                factors.append(f"signal_{rec.get('type', 'unknown')}")

        if dream_advice.get('dream_available', False):
            recommendations.append(('dream', dream_advice['dream_based_recommendation'], dream_advice.get('dream_confidence', 0.5)))
            factors.extend(dream_advice.get('factors', []))

        # Weight the recommendations
        action_weights = defaultdict(float)
        total_weight = 0

        for source, action, confidence in recommendations:
            weight = confidence * self._get_source_weight(source)
            action_weights[action] += weight
            total_weight += weight

        # Determine final action
        if total_weight > 0:
            final_action = max(action_weights.items(), key=lambda x: x[1])[0]
        else:
            final_action = base_action

        # Calculate overall confidence
        avg_confidence = sum(conf for _, _, conf in recommendations) / len(recommendations) if recommendations else 0.5

        return {
            'symbol': symbol,
            'action': final_action,
            'confidence': avg_confidence,
            'factors': factors,
            'analyses': {
                'base': base_metrics,
                'regime': regime_advice,
                'signal': signal_advice,
                'dream': dream_advice
            },
            'recommendation_breakdown': dict(action_weights)
        }

    def _get_source_weight(self, source: str) -> float:
        """Get weight multiplier for different analysis sources."""
        weights = {
            'base': 1.0,
            'regime': 0.8,
            'signal': 0.7,
            'dream': 0.6
        }
        return weights.get(source, 0.5)

    def _generate_global_insights(self, symbols_advice: Dict[str, Any], dream_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Generate global insights across all symbols."""
        insights = {
            'total_symbols_analyzed': len(symbols_advice),
            'promotion_candidates': 0,
            'demotion_candidates': 0,
            'regime_insights': {},
            'signal_insights': {},
            'dream_coverage': 0
        }

        # Count recommendations
        for symbol_data in symbols_advice.values():
            action = symbol_data.get('action')
            if action == 'promote':
                insights['promotion_candidates'] += 1
            elif action == 'demote':
                insights['demotion_candidates'] += 1

            # Check dream coverage
            if symbol_data.get('analyses', {}).get('dream', {}).get('dream_available', False):
                insights['dream_coverage'] += 1

        # Calculate percentages
        total = insights['total_symbols_analyzed']
        if total > 0:
            insights['promotion_rate'] = insights['promotion_candidates'] / total
            insights['demotion_rate'] = insights['demotion_candidates'] / total
            insights['dream_coverage_rate'] = insights['dream_coverage'] / total

        return insights


def save_enhanced_promotion_advice(advice: Dict[str, Any], output_path: Optional[Path] = None) -> Path:
    """Save enhanced promotion advice to JSON file."""
    if output_path is None:
        output_path = REPORTS / "gpt" / "enhanced_promotion_advice.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        json.dump(advice, f, indent=2, default=str)

    return output_path


# CLI interface
if __name__ == "__main__":
    import sys
    from engine_alpha.core.data_loader import load_trades_jsonl

    # Load trades
    trades = load_trades_jsonl()
    print(f"Loaded {len(trades)} trades")

    # Generate enhanced advice
    advisor = EnhancedPromotionAdvisor()
    advice = advisor.generate_comprehensive_promotion_advice(trades)

    # Save to file
    output_path = save_enhanced_promotion_advice(advice)
    print(f"Enhanced promotion advice saved to: {output_path}")

    # Print summary
    symbols = advice.get('symbols', {})
    print(f"\nAnalysis Summary:")
    print(f"  Symbols analyzed: {len(symbols)}")
    print(f"  Promotions recommended: {sum(1 for s in symbols.values() if s.get('action') == 'promote')}")
    print(f"  Demotions recommended: {sum(1 for s in symbols.values() if s.get('action') == 'demote')}")
    print(f"  Holds recommended: {sum(1 for s in symbols.values() if s.get('action') == 'hold')}")
