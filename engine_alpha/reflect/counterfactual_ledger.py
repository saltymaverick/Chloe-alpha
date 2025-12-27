#!/usr/bin/env python3
"""
Counterfactual PnL Ledger - Second-Order Intelligence Layer

Tracks what would have happened if Chloe didn't take trades, enabling:
- True opportunity cost measurement
- False positive detection
- Edge validation against null behavior
- Patience advantage quantification

This is the foundation for meta-intelligence - knowing whether you're adding value
beyond just participating in market movements.
"""

from __future__ import annotations
from typing import Dict, List, Any, Optional, Tuple, NamedTuple
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from pathlib import Path
import json
import math
from dateutil import parser

from engine_alpha.research.pf_timeseries import _compute_pf_for_window
from engine_alpha.reflect.regime_uncertainty import RegimeUncertaintyMetrics, assess_regime_uncertainty
from engine_alpha.reflect.edge_half_life import EdgeStrength, analyze_edge_strength
from engine_alpha.reflect.inaction_performance import InactionOutcome, analyze_inaction_outcome
from engine_alpha.reflect.fair_value_gaps import FairValueGap, fvg_detector
from engine_alpha.config.feature_flags import get_feature_registry


class CounterfactualDecision(NamedTuple):
    """A trading decision point with full context for counterfactual analysis"""
    ts: datetime
    symbol: str
    direction: int  # 1=long, -1=short, 0=no position
    confidence: float
    regime: str
    entry_price: Optional[float]
    market_state: Dict[str, Any]  # OHLCV, indicators, etc.
    decision_type: str  # 'entry', 'hold', 'exit', 'skip'
    regime_uncertainty: Optional[RegimeUncertaintyMetrics] = None  # Meta-intelligence: regime uncertainty
    edge_strength: Optional[EdgeStrength] = None  # Meta-intelligence: edge decay modeling
    fvg_context: Optional[Dict[str, Any]] = None  # Meta-intelligence: Fair Value Gap analysis


@dataclass
class CounterfactualOutcome:
    """Result of a counterfactual simulation"""
    decision_ts: datetime
    symbol: str
    actual_pnl_pct: Optional[float] = None
    counterfactual_pnl_pct: Optional[float] = None
    hold_duration_bars: Optional[int] = None
    exit_reason: Optional[str] = None
    regime_at_decision: Optional[str] = None
    confidence_at_decision: Optional[float] = None

    @property
    def opportunity_cost(self) -> Optional[float]:
        """How much better/worse did we do vs doing nothing?"""
        if self.actual_pnl_pct is None or self.counterfactual_pnl_pct is None:
            return None
        return self.actual_pnl_pct - self.counterfactual_pnl_pct

    @property
    def was_trade_beneficial(self) -> Optional[bool]:
        """Did trading add value vs holding cash?"""
        cost = self.opportunity_cost
        return cost > 0 if cost is not None else None


