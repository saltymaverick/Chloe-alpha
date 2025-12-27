#!/usr/bin/env python3
"""
Edge Half-Life Scoring - Second-Order Intelligence Layer

Models how long trading edges remain valid over time. Enables:
- Detection of decaying edges before they become losses
- Optimal timing for edge rotation
- Edge strength forecasting
- Meta-decisions about when to stop exploiting current opportunities

Key insight: Edges are perishable. Knowing when they expire is as important
as knowing when they exist.
"""

from __future__ import annotations
from typing import Dict, List, Any, Optional, Tuple, NamedTuple
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from pathlib import Path
import json
import math
from collections import defaultdict

from engine_alpha.research.pf_timeseries import _compute_pf_for_window
from engine_alpha.reflect.fair_value_gaps import fvg_detector
from engine_alpha.config.feature_flags import get_feature_registry


class EdgeMetrics(NamedTuple):
    """Core metrics for a trading edge at a point in time"""
    timestamp: datetime
    symbol: str
    pf: float  # Profit factor
    win_rate: float  # Win rate (0.0-1.0)
    expectancy: float  # Expected value per trade
    total_trades: int  # Sample size
    time_window_days: int  # Lookback window


class EdgeStrength(NamedTuple):
    """Quantified strength of a trading edge"""
    absolute_strength: float  # 0.0-1.0, how strong is this edge?
    relative_strength: float  # How strong vs symbol's historical average
    confidence: float  # Statistical confidence in the measurement
    half_life_days: float  # Estimated days until strength decays by 50%
    decay_rate: float  # Daily decay rate
    freshness_score: float  # How fresh/recent is this edge?


