#!/usr/bin/env python3
"""
Inaction Performance Scoring - Second-Order Intelligence Layer

Quantifies the performance impact of "no trade" decisions. Enables:
- Measuring the value of patience and restraint
- Scoring the quality of inaction decisions
- Understanding opportunity cost of discipline
- Building comprehensive performance models that include both action and inaction

The best traders are often defined by what they don't do.
"""

from __future__ import annotations
from typing import Dict, List, Any, Optional, Tuple, NamedTuple
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from pathlib import Path
import json
import math

from engine_alpha.research.pf_timeseries import _compute_pf_for_window
from engine_alpha.reflect.fair_value_gaps import fvg_detector
from engine_alpha.config.feature_flags import get_feature_registry


class InactionDecision(NamedTuple):
    """A decision NOT to trade, with full context"""
    timestamp: datetime
    symbol: str
    intended_direction: int  # What direction would have been traded
    confidence: float  # Confidence in the potential trade
    regime: str  # Market regime at decision time
    barrier_type: str  # Why the trade was blocked (e.g., "capital_mode", "regime_gate", "entry_min_conf")
    barrier_reason: str  # Specific reason for blocking
    market_state: Dict[str, Any]  # Market conditions at decision time


class InactionOutcome(NamedTuple):
    """Outcome analysis of an inaction decision"""
    decision_ts: datetime
    symbol: str
    counterfactual_return: float  # What would have happened if traded
    inaction_quality_score: float  # 0.0-1.0: How good was the inaction?
    opportunity_cost: float  # Cost/benefit of not trading
    hindsight_regret: float  # Would trading have been better?
    discipline_value: float  # Value added by restraint
    market_development: str  # How market moved after decision
    fvg_context: Optional[Dict[str, Any]] = None  # FVG analysis context


