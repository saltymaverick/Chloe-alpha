#!/usr/bin/env python3
"""
Regime Uncertainty Gating - Second-Order Intelligence Layer

Tracks confidence in regime classification to prevent over-confidence in uncertain markets.
This enables meta-decisions like:
- Reducing position sizes when regime confidence is low
- Delaying entries during regime transitions
- Modulating exit thresholds based on regime stability

Observer-only initially - records uncertainty without changing behavior.
"""

from __future__ import annotations
from typing import Dict, List, Any, Optional, Tuple, NamedTuple
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from pathlib import Path
import json
import math
from dateutil import parser

from engine_alpha.core.regime import classify_regime


class RegimeUncertaintyMetrics(NamedTuple):
    """Metrics for regime classification uncertainty"""
    regime_label: str
    confidence_score: float  # 0.0-1.0, how confident in this regime?
    stability_score: float  # 0.0-1.0, how stable has this regime been?
    transition_probability: float  # likelihood of regime change soon
    entropy: float  # information-theoretic uncertainty
    volatility_regime_confidence: float  # confidence in volatility assessment
    trend_regime_confidence: float  # confidence in trend assessment
    classification_timestamp: datetime


@dataclass
class RegimeUncertaintyTracker:
    """Tracks regime classification confidence over time"""

    history_window_minutes: int = 60  # How far back to look for stability
    min_samples_for_stability: int = 10  # Minimum samples to calculate stability
    uncertainty_log_file: Path = field(default_factory=lambda: Path("reports/regime_uncertainty_log.jsonl"))

    def __post_init__(self):
        self.uncertainty_log_file.parent.mkdir(parents=True, exist_ok=True)

    def assess_uncertainty(self, market_data: Dict[str, Any],
                          current_regime: str,
                          timestamp: Optional[datetime] = None) -> RegimeUncertaintyMetrics:
        """
        Assess uncertainty in current regime classification

        Args:
            market_data: OHLCV and indicator data
            current_regime: Current regime label (chop, trend_up, etc.)
            timestamp: When this assessment was made

        Returns:
            Comprehensive uncertainty metrics
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        # Get recent regime history for stability calculation
        recent_regimes = self._get_recent_regime_history(timestamp, self.history_window_minutes)

        # Calculate confidence in current regime classification
        confidence_score = self._calculate_regime_confidence(market_data, current_regime)

        # Calculate regime stability over time window
        stability_score = self._calculate_regime_stability(recent_regimes, current_regime)

        # Estimate transition probability
        transition_probability = self._estimate_transition_probability(recent_regimes, current_regime)

        # Calculate entropy (information-theoretic uncertainty)
        entropy = self._calculate_regime_entropy(recent_regimes)

        # Assess confidence in volatility vs trend components
        vol_confidence, trend_confidence = self._assess_component_confidences(market_data)

        metrics = RegimeUncertaintyMetrics(
            regime_label=current_regime,
            confidence_score=confidence_score,
            stability_score=stability_score,
            transition_probability=transition_probability,
            entropy=entropy,
            volatility_regime_confidence=vol_confidence,
            trend_regime_confidence=trend_confidence,
            classification_timestamp=timestamp
        )

        # Log the assessment
        self._log_uncertainty_assessment(metrics, market_data)

        return metrics

    def _calculate_regime_confidence(self, market_data: Dict[str, Any], regime: str) -> float:
        """
        Calculate confidence in regime classification based on market conditions.
        This is a simplified version - real implementation would use more sophisticated analysis.
        """
        # For now, use simple heuristics based on market volatility and trend strength
        # In a full implementation, this would come from the regime classifier itself

        try:
            # Extract some basic market metrics
            close_prices = market_data.get("closes", [])
            if len(close_prices) < 20:
                return 0.5  # Neutral confidence with insufficient data

            # Calculate recent volatility
            returns = [close_prices[i] / close_prices[i-1] - 1 for i in range(1, len(close_prices))]
            volatility = math.sqrt(sum(r**2 for r in returns[-20:]) / len(returns[-20:]))

            # Calculate trend strength (simplified)
            recent_trend = sum(returns[-10:])

            # Confidence based on how clearly the regime characteristics match
            if regime == "chop":
                # High volatility, low trend = confident chop
                confidence = min(1.0, volatility * 2.0) * (1.0 - abs(recent_trend) * 5.0)
            elif regime in ["trend_up", "trend_down"]:
                # Low volatility, strong trend = confident trend
                trend_strength = abs(recent_trend)
                confidence = min(1.0, trend_strength * 3.0) * (1.0 - volatility * 2.0)
            elif regime == "high_vol":
                # Very high volatility = confident high_vol
                confidence = min(1.0, volatility * 3.0)
            else:
                confidence = 0.5  # Unknown regime

            return max(0.0, min(1.0, confidence))

        except (KeyError, IndexError, ZeroDivisionError):
            return 0.5  # Neutral confidence on calculation errors

    def _calculate_regime_stability(self, recent_regimes: List[str], current_regime: str) -> float:
        """Calculate how stable the current regime has been over the time window"""
        if len(recent_regimes) < self.min_samples_for_stability:
            return 0.5  # Neutral stability with insufficient history

        # Count how many recent classifications match current regime
        matching_count = sum(1 for r in recent_regimes if r == current_regime)
        stability = matching_count / len(recent_regimes)

        return stability

    def _estimate_transition_probability(self, recent_regimes: List[str], current_regime: str) -> float:
        """Estimate probability of regime transition in near future"""
        if len(recent_regimes) < self.min_samples_for_stability:
            return 0.5  # Neutral probability

        # Count recent transitions (regime changes)
        transitions = sum(1 for i in range(1, len(recent_regimes))
                         if recent_regimes[i] != recent_regimes[i-1])

        # Transition rate over the window
        transition_rate = transitions / len(recent_regimes)

        # Scale to probability of transition in next period
        # Higher transition rates suggest higher transition probability
        return min(1.0, transition_rate * 2.0)

    def _calculate_regime_entropy(self, recent_regimes: List[str]) -> float:
        """Calculate entropy (information uncertainty) of regime distribution"""
        if not recent_regimes:
            return 1.0  # Maximum uncertainty

        # Count frequency of each regime
        regime_counts = {}
        for regime in recent_regimes:
            regime_counts[regime] = regime_counts.get(regime, 0) + 1

        # Calculate entropy
        entropy = 0.0
        total = len(recent_regimes)
        for count in regime_counts.values():
            prob = count / total
            if prob > 0:
                entropy -= prob * math.log2(prob)

        # Normalize to 0-1 scale (divide by max possible entropy)
        max_entropy = math.log2(len(regime_counts)) if regime_counts else 1.0
        return entropy / max_entropy if max_entropy > 0 else 0.0

    def _assess_component_confidences(self, market_data: Dict[str, Any]) -> Tuple[float, float]:
        """Assess confidence in volatility vs trend regime components"""
        # Simplified assessment - in practice would use more sophisticated analysis
        try:
            close_prices = market_data.get("closes", [])
            if len(close_prices) < 20:
                return 0.5, 0.5

            returns = [close_prices[i] / close_prices[i-1] - 1 for i in range(1, len(close_prices))]

            # Volatility confidence: how consistent is the volatility level?
            volatility = math.sqrt(sum(r**2 for r in returns[-20:]) / len(returns[-20:]))
            vol_confidence = min(1.0, volatility * 2.0)  # Higher vol = more confident

            # Trend confidence: how consistent is the trend direction?
            recent_trend = sum(returns[-10:])
            trend_consistency = abs(recent_trend) / sum(abs(r) for r in returns[-10:])
            trend_confidence = min(1.0, trend_consistency * 2.0)

            return vol_confidence, trend_confidence

        except (KeyError, IndexError, ZeroDivisionError):
            return 0.5, 0.5

    def _get_recent_regime_history(self, timestamp: datetime, minutes_back: int) -> List[str]:
        """Get recent regime classifications from log"""
        if not self.uncertainty_log_file.exists():
            return []

        cutoff = timestamp - timedelta(minutes=minutes_back)
        recent_regimes = []

        try:
            with self.uncertainty_log_file.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        record_ts = parser.isoparse(record["timestamp"])
                        if record_ts >= cutoff and record_ts <= timestamp:
                            recent_regimes.append(record["regime_label"])
                    except (json.JSONDecodeError, KeyError):
                        continue
        except Exception:
            pass

        return recent_regimes

    def _log_uncertainty_assessment(self, metrics: RegimeUncertaintyMetrics,
                                  market_data: Dict[str, Any]) -> None:
        """Log the uncertainty assessment for analysis"""
        record = {
            "timestamp": metrics.classification_timestamp.isoformat(),
            "regime_label": metrics.regime_label,
            "confidence_score": metrics.confidence_score,
            "stability_score": metrics.stability_score,
            "transition_probability": metrics.transition_probability,
            "entropy": metrics.entropy,
            "volatility_regime_confidence": metrics.volatility_regime_confidence,
            "trend_regime_confidence": metrics.trend_regime_confidence,
            "market_snapshot": {
                "close": market_data.get("closes", [-1])[-1] if market_data.get("closes") else None,
                "volume": market_data.get("volumes", [-1])[-1] if market_data.get("volumes") else None,
            }
        }

        with self.uncertainty_log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def get_uncertainty_metrics(self, lookback_minutes: int = 60) -> Dict[str, Any]:
        """Get aggregated uncertainty metrics over the lookback period"""
        if not self.uncertainty_log_file.exists():
            return {}

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)
        assessments = []

        with self.uncertainty_log_file.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                    record_ts = parser.isoparse(record["timestamp"])
                    if record_ts >= cutoff:
                        assessments.append(record)
                except (json.JSONDecodeError, KeyError):
                    continue

        if not assessments:
            return {}

        # Aggregate metrics
        confidence_scores = [a["confidence_score"] for a in assessments]
        stability_scores = [a["stability_score"] for a in assessments]
        transition_probs = [a["transition_probability"] for a in assessments]
        entropies = [a["entropy"] for a in assessments]

        # Group by regime
        regime_groups = {}
        for assessment in assessments:
            regime = assessment["regime_label"]
            if regime not in regime_groups:
                regime_groups[regime] = []
            regime_groups[regime].append(assessment)

        regime_stats = {}
        for regime, regs in regime_groups.items():
            regime_stats[regime] = {
                "count": len(regs),
                "avg_confidence": sum(r["confidence_score"] for r in regs) / len(regs),
                "avg_stability": sum(r["stability_score"] for r in regs) / len(regs),
                "avg_entropy": sum(r["entropy"] for r in regs) / len(regs),
            }

        return {
            "total_assessments": len(assessments),
            "time_range_minutes": lookback_minutes,
            "aggregate_metrics": {
                "avg_confidence": sum(confidence_scores) / len(confidence_scores),
                "avg_stability": sum(stability_scores) / len(stability_scores),
                "avg_transition_probability": sum(transition_probs) / len(transition_probs),
                "avg_entropy": sum(entropies) / len(entropies),
            },
            "regime_breakdown": regime_stats,
            "current_uncertainty_level": self._classify_uncertainty_level(
                sum(confidence_scores) / len(confidence_scores),
                sum(stability_scores) / len(stability_scores)
            )
        }

    def _classify_uncertainty_level(self, avg_confidence: float, avg_stability: float) -> str:
        """Classify overall uncertainty level"""
        combined_score = (avg_confidence + avg_stability) / 2.0

        if combined_score >= 0.8:
            return "LOW_UNCERTAINTY"
        elif combined_score >= 0.6:
            return "MODERATE_UNCERTAINTY"
        elif combined_score >= 0.4:
            return "HIGH_UNCERTAINTY"
        else:
            return "EXTREME_UNCERTAINTY"


# Global uncertainty tracker instance
regime_uncertainty_tracker = RegimeUncertaintyTracker()


def assess_regime_uncertainty(market_data: Dict[str, Any], current_regime: str,
                            timestamp: Optional[datetime] = None) -> RegimeUncertaintyMetrics:
    """Convenience function to assess regime uncertainty"""
    return regime_uncertainty_tracker.assess_uncertainty(market_data, current_regime, timestamp)


if __name__ == "__main__":
    # Example usage
    print("Regime Uncertainty Tracker initialized")

    # Test with dummy data
    test_market_data = {
        "closes": [100, 101, 102, 103, 102, 101, 100, 99, 98, 99, 100, 101],
        "volumes": [1000] * 12
    }

    metrics = assess_regime_uncertainty(test_market_data, "chop")
    print(f"Test assessment: {metrics.regime_label}, confidence={metrics.confidence_score:.2f}")

    summary = regime_uncertainty_tracker.get_uncertainty_metrics(60)
    print(f"Summary: {len(summary)} metrics available")