@dataclass
class CounterfactualLedger:
    """Tracks and analyzes counterfactual trading performance"""

    ledger_file: Path = field(default_factory=lambda: Path("reports/counterfactual_ledger.jsonl"))
    simulation_window_bars: int = 60  # How far ahead to simulate counterfactuals (15m bars)

    def __post_init__(self):
        self.ledger_file.parent.mkdir(parents=True, exist_ok=True)

    def record_decision(self, decision: CounterfactualDecision) -> None:
        """Record a trading decision for later counterfactual analysis"""
        record = {
            "type": "decision",
            "ts": decision.ts.isoformat(),
            "symbol": decision.symbol,
            "direction": decision.direction,
            "confidence": decision.confidence,
            "regime": decision.regime,
            "entry_price": decision.entry_price,
            "market_state": decision.market_state,
            "decision_type": decision.decision_type
        }

        # Add regime uncertainty metrics if available
        if decision.regime_uncertainty:
            record["regime_uncertainty"] = {
                "confidence_score": decision.regime_uncertainty.confidence_score,
                "stability_score": decision.regime_uncertainty.stability_score,
                "transition_probability": decision.regime_uncertainty.transition_probability,
                "entropy": decision.regime_uncertainty.entropy,
                "volatility_regime_confidence": decision.regime_uncertainty.volatility_regime_confidence,
                "trend_regime_confidence": decision.regime_uncertainty.trend_regime_confidence,
            }

        # Add edge strength metrics if available
        if decision.edge_strength:
            record["edge_strength"] = {
                "absolute_strength": decision.edge_strength.absolute_strength,
                "relative_strength": decision.edge_strength.relative_strength,
                "confidence": decision.edge_strength.confidence,
                "half_life_days": decision.edge_strength.half_life_days,
                "decay_rate": decision.edge_strength.decay_rate,
                "freshness_score": decision.edge_strength.freshness_score,
            }

        with self.ledger_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def resolve_counterfactual(self, symbol: str, exit_ts: datetime,
                             actual_pnl_pct: float, exit_reason: str,
                             regime_at_exit: str) -> None:
        """Resolve a counterfactual by finding the matching decision and computing outcome"""

        # Find the most recent decision for this symbol before exit_ts
        decision = self._find_matching_decision(symbol, exit_ts)
        if not decision:
            return

        # Simulate what would have happened if we didn't trade
        counterfactual_pnl = self._simulate_counterfactual(decision, exit_ts)

        outcome = CounterfactualOutcome(
            decision_ts=decision.ts,
            symbol=symbol,
            actual_pnl_pct=actual_pnl_pct,
            counterfactual_pnl_pct=counterfactual_pnl,
            hold_duration_bars=self._calculate_hold_duration(decision.ts, exit_ts),
            exit_reason=exit_reason,
            regime_at_decision=decision.regime,
            confidence_at_decision=decision.confidence
        )

        self._record_outcome(outcome)

    def _find_matching_decision(self, symbol: str, exit_ts: datetime) -> Optional[CounterfactualDecision]:
        """Find the decision that led to this trade"""
        if not self.ledger_file.exists():
            return None

        recent_decisions = []
        cutoff = exit_ts - timedelta(hours=24)  # Look back up to 24h

        with self.ledger_file.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                    if record.get("type") != "decision":
                        continue

                    record_ts = parser.isoparse(record["ts"])
                    if record_ts < cutoff or record_ts > exit_ts:
                        continue

                    if record["symbol"] == symbol and record.get("decision_type") in ("entry", "entry_attempt"):
                        recent_decisions.append(CounterfactualDecision(
                            ts=record_ts,
                            symbol=record["symbol"],
                            direction=record["direction"],
                            confidence=record["confidence"],
                            regime=record["regime"],
                            entry_price=record.get("entry_price"),
                            market_state=record.get("market_state", {}),
                            decision_type=record["decision_type"]
                        ))
                except (json.JSONDecodeError, KeyError):
                    continue

        # Return the most recent matching decision
        return max(recent_decisions, key=lambda d: d.ts) if recent_decisions else None

    def _simulate_counterfactual(self, decision: CounterfactualDecision, exit_ts: datetime) -> Optional[float]:
        """Simulate what would have happened if we didn't take the trade"""
        # This is a simplified simulation - in reality you'd need OHLCV data
        # For now, return a baseline (market return over the period)
        # TODO: Implement proper OHLCV-based simulation

        # Placeholder: assume neutral counterfactual (0% return)
        # Real implementation would track actual market movement
        return 0.0

    def _calculate_hold_duration(self, entry_ts: datetime, exit_ts: datetime) -> int:
        """Calculate how long the position was held in bars (15m)"""
        duration = exit_ts - entry_ts
        return max(1, int(duration.total_seconds() / 900))  # 15min = 900 seconds

    def _record_outcome(self, outcome: CounterfactualOutcome) -> None:
        """Record the resolved counterfactual outcome"""
        record = {
            "type": "outcome",
            "decision_ts": outcome.decision_ts.isoformat(),
            "symbol": outcome.symbol,
            "actual_pnl_pct": outcome.actual_pnl_pct,
            "counterfactual_pnl_pct": outcome.counterfactual_pnl_pct,
            "opportunity_cost": outcome.opportunity_cost,
            "was_trade_beneficial": outcome.was_trade_beneficial,
            "hold_duration_bars": outcome.hold_duration_bars,
            "exit_reason": outcome.exit_reason,
            "regime_at_decision": outcome.regime_at_decision,
            "confidence_at_decision": outcome.confidence_at_decision
        }

        with self.ledger_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def analyze_inaction_outcome(self, symbol: str, decision_ts: datetime,
                               actual_market_movement: float) -> None:
        """Analyze an inaction outcome and store it"""
        try:
            outcome = analyze_inaction_outcome(symbol, decision_ts, actual_market_movement)
            # Store the outcome in our ledger for comprehensive analysis
            record = {
                "type": "inaction_outcome",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "symbol": symbol,
                "decision_ts": decision_ts.isoformat(),
                "inaction_quality_score": outcome.inaction_quality_score,
                "counterfactual_return": outcome.counterfactual_return,
                "opportunity_cost": outcome.opportunity_cost,
                "discipline_value": outcome.discipline_value,
                "market_development": outcome.market_development
            }

            with self.ledger_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            # Don't fail the main flow if inaction analysis fails
            pass

    def get_counterfactual_metrics(self, lookback_days: int = 7) -> Dict[str, Any]:
        """Compute counterfactual performance metrics"""
        if not self.ledger_file.exists():
            return {}

        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        outcomes = []

        with self.ledger_file.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                    if record.get("type") != "outcome":
                        continue

                    record_ts = parser.isoparse(record["decision_ts"])
                    if record_ts < cutoff:
                        continue

                    outcomes.append(CounterfactualOutcome(
                        decision_ts=record_ts,
                        symbol=record["symbol"],
                        actual_pnl_pct=record.get("actual_pnl_pct"),
                        counterfactual_pnl_pct=record.get("counterfactual_pnl_pct"),
                        hold_duration_bars=record.get("hold_duration_bars"),
                        exit_reason=record.get("exit_reason"),
                        regime_at_decision=record.get("regime_at_decision"),
                        confidence_at_decision=record.get("confidence_at_decision")
                    ))
                except (json.JSONDecodeError, KeyError):
                    continue

        if not outcomes:
            return {}

        # Compute aggregate metrics
        opportunity_costs = [o.opportunity_cost for o in outcomes if o.opportunity_cost is not None]
        beneficial_trades = [o for o in outcomes if o.was_trade_beneficial is True]

        return {
            "total_decisions": len(outcomes),
            "avg_opportunity_cost": sum(opportunity_costs) / len(opportunity_costs) if opportunity_costs else None,
            "beneficial_trade_rate": len(beneficial_trades) / len(outcomes) if outcomes else 0,
            "total_opportunity_gain": sum(c for c in opportunity_costs if c > 0),
            "total_opportunity_loss": abs(sum(c for c in opportunity_costs if c < 0)),
            "counterfactual_pf": _compute_pf_for_window([o.actual_pnl_pct for o in outcomes if o.actual_pnl_pct is not None]),
            "null_pf": _compute_pf_for_window([o.counterfactual_pnl_pct for o in outcomes if o.counterfactual_pnl_pct is not None]),
            "by_regime": self._group_by_regime(outcomes),
            "by_confidence_quartile": self._group_by_confidence_quartile(outcomes)
        }

    def _group_by_regime(self, outcomes: List[CounterfactualOutcome]) -> Dict[str, Dict[str, Any]]:
        """Group counterfactual metrics by regime"""
        regimes = {}
        for outcome in outcomes:
            regime = outcome.regime_at_decision or "unknown"
            if regime not in regimes:
                regimes[regime] = []

            if outcome.opportunity_cost is not None:
                regimes[regime].append(outcome.opportunity_cost)

        result = {}
        for regime, costs in regimes.items():
            if costs:
                result[regime] = {
                    "count": len(costs),
                    "avg_opportunity_cost": sum(costs) / len(costs),
                    "beneficial_rate": sum(1 for c in costs if c > 0) / len(costs)
                }

        return result

    def _group_by_confidence_quartile(self, outcomes: List[CounterfactualOutcome]) -> Dict[str, Dict[str, Any]]:
        """Group counterfactual metrics by confidence quartiles"""
        confidences = [(o.confidence_at_decision or 0, o.opportunity_cost)
                      for o in outcomes if o.confidence_at_decision is not None and o.opportunity_cost is not None]

        if not confidences:
            return {}

        confidences.sort(key=lambda x: x[0])
        n = len(confidences)
        quartiles = {
            "Q1_lowest": confidences[:n//4],
            "Q2": confidences[n//4:n//2],
            "Q3": confidences[n//2:3*n//4],
            "Q4_highest": confidences[3*n//4:]
        }

        result = {}
        for quartile, data in quartiles.items():
            if data:
                costs = [d[1] for d in data]
                result[quartile] = {
                    "count": len(costs),
                    "avg_confidence": sum(d[0] for d in data) / len(data),
                    "avg_opportunity_cost": sum(costs) / len(costs),
                    "beneficial_rate": sum(1 for c in costs if c > 0) / len(costs)
                }

        return result

    def get_comprehensive_meta_metrics(self, lookback_days: int = 7) -> Dict[str, Any]:
        """Get comprehensive meta-intelligence metrics including inaction analysis"""
        base_metrics = self.get_counterfactual_metrics(lookback_days)

        # Add inaction performance metrics
        try:
            from engine_alpha.reflect.inaction_performance import inaction_performance_tracker
            inaction_metrics = inaction_performance_tracker.get_inaction_performance_metrics(
                lookback_hours=lookback_days * 24
            )

            if inaction_metrics.get("status") == "success":
                base_metrics["inaction_performance"] = {
                    "avg_inaction_quality": inaction_metrics["performance_summary"]["avg_inaction_quality"],
                    "net_discipline_value": inaction_metrics["performance_summary"]["net_discipline_value"],
                    "excellent_inactions": inaction_metrics["performance_summary"]["excellent_inactions"],
                    "barrier_effectiveness": inaction_metrics["barrier_analysis"]
                }
        except Exception:
            # Inaction metrics are optional
            pass

        return base_metrics


# Global ledger instance
counterfactual_ledger = CounterfactualLedger()


def record_trading_decision(symbol: str, direction: int, confidence: float,
                          regime: str, entry_price: Optional[float] = None,
                          market_state: Optional[Dict[str, Any]] = None,
                          decision_type: str = "entry",
                          regime_uncertainty: Optional[RegimeUncertaintyMetrics] = None,
                          edge_strength: Optional[EdgeStrength] = None,
                          fvg_context: Optional[Dict[str, Any]] = None) -> None:
    """Convenience function to record a trading decision with meta-intelligence"""
    registry = get_feature_registry()
    if registry.is_off("counterfactual_ledger"):
        return
    decision = CounterfactualDecision(
        ts=datetime.now(timezone.utc),
        symbol=symbol,
        direction=direction,
        confidence=confidence,
        regime=regime,
        entry_price=entry_price,
        market_state=market_state or {},
        decision_type=decision_type,
        regime_uncertainty=regime_uncertainty,
        edge_strength=edge_strength,
        fvg_context=fvg_context
    )
    counterfactual_ledger.record_decision(decision)


def resolve_trade_counterfactual(symbol: str, exit_ts: datetime,
                               actual_pnl_pct: float, exit_reason: str,
                               regime_at_exit: str) -> None:
    """Convenience function to resolve a counterfactual after trade exit"""
    counterfactual_ledger.resolve_counterfactual(
        symbol, exit_ts, actual_pnl_pct, exit_reason, regime_at_exit
    )


if __name__ == "__main__":
    # Example usage and testing
    print("Counterfactual PnL Ledger initialized")
    metrics = counterfactual_ledger.get_counterfactual_metrics()
    print(f"Current metrics: {len(metrics)} outcomes tracked")