@dataclass
class EdgeHalfLifeTracker:
    """Tracks and models the decay of trading edges over time"""

    analysis_window_days: int = 90  # How far back to analyze edge decay
    min_samples_for_modeling: int = 20  # Minimum trades to build decay model
    edge_history_file: Path = field(default_factory=lambda: Path("reports/edge_half_life_history.jsonl"))

    def __post_init__(self):
        self.edge_history_file.parent.mkdir(parents=True, exist_ok=True)

    def analyze_edge_half_life(self, symbol: str, current_metrics: EdgeMetrics,
                              historical_trades: List[Dict[str, Any]]) -> EdgeStrength:
        """
        Analyze the half-life and current strength of a trading edge.

        Args:
            symbol: Trading symbol
            current_metrics: Current edge performance metrics
            historical_trades: Historical trade data for decay modeling

        Returns:
            Comprehensive edge strength analysis
        """

        # Calculate absolute edge strength
        absolute_strength = self._calculate_absolute_strength(current_metrics)

        # Calculate relative strength vs historical average
        relative_strength = self._calculate_relative_strength(symbol, current_metrics, historical_trades)

        # Model decay pattern and estimate half-life
        decay_model = self._model_edge_decay(symbol, historical_trades)
        half_life_days = decay_model.get('half_life_days', 30.0)
        decay_rate = decay_model.get('decay_rate', 0.02)

        # Assess statistical confidence
        confidence = self._calculate_edge_confidence(current_metrics)

        # Calculate freshness (recency bonus)
        freshness_score = self._calculate_freshness_score(current_metrics)

        edge_strength = EdgeStrength(
            absolute_strength=absolute_strength,
            relative_strength=relative_strength,
            confidence=confidence,
            half_life_days=half_life_days,
            decay_rate=decay_rate,
            freshness_score=freshness_score
        )

        # Log the analysis for future modeling
        self._log_edge_analysis(symbol, current_metrics, edge_strength, decay_model)

        return edge_strength

    def _calculate_absolute_strength(self, metrics: EdgeMetrics) -> float:
        """Calculate absolute edge strength based on performance metrics"""
        pf_score = min(1.0, max(0.0, (metrics.pf - 0.8) / 0.4))  # 0.8-1.2 maps to 0-1
        win_rate_score = metrics.win_rate  # Already 0-1
        expectancy_score = min(1.0, max(0.0, metrics.expectancy / 0.005))  # Scale expectancy

        # Weighted combination (PF most important, then win rate, then expectancy)
        strength = (0.5 * pf_score) + (0.3 * win_rate_score) + (0.2 * expectancy_score)

        # Sample size penalty for very small samples
        if metrics.total_trades < 10:
            strength *= 0.7
        elif metrics.total_trades < 30:
            strength *= 0.9

        return min(1.0, max(0.0, strength))

    def _calculate_relative_strength(self, symbol: str, current_metrics: EdgeMetrics,
                                   historical_trades: List[Dict[str, Any]]) -> float:
        """Calculate strength relative to symbol's historical performance"""
        if not historical_trades:
            return 0.5  # Neutral if no history

        # Calculate historical baseline (long-term average)
        historical_pfs = []
        window_size = 30  # 30-day windows

        # Group trades by time windows
        sorted_trades = sorted(historical_trades, key=lambda x: x.get('ts', ''))
        for i in range(0, len(sorted_trades) - window_size + 1, window_size // 2):
            window_trades = sorted_trades[i:i + window_size]
            if len(window_trades) >= 10:  # Minimum sample
                returns = [t.get('pct', 0) for t in window_trades if t.get('pct') is not None]
                if returns:
                    pf = _compute_pf_for_window(returns)
                    historical_pfs.append(pf)

        if not historical_pfs:
            return 0.5

        historical_avg_pf = sum(historical_pfs) / len(historical_pfs)
        historical_std_pf = math.sqrt(sum((pf - historical_avg_pf) ** 2 for pf in historical_pfs) / len(historical_pfs))

        if historical_std_pf == 0:
            return 0.5

        # Z-score of current PF vs historical
        z_score = (current_metrics.pf - historical_avg_pf) / historical_std_pf

        # Convert z-score to 0-1 scale (clip extreme values)
        relative_strength = 1.0 / (1.0 + math.exp(-z_score))  # Sigmoid

        return relative_strength

    def _model_edge_decay(self, symbol: str, historical_trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Model how edges decay over time using historical data"""
        if len(historical_trades) < self.min_samples_for_modeling:
            return {
                'half_life_days': 30.0,  # Default assumption
                'decay_rate': 0.02,  # 2% daily decay
                'model_type': 'default_assumption',
                'confidence': 0.3
            }

        # Group trades by time windows to see performance decay
        sorted_trades = sorted(historical_trades, key=lambda x: x.get('ts', ''))

        # Calculate rolling PF over different time windows
        window_sizes = [7, 14, 30, 60, 90]  # Days
        rolling_pfs = {}

        for window_days in window_sizes:
            window_pfs = []
            window_size_trades = window_days * 2  # Rough estimate of trades per day

            for i in range(0, len(sorted_trades) - window_size_trades + 1, window_size_trades // 4):
                window_trades = sorted_trades[i:i + window_size_trades]
                if len(window_trades) >= 10:
                    returns = [t.get('pct', 0) for t in window_trades if t.get('pct') is not None]
                    if returns:
                        pf = _compute_pf_for_window(returns)
                        window_pfs.append(pf)

            if window_pfs:
                rolling_pfs[window_days] = sum(window_pfs) / len(window_pfs)

        if not rolling_pfs:
            return {
                'half_life_days': 30.0,
                'decay_rate': 0.02,
                'model_type': 'insufficient_data',
                'confidence': 0.3
            }

        # Model decay: assume exponential decay from peak performance
        # Find the peak PF and model decay from there
        peak_pf = max(rolling_pfs.values())
        peak_window = max(rolling_pfs.keys(), key=lambda k: rolling_pfs[k])

        # Calculate decay rate by fitting exponential decay
        decay_points = []
        for window_days, pf in rolling_pfs.items():
            if pf > 0.8:  # Only consider decent performance windows
                time_from_peak = abs(window_days - peak_window)
                decay_ratio = pf / peak_pf if peak_pf > 0 else 0
                if decay_ratio > 0:
                    decay_points.append((time_from_peak, decay_ratio))

        if len(decay_points) >= 3:
            # Fit exponential decay: ratio = exp(-decay_rate * time)
            # Take log: ln(ratio) = -decay_rate * time
            try:
                # Simple linear regression on log decay
                times = [t for t, r in decay_points]
                log_ratios = [math.log(max(r, 0.01)) for t, r in decay_points]  # Avoid log(0)

                # Calculate slope (decay rate)
                n = len(times)
                sum_t = sum(times)
                sum_lr = sum(log_ratios)
                sum_t_lr = sum(t * lr for t, lr in zip(times, log_ratios))
                sum_t2 = sum(t * t for t in times)

                if n * sum_t2 - sum_t * sum_t != 0:
                    decay_rate = -(n * sum_t_lr - sum_t * sum_lr) / (n * sum_t2 - sum_t * sum_t)
                    decay_rate = max(0.001, min(0.1, decay_rate))  # Reasonable bounds

                    # Half-life: time for decay to 50% = ln(0.5) / -decay_rate
                    half_life_days = math.log(0.5) / -decay_rate

                    return {
                        'half_life_days': max(7, min(180, half_life_days)),  # 1 week to 6 months
                        'decay_rate': decay_rate,
                        'model_type': 'exponential_decay_fit',
                        'confidence': min(0.9, len(decay_points) / 10.0),
                        'peak_pf': peak_pf,
                        'data_points': len(decay_points)
                    }
            except (ValueError, ZeroDivisionError):
                pass

        # Fallback: use empirical decay patterns
        return {
            'half_life_days': 45.0,  # Conservative estimate
            'decay_rate': 0.015,  # 1.5% daily decay
            'model_type': 'empirical_fallback',
            'confidence': 0.5
        }

    def _calculate_edge_confidence(self, metrics: EdgeMetrics) -> float:
        """Calculate statistical confidence in edge measurement"""
        # Confidence based on sample size and consistency
        sample_confidence = min(1.0, metrics.total_trades / 50.0)  # 50 trades for full confidence

        # PF confidence (extreme PFs are less reliable)
        pf_confidence = 1.0 - abs(metrics.pf - 1.0) * 0.5  # Peak at PF=1.0

        # Time window confidence (longer windows more reliable)
        window_confidence = min(1.0, metrics.time_window_days / 30.0)  # 30 days for full confidence

        return (0.4 * sample_confidence) + (0.4 * pf_confidence) + (0.2 * window_confidence)

    def _calculate_freshness_score(self, metrics: EdgeMetrics) -> float:
        """Calculate how fresh/recent the edge data is"""
        # Prefer more recent data (exponential decay of age)
        hours_old = (datetime.now(timezone.utc) - metrics.timestamp).total_seconds() / 3600

        # Freshness decays exponentially with half-life of 24 hours
        decay_rate = math.log(2) / 24  # Half-life = 24 hours
        freshness = math.exp(-decay_rate * hours_old)

        return freshness

    def _log_edge_analysis(self, symbol: str, metrics: EdgeMetrics,
                          strength: EdgeStrength, decay_model: Dict[str, Any]) -> None:
        """Log edge analysis for future modeling improvement"""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "edge_metrics": {
                "pf": metrics.pf,
                "win_rate": metrics.win_rate,
                "expectancy": metrics.expectancy,
                "total_trades": metrics.total_trades,
                "time_window_days": metrics.time_window_days
            },
            "edge_strength": {
                "absolute_strength": strength.absolute_strength,
                "relative_strength": strength.relative_strength,
                "confidence": strength.confidence,
                "half_life_days": strength.half_life_days,
                "decay_rate": strength.decay_rate,
                "freshness_score": strength.freshness_score
            },
            "decay_model": decay_model
        }

        with self.edge_history_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def get_edge_health_assessment(self, symbol: str, lookback_days: int = 30) -> Dict[str, Any]:
        """Get comprehensive edge health assessment for a symbol"""
        # Load historical edge analyses
        assessments = []
        if self.edge_history_file.exists():
            cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
            with self.edge_history_file.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        if record["symbol"] == symbol:
                            record_ts = datetime.fromisoformat(record["timestamp"])
                            if record_ts >= cutoff:
                                assessments.append(record)
                    except (json.JSONDecodeError, KeyError):
                        continue

        if not assessments:
            return {
                "symbol": symbol,
                "status": "insufficient_data",
                "recommendation": "need_more_trades_for_edge_analysis"
            }

        # Analyze edge health trends
        recent_assessments = sorted(assessments[-10:], key=lambda x: x["timestamp"])  # Last 10

        strengths = [a["edge_strength"]["absolute_strength"] for a in recent_assessments]
        half_lives = [a["edge_strength"]["half_life_days"] for a in recent_assessments]
        decay_rates = [a["edge_strength"]["decay_rate"] for a in recent_assessments]

        # Trend analysis
        strength_trend = self._calculate_trend(strengths)
        half_life_trend = self._calculate_trend(half_lives)

        # Current health status
        current_strength = strengths[-1] if strengths else 0
        current_half_life = half_lives[-1] if half_lives else 30

        if current_strength > 0.7 and strength_trend > 0:
            health_status = "strong_healthy"
            recommendation = "continue_exploiting"
        elif current_strength > 0.5 and strength_trend >= 0:
            health_status = "moderate_stable"
            recommendation = "monitor_closely"
        elif current_strength > 0.3:
            health_status = "weakening"
            recommendation = "reduce_exposure"
        else:
            health_status = "expired"
            recommendation = "rotate_to_new_edge"

        # Integrate FVG analysis for structural edge assessment
        fvg_stats = fvg_detector.get_fvg_statistics(symbol, days_back=lookback_days)

        # Analyze how FVGs relate to edge health
        fvg_edge_insights = self._analyze_fvg_edge_relationship(fvg_stats, strength_trend, current_strength)

        return {
            "symbol": symbol,
            "status": health_status,
            "recommendation": recommendation,
            "current_strength": current_strength,
            "current_half_life_days": current_half_life,
            "strength_trend": strength_trend,
            "half_life_trend": half_life_trend,
            "avg_decay_rate": sum(decay_rates) / len(decay_rates) if decay_rates else 0,
            "analysis_period_days": lookback_days,
            "data_points": len(assessments),
            "fvg_analysis": fvg_stats,
            "fvg_edge_insights": fvg_edge_insights
        }

    def _calculate_trend(self, values: List[float]) -> float:
        """Calculate linear trend slope"""
        if len(values) < 2:
            return 0.0

        n = len(values)
        x = list(range(n))
        y = values

        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(xi * yi for xi, yi in zip(x, y))
        sum_x2 = sum(xi * xi for xi in x)

        if n * sum_x2 - sum_x * sum_x == 0:
            return 0.0

        slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x * sum_x)
        return slope

    def _analyze_fvg_edge_relationship(self, fvg_stats: Dict[str, Any],
                                     strength_trend: float, current_strength: float) -> Dict[str, Any]:
        """Analyze relationship between FVG activity and edge health"""
        insights = {
            "fvg_edge_correlation": "unknown",
            "fvg_market_structure": "neutral",
            "gap_fill_expectation": "unclear"
        }

        if fvg_stats.get("status") == "no_data":
            return insights

        # Analyze FVG fill rates vs edge strength
        fill_rate = fvg_stats.get("fill_rate", 0)
        gap_count = fvg_stats.get("total_gaps", 0)

        if gap_count < 3:
            insights["fvg_edge_correlation"] = "insufficient_fvg_data"
            return insights

        # High fill rate + strong edge = structural efficiency
        if fill_rate > 0.7 and current_strength > 0.7:
            insights["fvg_edge_correlation"] = "structural_efficiency"
            insights["fvg_market_structure"] = "well_balanced"
            insights["gap_fill_expectation"] = "high_confidence"

        # Low fill rate + weak edge = structural inefficiency
        elif fill_rate < 0.3 and current_strength < 0.4:
            insights["fvg_edge_correlation"] = "structural_inefficiency"
            insights["fvg_market_structure"] = "imbalanced"
            insights["gap_fill_expectation"] = "low_confidence"

        # High fill rate + weak edge = potential regime change
        elif fill_rate > 0.6 and current_strength < 0.4:
            insights["fvg_edge_correlation"] = "regime_transition"
            insights["fvg_market_structure"] = "changing"
            insights["gap_fill_expectation"] = "moderate_confidence"

        # Low fill rate + strong edge = persistent dislocation
        elif fill_rate < 0.4 and current_strength > 0.6:
            insights["fvg_edge_correlation"] = "persistent_dislocation"
            insights["fvg_market_structure"] = "unresolved"
            insights["gap_fill_expectation"] = "delayed_resolution"

        # Analyze regime distribution
        regime_dist = fvg_stats.get("regime_distribution", {})
        dominant_regime = max(regime_dist.items(), key=lambda x: x[1])[0] if regime_dist else "unknown"
        insights["dominant_fvg_regime"] = dominant_regime

        return insights

    def get_edge_rotation_signals(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """Get edge rotation signals for multiple symbols"""
        signals = {}

        for symbol in symbols:
            health = self.get_edge_health_assessment(symbol)

            # Handle insufficient data case
            if health["status"] == "insufficient_data":
                signals[symbol] = {
                    "signal": "insufficient_data",
                    "urgency": "low",
                    "health_status": "insufficient_data",
                    "current_strength": 0.0,
                    "days_until_half_life": 0.0,
                    "trend_direction": "unknown"
                }
                continue

            # Generate rotation signal based on health
            if health["status"] == "expired":
                signal_strength = "strong_rotate"
                urgency = "immediate"
            elif health["status"] == "weakening" and health["strength_trend"] < -0.01:
                signal_strength = "moderate_rotate"
                urgency = "high"
            elif health["status"] == "moderate_stable" and health["current_half_life_days"] < 14:
                signal_strength = "weak_rotate"
                urgency = "medium"
            else:
                signal_strength = "hold_position"
                urgency = "low"

            signals[symbol] = {
                "signal": signal_strength,
                "urgency": urgency,
                "health_status": health["status"],
                "current_strength": health["current_strength"],
                "days_until_half_life": health["current_half_life_days"],
                "trend_direction": "improving" if health["strength_trend"] > 0 else "declining"
            }

        return signals


# Global edge half-life tracker instance
edge_half_life_tracker = EdgeHalfLifeTracker()


def analyze_edge_strength(symbol: str, pf: float, win_rate: float, expectancy: float,
                        total_trades: int, time_window_days: int,
                        historical_trades: List[Dict[str, Any]]) -> EdgeStrength:
    """Convenience function to analyze edge strength"""
    registry = get_feature_registry()
    if registry.is_off("edge_half_life"):
        # Return a default/empty EdgeStrength when feature is off
        return EdgeStrength(
            timestamp=datetime.now(timezone.utc),
            symbol=symbol,
            half_life_days=0.0,
            strength_score=0.0,
            confidence=0.0,
            recommendation="feature_disabled",
            decay_rate=0.0,
            time_window_days=time_window_days
        )

    metrics = EdgeMetrics(
        timestamp=datetime.now(timezone.utc),
        symbol=symbol,
        pf=pf,
        win_rate=win_rate,
        expectancy=expectancy,
        total_trades=total_trades,
        time_window_days=time_window_days
    )

    return edge_half_life_tracker.analyze_edge_half_life(symbol, metrics, historical_trades)


if __name__ == "__main__":
    # Example usage
    print("Edge Half-Life Tracker initialized")

    # Test with sample data
    sample_trades = [
        {"ts": "2024-01-01T00:00:00Z", "pct": 0.01},
        {"ts": "2024-01-02T00:00:00Z", "pct": 0.005},
        {"ts": "2024-01-03T00:00:00Z", "pct": -0.008},
        # ... more trades would be here
    ]

    strength = analyze_edge_strength(
        symbol="TESTUSD",
        pf=1.15,
        win_rate=0.55,
        expectancy=0.002,
        total_trades=50,
        time_window_days=30,
        historical_trades=sample_trades
    )

    print(f"Test edge strength: {strength.absolute_strength:.2f}")
    print(f"Half-life: {strength.half_life_days:.1f} days")
