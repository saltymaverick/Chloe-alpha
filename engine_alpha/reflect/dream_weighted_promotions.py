"""
Dream-Weighted Promotion System
Use Dream mode simulation results to weight real promotion decisions.
"""
import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
import dateutil.parser

from engine_alpha.core.paths import REPORTS


class DreamWeightedPromoter:
    """Weight promotion decisions using Dream mode simulation results."""

    def __init__(self):
        self.dream_output_path = REPORTS / "gpt" / "dream_output.json"
        self.dream_log_path = REPORTS / "gpt" / "dream_log.jsonl"

    def load_dream_results(self, lookback_days: int = 30) -> Dict[str, Any]:
        """
        Load and analyze Dream mode simulation results.

        Args:
            lookback_days: How far back to look for dream results

        Returns:
            Analyzed dream performance data
        """
        dream_data = self._load_dream_output()
        dream_logs = self._load_dream_logs(lookback_days)

        return self._analyze_dream_performance(dream_data, dream_logs)

    def _load_dream_output(self) -> Dict[str, Any]:
        """Load dream output JSON."""
        if not self.dream_output_path.exists():
            return {}

        try:
            return json.loads(self.dream_output_path.read_text())
        except Exception:
            return {}

    def _load_dream_logs(self, lookback_days: int) -> List[Dict[str, Any]]:
        """Load dream simulation logs."""
        if not self.dream_log_path.exists():
            return []

        cutoff_time = datetime.now() - timedelta(days=lookback_days)
        logs = []

        try:
            with open(self.dream_log_path, 'r') as f:
                for line in f:
                    try:
                        log_entry = json.loads(line.strip())
                        if log_entry.get('timestamp'):
                            ts = dateutil.parser.parse(log_entry['timestamp'])
                            if ts >= cutoff_time:
                                logs.append(log_entry)
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass

        return logs

    def _analyze_dream_performance(self, dream_data: Dict[str, Any], dream_logs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze dream performance data."""
        analysis = {
            'simulation_count': len(dream_logs),
            'symbol_performance': defaultdict(dict),
            'strategy_effectiveness': {},
            'confidence_scores': {},
            'dream_weight_available': len(dream_logs) > 0
        }

        if not dream_logs:
            return analysis

        # Analyze per-symbol performance
        for log in dream_logs:
            symbol = log.get('symbol')
            if not symbol:
                continue

            strategy = log.get('strategy', 'unknown')
            pnl = log.get('projected_pnl', 0)
            confidence = log.get('confidence', 0.5)

            if symbol not in analysis['symbol_performance']:
                analysis['symbol_performance'][symbol] = {
                    'total_simulations': 0,
                    'strategies_tested': set(),
                    'avg_projected_pnl': 0,
                    'best_strategy': None,
                    'best_pnl': float('-inf'),
                    'avg_confidence': 0
                }

            perf = analysis['symbol_performance'][symbol]
            perf['total_simulations'] += 1
            perf['strategies_tested'].add(strategy)
            perf['avg_projected_pnl'] = (
                (perf['avg_projected_pnl'] * (perf['total_simulations'] - 1)) + pnl
            ) / perf['total_simulations']
            perf['avg_confidence'] = (
                (perf['avg_confidence'] * (perf['total_simulations'] - 1)) + confidence
            ) / perf['total_simulations']

            if pnl > perf['best_pnl']:
                perf['best_pnl'] = pnl
                perf['best_strategy'] = strategy

            perf['strategies_tested'] = list(perf['strategies_tested'])

        # Calculate confidence scores
        for symbol, perf in analysis['symbol_performance'].items():
            # Confidence based on simulation count and consistency
            sim_count_confidence = min(perf['total_simulations'] / 20.0, 1.0)

            # Confidence based on positive projections
            pnl_confidence = 1.0 if perf['avg_projected_pnl'] > 0 else 0.3

            # Combined confidence
            analysis['confidence_scores'][symbol] = (sim_count_confidence * 0.6) + (pnl_confidence * 0.4)

        return analysis

    def calculate_dream_weighted_score(
        self,
        symbol: str,
        real_performance: Dict[str, Any],
        dream_analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Calculate dream-weighted promotion score.

        Args:
            symbol: Symbol to evaluate
            real_performance: Real trading performance metrics
            dream_analysis: Dream simulation analysis

        Returns:
            Dream-weighted promotion analysis
        """
        result = {
            'symbol': symbol,
            'dream_available': False,
            'dream_weight': 0.0,
            'weighted_score': 0.0,
            'real_performance': real_performance,
            'dream_insights': {},
            'recommendation': 'hold',
            'confidence': 0.0
        }

        if not dream_analysis.get('dream_weight_available', False):
            return result

        symbol_dream = dream_analysis.get('symbol_performance', {}).get(symbol)
        if not symbol_dream:
            return result

        result['dream_available'] = True

        # Calculate dream weight based on confidence and sample size
        dream_confidence = dream_analysis.get('confidence_scores', {}).get(symbol, 0.0)
        result['dream_weight'] = dream_confidence

        # Calculate base real performance score
        real_score = self._calculate_real_performance_score(real_performance)

        # Calculate dream-projected score
        dream_score = self._calculate_dream_projected_score(symbol_dream)

        # Weight the scores
        result['weighted_score'] = (real_score * (1 - result['dream_weight'])) + (dream_score * result['dream_weight'])

        # Generate dream insights
        result['dream_insights'] = {
            'simulations_run': symbol_dream.get('total_simulations', 0),
            'avg_projected_pnl': symbol_dream.get('avg_projected_pnl', 0),
            'best_strategy': symbol_dream.get('best_strategy'),
            'strategies_tested': symbol_dream.get('strategies_tested', []),
            'dream_confidence': dream_confidence
        }

        # Determine recommendation
        if result['weighted_score'] > 0.6:
            result['recommendation'] = 'promote'
        elif result['weighted_score'] < 0.3:
            result['recommendation'] = 'demote'
        else:
            result['recommendation'] = 'hold'

        result['confidence'] = min(dream_confidence + 0.3, 1.0)  # Boost confidence with dream data

        return result

    def _calculate_real_performance_score(self, real_perf: Dict[str, Any]) -> float:
        """Calculate performance score from real trading data."""
        score = 0.0

        # PF contribution
        pf = real_perf.get('pf', 1.0)
        if pf > 1.5:
            score += 0.4
        elif pf > 1.2:
            score += 0.2
        elif pf < 0.8:
            score -= 0.3

        # Win rate contribution
        win_rate = real_perf.get('win_rate', 0.5)
        score += (win_rate - 0.5) * 0.6  # ±0.3

        # Sample size contribution
        sample_size = real_perf.get('n_closes', 0)
        if sample_size > 50:
            score += 0.1
        elif sample_size < 10:
            score -= 0.2

        return max(0.0, min(1.0, score))

    def _calculate_dream_projected_score(self, dream_perf: Dict[str, Any]) -> float:
        """Calculate projected performance score from dream simulations."""
        score = 0.5  # Neutral starting point

        # Projected P&L contribution
        avg_pnl = dream_perf.get('avg_projected_pnl', 0)
        if avg_pnl > 0.005:  # >0.5% projected
            score += 0.3
        elif avg_pnl < -0.005:  # <-0.5% projected
            score -= 0.3

        # Strategy diversity contribution
        strategies_tested = len(dream_perf.get('strategies_tested', []))
        if strategies_tested > 3:
            score += 0.1
        elif strategies_tested == 1:
            score -= 0.1

        # Best P&L vs average
        best_pnl = dream_perf.get('best_pnl', 0)
        if best_pnl > avg_pnl * 1.5:
            score += 0.1  # Good upside potential

        return max(0.0, min(1.0, score))


def generate_dream_weighted_promotion_advice(
    dream_analysis: Dict[str, Any],
    real_performance: Dict[str, Any],
    symbol: str
) -> Dict[str, Any]:
    """
    Generate promotion advice weighted by dream simulation results.

    Args:
        dream_analysis: Dream simulation analysis
        real_performance: Real trading performance
        symbol: Symbol being evaluated

    Returns:
        Dream-weighted promotion advice
    """
    promoter = DreamWeightedPromoter()
    dream_weighted = promoter.calculate_dream_weighted_score(symbol, real_performance, dream_analysis)

    advice = {
        'symbol': symbol,
        'dream_weighted_analysis': dream_weighted,
        'dream_available': dream_weighted['dream_available'],
        'dream_weight': dream_weighted['dream_weight'],
        'weighted_score': dream_weighted['weighted_score'],
        'dream_based_recommendation': dream_weighted['recommendation'],
        'dream_confidence': dream_weighted['confidence'],
        'dream_insights': dream_weighted['dream_insights'],
        'factors': []
    }

    if dream_weighted['dream_available']:
        advice['factors'].append(f"dream_weight_{dream_weighted['dream_weight']:.2f}")
        advice['factors'].append(f"weighted_score_{dream_weighted['weighted_score']:.2f}")

        if dream_weighted['dream_weight'] > 0.6:
            advice['factors'].append("strong_dream_confidence")
        elif dream_weighted['dream_weight'] < 0.3:
            advice['factors'].append("weak_dream_confidence")
    else:
        advice['factors'].append("no_dream_data_available")

    return advice
