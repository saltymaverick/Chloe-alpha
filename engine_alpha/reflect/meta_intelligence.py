#!/usr/bin/env python3
"""
Unified Meta-Intelligence Layer - The Complete Intelligence System

Combines all meta-intelligence components into a cohesive decision-making framework:
- Counterfactual PnL analysis
- Regime uncertainty assessment
- Edge half-life modeling
- Inaction performance scoring

Enables meta-decisions based on comprehensive second-order intelligence.
"""

from __future__ import annotations
from typing import Dict, List, Any, Optional, Tuple, NamedTuple
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
import json
import math

from engine_alpha.reflect.counterfactual_ledger import counterfactual_ledger
from engine_alpha.reflect.regime_uncertainty import regime_uncertainty_tracker
from engine_alpha.reflect.edge_half_life import edge_half_life_tracker
from engine_alpha.reflect.inaction_performance import inaction_performance_tracker
from engine_alpha.reflect.fair_value_gaps import fvg_detector


class MetaDecisionScore(NamedTuple):
    """Comprehensive meta-intelligence decision score"""
    overall_score: float  # 0.0-1.0: Overall decision quality
    confidence: float  # Statistical confidence in the score
    risk_adjusted_score: float  # Score adjusted for uncertainty
    component_scores: Dict[str, float]  # Individual component contributions
    dominant_factors: List[str]  # Key factors influencing the decision
    recommendation: str  # Actionable recommendation
    reasoning: str  # Explanation of the score


class MetaIntelligenceSnapshot(NamedTuple):
    """Complete meta-intelligence state snapshot"""
    timestamp: datetime
    counterfactual_metrics: Dict[str, Any]
    regime_uncertainty: Dict[str, Any]
    edge_health: Dict[str, Any]
    inaction_performance: Dict[str, Any]
    cross_component_insights: Dict[str, Any]
    system_health_score: float  # 0.0-1.0: Overall meta-intelligence health
    fvg_metrics: Optional[Dict[str, Any]] = None  # Fair Value Gap analysis