@dataclass
class InactionPerformanceTracker:
    """Tracks and scores the performance impact of not trading"""

    inaction_log_file: Path = field(default_factory=lambda: Path("reports/inaction_performance_log.jsonl"))
    analysis_window_hours: int = 24  # How long to track counterfactual outcomes
    min_counterfactual_samples: int = 10  # Minimum samples for reliable scoring

    def __post_init__(self):
        self.inaction_log_file.parent.mkdir(parents=True, exist_ok=True)

    def record_inaction_decision(self, decision: InactionDecision) -> None:
        """Record a decision not to trade for later performance analysis"""
        record = {
            "type": "inaction_decision",
            "timestamp": decision.timestamp.isoformat(),
            "symbol": decision.symbol,
            "intended_direction": decision.intended_direction,
            "confidence": decision.confidence,
            "regime": decision.regime,
            "barrier_type": decision.barrier_type,
            "barrier_reason": decision.barrier_reason,
            "market_state": decision.market_state
        }

        with self.inaction_log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def analyze_inaction_outcome(self, symbol: str, decision_ts: datetime,
                               actual_market_movement: float) -> InactionOutcome:
        """
        Analyze the outcome of an inaction decision by comparing to what would have happened.

        Args:
            symbol: Trading symbol
            decision_ts: When the inaction decision was made
            actual_market_movement: How much the market actually moved after decision

        Returns:
            Comprehensive analysis of the inaction's performance impact
        """
        # Find the matching inaction decision
        decision = self._find_inaction_decision(symbol, decision_ts)
        if not decision:
            # Create a synthetic outcome for unrecorded decisions
            return InactionOutcome(
                decision_ts=decision_ts,
                symbol=symbol,
                counterfactual_return=actual_market_movement,
                inaction_quality_score=0.5,  # Neutral for unrecorded
                opportunity_cost=0.0,
                hindsight_regret=0.0,
                discipline_value=0.0,
                market_development=self._classify_market_development(actual_market_movement)
            )

        # Calculate counterfactual: what would have happened if traded
        intended_direction = decision.intended_direction
        counterfactual_return = actual_market_movement * intended_direction

        # Score the quality of the inaction decision
        quality_score = self._score_inaction_quality(decision, counterfactual_return)

        # Calculate opportunity cost (what was given up by not trading)
        opportunity_cost = counterfactual_return  # Positive = missed opportunity, Negative = avoided loss

        # Calculate hindsight regret (would trading have been better?)
        hindsight_regret = max(0, counterfactual_return)  # Only count missed gains as regret

        # Calculate discipline value (value added by restraint)
        discipline_value = -min(0, counterfactual_return)  # Only count avoided losses as value

        market_development = self._classify_market_development(actual_market_movement)

        # Analyze FVG context for inaction decision
        fvg_context = self._analyze_fvg_inaction_context(symbol, decision_ts, actual_market_movement)

        outcome = InactionOutcome(
            decision_ts=decision_ts,
            symbol=symbol,
            counterfactual_return=counterfactual_return,
            inaction_quality_score=quality_score,
            opportunity_cost=opportunity_cost,
            hindsight_regret=hindsight_regret,
            discipline_value=discipline_value,
            market_development=market_development,
            fvg_context=fvg_context
        )

        # Log the outcome analysis
        self._log_inaction_outcome(decision, outcome)

        return outcome

    def _analyze_fvg_inaction_context(self, symbol: str, decision_ts: datetime,
                                    actual_movement: float) -> Dict[str, Any]:
        """Analyze FVG context around inaction decisions"""
        # Get FVG statistics around the decision time
        fvg_stats = fvg_detector.get_fvg_statistics(symbol, days_back=7)

        context = {
            "fvg_present": False,
            "fvg_type": None,
            "gap_size": 0,
            "gap_direction": None,
            "inaction_fvg_quality": "neutral"
        }

        if fvg_stats.get("status") == "no_data":
            return context

        # Analyze if FVGs were present and how they relate to the inaction
        gap_count = fvg_stats.get("total_gaps", 0)
        fill_rate = fvg_stats.get("fill_rate", 0)

        context["fvg_present"] = gap_count > 0
        context["recent_gaps"] = gap_count

        if gap_count > 0:
            # Determine if inaction aligned with FVG market structure
            if actual_movement > 0.005:  # Market moved up significantly
                context["gap_direction"] = "bullish_potential"
                if fill_rate > 0.6:
                    context["inaction_fvg_quality"] = "good_timing"  # Avoided trading into filled gaps
                else:
                    context["inaction_fvg_quality"] = "potentially_missed"  # May have missed gap fill opportunity
            elif actual_movement < -0.005:  # Market moved down significantly
                context["gap_direction"] = "bearish_potential"
                if fill_rate > 0.6:
                    context["inaction_fvg_quality"] = "good_timing"  # Avoided trading into filled gaps
                else:
                    context["inaction_fvg_quality"] = "potentially_missed"  # May have missed gap fill opportunity
            else:
                context["inaction_fvg_quality"] = "neutral_movement"

        return context

    def _find_inaction_decision(self, symbol: str, decision_ts: datetime) -> Optional[InactionDecision]:
        """Find the inaction decision that matches this analysis"""
        if not self.inaction_log_file.exists():
            return None

        # Look within a small time window around the decision timestamp
        window_start = decision_ts - timedelta(minutes=5)
        window_end = decision_ts + timedelta(minutes=5)

        with self.inaction_log_file.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                    if record.get("type") != "inaction_decision":
                        continue

                    record_ts = datetime.fromisoformat(record["timestamp"])
                    if (window_start <= record_ts <= window_end and
                        record["symbol"] == symbol):
                        return InactionDecision(
                            timestamp=record_ts,
                            symbol=record["symbol"],
                            intended_direction=record["intended_direction"],
                            confidence=record["confidence"],
                            regime=record["regime"],
                            barrier_type=record["barrier_type"],
                            barrier_reason=record["barrier_reason"],
                            market_state=record["market_state"]
                        )
                except (json.JSONDecodeError, KeyError):
                    continue

        return None

    def _score_inaction_quality(self, decision: InactionDecision, counterfactual_return: float) -> float:
        """
        Score the quality of an inaction decision based on context and outcome.

        Returns 0.0-1.0 where:
        1.0 = Perfect inaction (avoided a loss that would have happened)
        0.5 = Neutral inaction (unclear if right or wrong)
        0.0 = Poor inaction (missed a gain that would have happened)
        """
        # Base score from counterfactual outcome
        if counterfactual_return < -0.005:  # Would have been a significant loss
            base_score = 1.0  # Excellent inaction - avoided loss
        elif counterfactual_return < -0.001:  # Would have been a small loss
            base_score = 0.8  # Good inaction - avoided minor loss
        elif counterfactual_return > 0.005:  # Would have been a significant gain
            base_score = 0.2  # Poor inaction - missed gain
        elif counterfactual_return > 0.001:  # Would have been a small gain
            base_score = 0.4  # Mediocre inaction - missed minor gain
        else:  # Would have been break-even
            base_score = 0.6  # Neutral inaction

        # Adjust based on decision context
        confidence = decision.confidence
        barrier_type = decision.barrier_type

        # High confidence inaction is more meaningful
        confidence_multiplier = 0.5 + (confidence * 0.5)  # 0.5-1.0

        # Different barrier types have different quality implications
        barrier_quality = {
            "capital_mode": 0.9,  # Usually wise (halt, de-risk)
            "regime_gate_soft": 0.8,  # Usually prudent (regime caution)
            "regime_gate": 0.8,  # Usually prudent
            "entry_min_conf": 0.7,  # Usually conservative
            "slot_limits": 0.6,  # Usually necessary but not insightful
            "pretrade_check": 0.6,  # Usually necessary
            "policy_block": 0.5,  # Could be good or bad depending on policy
        }.get(barrier_type, 0.5)

        final_score = base_score * confidence_multiplier * barrier_quality
        return min(1.0, max(0.0, final_score))

    def _classify_market_development(self, market_movement: float) -> str:
        """Classify how the market developed after the inaction decision"""
        abs_movement = abs(market_movement)

        if abs_movement < 0.001:
            return "sideways"
        elif abs_movement < 0.005:
            return "minor_move"
        elif market_movement > 0.01:
            return "strong_uptrend"
        elif market_movement < -0.01:
            return "strong_downtrend"
        elif market_movement > 0.005:
            return "moderate_uptrend"
        elif market_movement < -0.005:
            return "moderate_downtrend"
        else:
            return "mixed"

    def _log_inaction_outcome(self, decision: InactionDecision, outcome: InactionOutcome) -> None:
        """Log the analyzed outcome of an inaction decision"""
        record = {
            "type": "inaction_outcome",
            "decision_timestamp": decision.timestamp.isoformat(),
            "analysis_timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": decision.symbol,
            "counterfactual_return": outcome.counterfactual_return,
            "inaction_quality_score": outcome.inaction_quality_score,
            "opportunity_cost": outcome.opportunity_cost,
            "hindsight_regret": outcome.hindsight_regret,
            "discipline_value": outcome.discipline_value,
            "market_development": outcome.market_development,
            "decision_context": {
                "intended_direction": decision.intended_direction,
                "confidence": decision.confidence,
                "regime": decision.regime,
                "barrier_type": decision.barrier_type,
                "barrier_reason": decision.barrier_reason
            }
        }

        with self.inaction_log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def get_inaction_performance_metrics(self, lookback_hours: int = 24) -> Dict[str, Any]:
        """Get comprehensive inaction performance metrics"""
        if not self.inaction_log_file.exists():
            return {"status": "no_data", "message": "No inaction data available yet"}

        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        outcomes = []

        with self.inaction_log_file.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                    if record.get("type") == "inaction_outcome":
                        record_ts = datetime.fromisoformat(record["decision_timestamp"])
                        if record_ts >= cutoff:
                            outcomes.append(record)
                except (json.JSONDecodeError, KeyError):
                    continue

        if not outcomes:
            return {"status": "insufficient_data", "message": "No recent inaction outcomes"}

        # Aggregate metrics
        quality_scores = [o["inaction_quality_score"] for o in outcomes]
        opportunity_costs = [o["opportunity_cost"] for o in outcomes]
        discipline_values = [o["discipline_value"] for o in outcomes]
        regret_values = [o["hindsight_regret"] for o in outcomes]

        # Categorize outcomes
        excellent_inaction = sum(1 for o in outcomes if o["inaction_quality_score"] > 0.8)
        good_inaction = sum(1 for o in outcomes if 0.6 <= o["inaction_quality_score"] <= 0.8)
        poor_inaction = sum(1 for o in outcomes if o["inaction_quality_score"] < 0.4)

        # Barrier type analysis
        barrier_performance = {}
        for outcome in outcomes:
            barrier = outcome["decision_context"]["barrier_type"]
            quality = outcome["inaction_quality_score"]
            if barrier not in barrier_performance:
                barrier_performance[barrier] = []
            barrier_performance[barrier].append(quality)

        barrier_summary = {}
        for barrier, qualities in barrier_performance.items():
            barrier_summary[barrier] = {
                "count": len(qualities),
                "avg_quality": sum(qualities) / len(qualities),
                "excellent_rate": sum(1 for q in qualities if q > 0.8) / len(qualities)
            }

        return {
            "status": "success",
            "time_period_hours": lookback_hours,
            "total_inaction_decisions": len(outcomes),
            "performance_summary": {
                "avg_inaction_quality": sum(quality_scores) / len(quality_scores),
                "excellent_inactions": excellent_inaction,
                "good_inactions": good_inaction,
                "poor_inactions": poor_inactions,
                "net_discipline_value": sum(discipline_values) - sum(regret_values),
                "total_opportunity_cost": sum(opportunity_costs)
            },
            "barrier_analysis": barrier_summary,
            "market_development_breakdown": self._analyze_market_developments(outcomes),
            "recommendations": self._generate_inaction_recommendations(outcomes)
        }

    def _analyze_market_developments(self, outcomes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze how markets developed after inaction decisions"""
        developments = [o["market_development"] for o in outcomes]
        development_counts = {}

        for dev in developments:
            development_counts[dev] = development_counts.get(dev, 0) + 1

        # Calculate success rates by market development
        success_by_development = {}
        for outcome in outcomes:
            dev = outcome["market_development"]
            quality = outcome["inaction_quality_score"]
            if dev not in success_by_development:
                success_by_development[dev] = []
            success_by_development[dev].append(quality)

        success_rates = {}
        for dev, qualities in success_by_development.items():
            success_rates[dev] = {
                "count": len(qualities),
                "avg_quality": sum(qualities) / len(qualities),
                "excellent_rate": sum(1 for q in qualities if q > 0.8) / len(qualities)
            }

        return {
            "development_counts": development_counts,
            "success_rates_by_development": success_rates
        }

    def _generate_inaction_recommendations(self, outcomes: List[Dict[str, Any]]) -> List[str]:
        """Generate recommendations based on inaction performance analysis"""
        recommendations = []

        if not outcomes:
            return ["Need more inaction data for recommendations"]

        # Analyze barrier performance
        barrier_qualities = {}
        for outcome in outcomes:
            barrier = outcome["decision_context"]["barrier_type"]
            quality = outcome["inaction_quality_score"]
            if barrier not in barrier_qualities:
                barrier_qualities[barrier] = []
            barrier_qualities[barrier].append(quality)

        # Find best and worst performing barriers
        barrier_avg_quality = {}
        for barrier, qualities in barrier_qualities.items():
            if len(qualities) >= 3:  # Only consider barriers with enough samples
                barrier_avg_quality[barrier] = sum(qualities) / len(qualities)

        if barrier_avg_quality:
            best_barrier = max(barrier_avg_quality.items(), key=lambda x: x[1])
            worst_barrier = min(barrier_avg_quality.items(), key=lambda x: x[1])

            if best_barrier[1] > 0.7:
                recommendations.append(f"Trust {best_barrier[0]} barriers more (avg quality: {best_barrier[1]:.2f})")

            if worst_barrier[1] < 0.5:
                recommendations.append(f"Review {worst_barrier[0]} barriers (avg quality: {worst_barrier[1]:.2f})")

        # Overall performance assessment
        avg_quality = sum(o["inaction_quality_score"] for o in outcomes) / len(outcomes)

        if avg_quality > 0.7:
            recommendations.append("Inaction discipline is excellent - continue current approach")
        elif avg_quality > 0.5:
            recommendations.append("Inaction performance is good but could be improved")
        else:
            recommendations.append("Review inaction criteria - current discipline may be too restrictive")

        return recommendations

    def get_patience_score(self, symbol: str, lookback_hours: int = 168) -> Dict[str, Any]:
        """Calculate a 'patience score' for a symbol based on inaction quality"""
        metrics = self.get_inaction_performance_metrics(lookback_hours)

        if metrics["status"] != "success":
            return {
                "symbol": symbol,
                "patience_score": 0.5,
                "confidence": "low",
                "assessment": "insufficient_data"
            }

        # Patience score combines inaction quality with discipline value
        inaction_quality = metrics["performance_summary"]["avg_inaction_quality"]
        discipline_value = metrics["performance_summary"]["net_discipline_value"]

        # Normalize discipline value to 0-1 scale (assuming max reasonable value is 0.05)
        normalized_discipline = min(1.0, max(0.0, discipline_value / 0.05))

        patience_score = (inaction_quality * 0.7) + (normalized_discipline * 0.3)

        # Confidence based on sample size
        sample_size = metrics["total_inaction_decisions"]
        if sample_size >= 50:
            confidence = "high"
        elif sample_size >= 20:
            confidence = "medium"
        else:
            confidence = "low"

        # Overall assessment
        if patience_score > 0.8:
            assessment = "masterful_patience"
        elif patience_score > 0.6:
            assessment = "good_discipline"
        elif patience_score > 0.4:
            assessment = "moderate_restraint"
        else:
            assessment = "overly_cautious"

        return {
            "symbol": symbol,
            "patience_score": patience_score,
            "confidence": confidence,
            "assessment": assessment,
            "inaction_quality": inaction_quality,
            "discipline_value": discipline_value,
            "sample_size": sample_size
        }


# Global inaction performance tracker instance
inaction_performance_tracker = InactionPerformanceTracker()


def record_inaction_decision(symbol: str, intended_direction: int, confidence: float,
                           regime: str, barrier_type: str, barrier_reason: str,
                           market_state: Optional[Dict[str, Any]] = None) -> None:
    """Convenience function to record an inaction decision"""
    registry = get_feature_registry()
    if registry.is_off("inaction_scoring"):
        return
    decision = InactionDecision(
        timestamp=datetime.now(timezone.utc),
        symbol=symbol,
        intended_direction=intended_direction,
        confidence=float(confidence),
        regime=regime,
        barrier_type=barrier_type,
        barrier_reason=barrier_reason,
        market_state=market_state or {}
    )
    inaction_performance_tracker.record_inaction_decision(decision)


def analyze_inaction_outcome(symbol: str, decision_ts: datetime,
                           actual_market_movement: float) -> InactionOutcome:
    """Convenience function to analyze an inaction outcome"""
    return inaction_performance_tracker.analyze_inaction_outcome(symbol, decision_ts, actual_market_movement)


if __name__ == "__main__":
    # Example usage
    print("Inaction Performance Tracker initialized")

    # Test patience score calculation
    patience = inaction_performance_tracker.get_patience_score("TESTUSD")
    print(f"Test patience score: {patience['patience_score']:.2f} ({patience['assessment']})")

    metrics = inaction_performance_tracker.get_inaction_performance_metrics()
    print(f"Current metrics status: {metrics.get('status', 'unknown')}")