@dataclass
class MetaIntelligenceOrchestrator:
    """Unified orchestrator for all meta-intelligence components"""

    analysis_window_days: int = 7

    def __post_init__(self):
        # Ensure all components are initialized
        pass

    def assess_meta_decision_quality(self, symbol: str, decision_type: str = "general",
                                   market_context: Optional[Dict[str, Any]] = None) -> MetaDecisionScore:
        """
        Provide comprehensive meta-intelligence assessment for a decision.

        Args:
            symbol: Trading symbol
            decision_type: Type of decision (entry, exit, hold, inaction)
            market_context: Current market conditions

        Returns:
            Comprehensive meta-decision score
        """
        component_scores = {}
        insights = []

        # 1. Counterfactual Analysis
        cf_metrics = counterfactual_ledger.get_counterfactual_metrics(self.analysis_window_days)
        cf_score = self._extract_counterfactual_score(cf_metrics, symbol)
        component_scores["counterfactual"] = cf_score

        if cf_score > 0.7:
            insights.append("Strong counterfactual performance indicates good decision quality")
        elif cf_score < 0.4:
            insights.append("Poor counterfactual outcomes suggest decision concerns")

        # 2. Regime Uncertainty
        regime_health = regime_uncertainty_tracker.get_uncertainty_metrics(24)  # 24 hours
        regime_score = self._extract_regime_score(regime_health)
        component_scores["regime_uncertainty"] = regime_score

        if regime_score < 0.5:
            insights.append("High regime uncertainty may reduce decision confidence")
        else:
            insights.append("Regime conditions are relatively stable")

        # 3. Edge Half-Life
        edge_health = edge_half_life_tracker.get_edge_health_assessment(symbol, self.analysis_window_days)
        edge_score = self._extract_edge_score(edge_health)
        component_scores["edge_half_life"] = edge_score

        if edge_health.get("status") == "expired":
            insights.append("Trading edge appears exhausted - consider rotation")
        elif edge_health.get("status") == "strong_healthy":
            insights.append("Edge is strong and fresh - favorable conditions")

        # 4. Inaction Performance
        inaction_metrics = inaction_performance_tracker.get_inaction_performance_metrics(24)
        inaction_score = self._extract_inaction_score(inaction_metrics, symbol)
        component_scores["inaction_performance"] = inaction_score

        # 5. Fair Value Gap Analysis (New)
        fvg_score = self._extract_fvg_score(symbol)
        component_scores["fair_value_gaps"] = fvg_score

        if inaction_score > 0.7:
            insights.append("Historical inaction discipline is excellent")
        elif inaction_score < 0.4:
            insights.append("Inaction decisions have been suboptimal")

        # Calculate overall score with component weighting
        weights = {
            "counterfactual": 0.25,  # Historical decision quality
            "regime_uncertainty": 0.2,  # Current market stability
            "edge_half_life": 0.25,  # Edge condition
            "inaction_performance": 0.15,  # Discipline quality
            "fair_value_gaps": 0.15  # Market structure efficiency
        }

        overall_score = sum(score * weights[component] for component, score in component_scores.items())

        # Risk adjustment based on uncertainty
        uncertainty_penalty = 1.0 - regime_score  # Higher uncertainty = lower confidence
        risk_adjusted_score = overall_score * (0.7 + 0.3 * regime_score)  # Blend with uncertainty

        # Statistical confidence (based on data availability)
        data_points = (
            len(cf_metrics.get("decisions", [])) +
            (regime_health.get("total_assessments", 0) if regime_health else 0) +
            (edge_health.get("data_points", 0) if isinstance(edge_health, dict) else 0) +
            (inaction_metrics.get("total_inaction_decisions", 0) if inaction_metrics.get("status") == "success" else 0)
        )
        confidence = min(1.0, data_points / 100.0)  # Full confidence at 100+ data points

        # Generate recommendation
        recommendation = self._generate_meta_recommendation(
            overall_score, component_scores, decision_type, insights
        )

        # Dominant factors
        dominant_factors = sorted(
            [(comp, score) for comp, score in component_scores.items()],
            key=lambda x: x[1]
        )[:2]  # Top 2 factors
        dominant_factors = [f"{comp}: {score:.2f}" for comp, score in dominant_factors]

        return MetaDecisionScore(
            overall_score=overall_score,
            confidence=confidence,
            risk_adjusted_score=risk_adjusted_score,
            component_scores=component_scores,
            dominant_factors=dominant_factors,
            recommendation=recommendation,
            reasoning="; ".join(insights)
        )

    def get_meta_intelligence_snapshot(self) -> MetaIntelligenceSnapshot:
        """Get complete meta-intelligence system snapshot"""
        timestamp = datetime.now(timezone.utc)

        # Gather all component metrics
        cf_metrics = counterfactual_ledger.get_comprehensive_meta_metrics(self.analysis_window_days)
        regime_metrics = regime_uncertainty_tracker.get_uncertainty_metrics(24)
        edge_metrics = self._get_aggregate_edge_health()
        inaction_metrics = inaction_performance_tracker.get_inaction_performance_metrics(24)
        fvg_metrics = self._get_aggregate_fvg_health()

        # Cross-component insights
        cross_insights = self._analyze_cross_component_relationships(
            cf_metrics, regime_metrics, edge_metrics, inaction_metrics, fvg_metrics
        )

        # Overall system health score
        health_components = []

        if cf_metrics and "pf_7d" in cf_metrics:
            health_components.append(min(1.0, max(0.0, cf_metrics["pf_7d"] + 1.0)))  # -1 to 1 scale

        if regime_metrics and regime_metrics.get("aggregate_metrics"):
            health_components.append(regime_metrics["aggregate_metrics"]["avg_confidence"])

        if edge_metrics and "avg_edge_strength" in edge_metrics:
            health_components.append(edge_metrics["avg_edge_strength"])

        if inaction_metrics.get("status") == "success":
            health_components.append(inaction_metrics["performance_summary"]["avg_inaction_quality"])

        system_health_score = sum(health_components) / len(health_components) if health_components else 0.5

        return MetaIntelligenceSnapshot(
            timestamp=timestamp,
            counterfactual_metrics=cf_metrics,
            regime_uncertainty=regime_metrics,
            edge_health=edge_metrics,
            inaction_performance=inaction_metrics,
            cross_component_insights=cross_insights,
            system_health_score=system_health_score,
            fvg_metrics=fvg_metrics
        )

    def _extract_counterfactual_score(self, cf_metrics: Dict[str, Any], symbol: str) -> float:
        """Extract decision quality score from counterfactual metrics"""
        if not cf_metrics or "pf_7d" not in cf_metrics:
            return 0.5  # Neutral

        # Base score on recent performance
        pf_score = min(1.0, max(0.0, cf_metrics["pf_7d"] + 1.0))  # Convert to 0-1 scale

        # Adjust for sample size
        count_7d = cf_metrics.get("count_7d", 0)
        sample_adjustment = min(1.0, count_7d / 50.0)  # Full confidence at 50+ trades

        return pf_score * 0.7 + sample_adjustment * 0.3

    def _extract_regime_score(self, regime_health: Dict[str, Any]) -> float:
        """Extract regime stability score"""
        if not regime_health or "aggregate_metrics" not in regime_health:
            return 0.5

        metrics = regime_health["aggregate_metrics"]
        confidence = metrics.get("avg_confidence", 0.5)
        stability = metrics.get("avg_stability", 0.5)

        return (confidence + stability) / 2.0

    def _extract_edge_score(self, edge_health: Dict[str, Any]) -> float:
        """Extract edge health score"""
        if not edge_health or edge_health.get("status") == "insufficient_data":
            return 0.5

        status_scores = {
            "strong_healthy": 0.9,
            "moderate_stable": 0.7,
            "weakening": 0.4,
            "expired": 0.1
        }

        base_score = status_scores.get(edge_health.get("status", "unknown"), 0.5)

        # Adjust for trend
        trend_bonus = 0.1 if edge_health.get("strength_trend", 0) > 0 else -0.1

        return min(1.0, max(0.0, base_score + trend_bonus))

    def _extract_inaction_score(self, inaction_metrics: Dict[str, Any], symbol: str) -> float:
        """Extract inaction performance score"""
        if inaction_metrics.get("status") != "success":
            return 0.5

        # Get symbol-specific patience score
        patience = inaction_performance_tracker.get_patience_score(symbol)
        patience_score = patience.get("patience_score", 0.5)

        # Blend with aggregate performance
        aggregate_quality = inaction_metrics["performance_summary"]["avg_inaction_quality"]

        return (patience_score + aggregate_quality) / 2.0

    def _extract_fvg_score(self, symbol: str) -> float:
        """Extract Fair Value Gap efficiency score"""
        try:
            fvg_stats = fvg_detector.get_fvg_statistics(symbol, days_back=14)

            if fvg_stats.get("status") == "no_data":
                return 0.5  # Neutral when no data

            gap_count = fvg_stats.get("total_gaps", 0)
            fill_rate = fvg_stats.get("fill_rate", 0)

            if gap_count < 3:
                return 0.5  # Insufficient data

            # Score based on market efficiency (high fill rates = efficient market structure)
            efficiency_score = min(1.0, fill_rate * 1.2)  # Bonus for high fill rates

            # Consider gap frequency (some gaps are good, too many may indicate noise)
            frequency_score = min(1.0, gap_count / 20.0)  # Optimal around 20 gaps per 2 weeks

            return (efficiency_score + frequency_score) / 2.0

        except Exception as e:
            print(f"FVG_SCORE_ERROR: {e}")
            return 0.5

    def _get_aggregate_edge_health(self) -> Dict[str, Any]:
        """Get aggregate edge health across all tracked symbols"""
        symbols = ["ADAUSDT", "ATOMUSDT", "BTCUSDT", "DOTUSDT", "ETHUSDT", "LINKUSDT", "SOLUSDT", "BNBUSDT"]
        edge_scores = []

        for symbol in symbols:
            health = edge_half_life_tracker.get_edge_health_assessment(symbol, self.analysis_window_days)
            if health.get("status") != "insufficient_data":
                edge_scores.append(health.get("current_strength", 0.5))

        if not edge_scores:
            return {"status": "insufficient_data"}

        return {
            "avg_edge_strength": sum(edge_scores) / len(edge_scores),
            "strong_edges": sum(1 for s in edge_scores if s > 0.7),
            "weak_edges": sum(1 for s in edge_scores if s < 0.4),
            "total_symbols": len(symbols),
            "analyzed_symbols": len(edge_scores)
        }

    def _get_aggregate_fvg_health(self) -> Dict[str, Any]:
        """Get aggregate FVG health across all tracked symbols"""
        symbols = ["ADAUSDT", "ATOMUSDT", "BTCUSDT", "DOTUSDT", "ETHUSDT", "LINKUSDT", "SOLUSDT", "BNBUSDT"]
        fvg_scores = []
        total_gaps = 0
        total_filled = 0

        for symbol in symbols:
            stats = fvg_detector.get_fvg_statistics(symbol, days_back=14)
            if stats.get("status") != "no_data":
                score = self._extract_fvg_score(symbol)
                fvg_scores.append(score)
                total_gaps += stats.get("total_gaps", 0)
                total_filled += stats.get("gaps_by_status", {}).get("filled", 0)

        if not fvg_scores:
            return {"status": "insufficient_data"}

        avg_efficiency = sum(fvg_scores) / len(fvg_scores) if fvg_scores else 0.5
        overall_fill_rate = total_filled / total_gaps if total_gaps > 0 else 0

        return {
            "avg_market_efficiency": avg_efficiency,
            "overall_fill_rate": overall_fill_rate,
            "total_gaps_analyzed": total_gaps,
            "symbols_with_fvg_data": len(fvg_scores),
            "market_structure_health": "efficient" if avg_efficiency > 0.7 else "neutral" if avg_efficiency > 0.4 else "inefficient"
        }

    def _analyze_cross_component_relationships(self, cf_metrics: Dict, regime_metrics: Dict,
                                            edge_metrics: Dict, inaction_metrics: Dict, fvg_metrics: Optional[Dict] = None) -> Dict[str, Any]:
        """Analyze relationships between different meta-intelligence components"""
        insights = {}

        # Counterfactual vs Regime Uncertainty
        if cf_metrics and regime_metrics:
            cf_pf = cf_metrics.get("pf_7d")
            regime_conf = regime_metrics.get("aggregate_metrics", {}).get("avg_confidence", 0.5)

            if cf_pf is not None:
                if cf_pf > 1.0 and regime_conf > 0.7:
                    insights["stable_regime_advantage"] = "Strong performance in stable regime conditions"
                elif cf_pf < 0.8 and regime_conf < 0.4:
                    insights["uncertainty_penalty"] = "Poor performance correlated with high regime uncertainty"

        # Edge Health vs Inaction Performance
        if edge_metrics and inaction_metrics.get("status") == "success":
            avg_edge = edge_metrics.get("avg_edge_strength", 0.5)
            inaction_quality = inaction_metrics["performance_summary"]["avg_inaction_quality"]

            if avg_edge > 0.7 and inaction_quality > 0.7:
                insights["disciplined_strong_edges"] = "Excellent discipline in strong edge environment"
            elif avg_edge < 0.4 and inaction_quality < 0.4:
                insights["poor_edge_discipline"] = "Weak edges compounded by poor discipline"

        # FVG insights
        if fvg_metrics and fvg_metrics.get("status") != "insufficient_data":
            fvg_efficiency = fvg_metrics.get("avg_market_efficiency", 0.5)
            fill_rate = fvg_metrics.get("overall_fill_rate", 0)

            if fvg_efficiency > 0.7 and fill_rate > 0.6:
                insights["fvg_market_efficiency"] = "High gap fill rates indicate efficient market structure"
            elif fvg_efficiency < 0.4:
                insights["fvg_market_inefficiency"] = "Low gap fill rates suggest structural inefficiencies"

        # Overall system coherence (now includes FVGs)
        component_scores = []
        if cf_metrics and "pf_7d" in cf_metrics:
            component_scores.append(min(1.0, max(0.0, cf_metrics["pf_7d"] + 1.0)))
        if regime_metrics and regime_metrics.get("aggregate_metrics"):
            component_scores.append(regime_metrics["aggregate_metrics"]["avg_confidence"])
        if edge_metrics and "avg_edge_strength" in edge_metrics:
            component_scores.append(edge_metrics["avg_edge_strength"])
        if inaction_metrics.get("status") == "success":
            component_scores.append(inaction_metrics["performance_summary"]["avg_inaction_quality"])
        if fvg_metrics and fvg_metrics.get("status") != "insufficient_data":
            component_scores.append(fvg_metrics.get("avg_market_efficiency", 0.5))

        if len(component_scores) >= 2:
            coherence = 1.0 - (sum(abs(s - sum(component_scores)/len(component_scores)) for s in component_scores) / len(component_scores))
            insights["system_coherence"] = f"{coherence:.2f}"

        return insights

    def _generate_meta_recommendation(self, overall_score: float, component_scores: Dict[str, float],
                                    decision_type: str, insights: List[str]) -> str:
        """Generate actionable meta-intelligence recommendation"""
        if overall_score > 0.8:
            return "HIGH_CONFIDENCE: Proceed with decision - all meta-factors align favorably"
        elif overall_score > 0.6:
            return "MODERATE_CONFIDENCE: Proceed but monitor closely - some caution advised"
        elif overall_score > 0.4:
            return "LOW_CONFIDENCE: Consider delaying decision - mixed meta-signals"
        else:
            return "HIGH_RISK: Strongly reconsider decision - meta-intelligence suggests caution"

    def get_meta_decision_matrix(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """Generate meta-decision matrix for multiple symbols"""
        matrix = {}

        for symbol in symbols:
            try:
                score = self.assess_meta_decision_quality(symbol, "general")
                matrix[symbol] = {
                    "overall_score": score.overall_score,
                    "confidence": score.confidence,
                    "recommendation": score.recommendation,
                    "dominant_factors": score.dominant_factors,
                    "risk_adjusted_score": score.risk_adjusted_score
                }
            except Exception as e:
                matrix[symbol] = {
                    "error": str(e),
                    "overall_score": 0.5,
                    "recommendation": "Unable to assess - data collection in progress"
                }

        return matrix


# Global meta-intelligence orchestrator instance
meta_intelligence_orchestrator = MetaIntelligenceOrchestrator()


def assess_meta_decision_quality(symbol: str, decision_type: str = "general",
                               market_context: Optional[Dict[str, Any]] = None) -> MetaDecisionScore:
    """Convenience function for meta-decision assessment"""
    return meta_intelligence_orchestrator.assess_meta_decision_quality(symbol, decision_type, market_context)


def get_meta_intelligence_snapshot() -> MetaIntelligenceSnapshot:
    """Convenience function for complete meta-intelligence snapshot"""
    return meta_intelligence_orchestrator.get_meta_intelligence_snapshot()


if __name__ == "__main__":
    # Example usage
    print("Unified Meta-Intelligence Layer initialized")

    # Test assessment for a symbol
    try:
        score = assess_meta_decision_quality("ADAUSDT")
        print(f"ADAUSDT meta-decision score: {score.overall_score:.2f}")
        print(f"Recommendation: {score.recommendation}")
    except Exception as e:
        print(f"Assessment failed: {e}")

    # Test snapshot
    snapshot = get_meta_intelligence_snapshot()
    print(f"System health score: {snapshot.system_health_score:.2f}")
