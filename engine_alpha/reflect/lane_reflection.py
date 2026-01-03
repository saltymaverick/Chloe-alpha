"""
Lane Reflection System

Generates comprehensive per-lane performance analysis and adjustment recommendations.
"""

import json
import statistics
import os
import tempfile
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

from dateutil import parser


class LaneReflection:
    """Generates lane performance reflection artifacts."""

    def __init__(self, window_hours: int = 24):
        self.window_hours = window_hours
        self.end_ts = datetime.now(timezone.utc)
        self.start_ts = self.end_ts - timedelta(hours=window_hours)

    def generate_reflection(self) -> Dict[str, Any]:
        """Generate the complete lane reflection artifact."""
        return {
            "generated_at": self.end_ts.isoformat(),
            "window": {
                "hours": self.window_hours,
                "start_ts": self.start_ts.isoformat(),
                "end_ts": self.end_ts.isoformat()
            },
            "inputs": {
                "trades_file": "reports/trades.jsonl",
                "counterfactual_file": "reports/counterfactual_ledger.jsonl",
                "symbol_states_file": "reports/risk/symbol_states.json",
                "pf_file": "reports/pf_local.json"
            },
            "lanes": self._analyze_lanes(),
            "global": self._analyze_global(),
            "recommendations": self._generate_recommendations()
        }

    def _analyze_lanes(self) -> Dict[str, Any]:
        """Analyze performance metrics for each lane."""
        lanes = {}

        # Load and group trade data by lane
        lane_trades = self._load_lane_trades()
        lane_counterfactual = self._load_lane_counterfactual()
        scalp_counterfactual = self._load_scalp_counterfactual()

        # Define lane intents and invariants
        lane_metadata = {
            "core": {
                "intent": "production",
                "invariants": {
                    "should_trade": True,
                    "should_be_low_risk": False,
                    "should_avoid_micro_churn": True
                }
            },
            "exploration": {
                "intent": "sample_building",
                "invariants": {
                    "should_trade": True,
                    "should_be_low_risk": True,
                    "should_avoid_micro_churn": True
                }
            },
            "recovery": {
                "intent": "earn_back",
                "invariants": {
                    "should_trade": True,
                    "should_be_low_risk": True,
                    "should_avoid_micro_churn": True
                }
            },
            "quarantine": {
                "intent": "no_trading",
                "invariants": {
                    "should_trade": False,
                    "should_be_low_risk": True,
                    "should_avoid_micro_churn": True
                }
            },
            "scalp": {
                "intent": "micro_edge",
                "invariants": {
                    "should_trade": True,
                    "should_be_low_risk": True,
                    "should_avoid_micro_churn": False  # SCALP is allowed to be fast
                }
            },
            "expansion": {
                "intent": "breakout_continuation",
                "invariants": {
                    "should_trade": True,
                    "should_be_low_risk": False,  # Expansion trades are higher risk
                    "should_avoid_micro_churn": True
                }
            }
        }

        for lane_id, metadata in lane_metadata.items():
            cf_data = lane_counterfactual.get(lane_id, [])

            lanes[lane_id] = self._analyze_single_lane(
                lane_id, metadata, lane_trades.get(lane_id, []), cf_data
            )

            # For SCALP, add specialized counterfactual analysis
            if lane_id == "scalp" and scalp_counterfactual:
                lanes[lane_id]["counterfactual"] = scalp_counterfactual

        # Add unknown lane for legacy trades
        if lane_trades.get("unknown"):
            lanes["unknown"] = self._analyze_legacy_lane(lane_trades["unknown"])

        return lanes

    def _load_lane_trades(self) -> Dict[str, List[Dict[str, Any]]]:
        """Load and group trades by lane_id."""
        lane_trades = defaultdict(list)

        trades_file = Path("reports/trades.jsonl")
        if not trades_file.exists():
            return lane_trades

        with open(trades_file, 'r') as f:
            for line in f:
                try:
                    event = json.loads(line.strip())
                    if event.get("type") not in ("open", "close"):
                        continue

                    ts = event.get("ts")
                    if not ts:
                        continue

                    event_ts = parser.isoparse(ts.replace("Z", "+00:00"))
                    if not (self.start_ts <= event_ts <= self.end_ts):
                        continue

                    # Use lane_id, fallback to trade_kind mapping for legacy
                    lane_id = event.get("lane_id") or self._infer_lane_from_trade_kind(event.get("trade_kind"))
                    if lane_id:
                        lane_trades[lane_id].append(event)

                except (json.JSONDecodeError, ValueError):
                    continue

        return dict(lane_trades)

    def _infer_lane_from_trade_kind(self, trade_kind: Optional[str]) -> Optional[str]:
        """Map legacy trade_kind to lane_id."""
        if not trade_kind:
            return "unknown"

        mapping = {
            "normal": "core",
            "exploration": "exploration",
            "recovery_v2": "recovery"
        }
        return mapping.get(trade_kind, "unknown")

    def _load_lane_counterfactual(self) -> Dict[str, List[Dict[str, Any]]]:
        """Load and group counterfactual outcomes by lane_id."""
        lane_outcomes = defaultdict(list)

        cf_file = Path("reports/counterfactual_ledger.jsonl")
        if not cf_file.exists():
            return lane_outcomes

        with open(cf_file, 'r') as f:
            for line in f:
                try:
                    outcome = json.loads(line.strip())
                    if outcome.get("type") != "outcome":
                        continue

                    ts = outcome.get("exit_ts") or outcome.get("ts")
                    if not ts:
                        continue

                    outcome_ts = parser.isoparse(ts.replace("Z", "+00:00"))
                    if not (self.start_ts <= outcome_ts <= self.end_ts):
                        continue

                    lane_id = outcome.get("lane_id") or "unknown"
                    lane_outcomes[lane_id].append(outcome)

                except (json.JSONDecodeError, ValueError):
                    continue

        return dict(lane_outcomes)

    def _load_scalp_counterfactual(self) -> Optional[Dict[str, Any]]:
        """Load SCALP-specific counterfactual analysis if available."""
        try:
            import json
            scalp_file = Path("reports/reflect/scalp_counterfactual.json")
            if scalp_file.exists():
                with open(scalp_file, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        return None

    def _analyze_single_lane(self, lane_id: str, metadata: Dict[str, Any],
                           trades: List[Dict[str, Any]],
                           cf_outcomes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze a single lane's performance."""

        # Volume metrics
        opens = len([t for t in trades if t.get("type") == "open"])
        closes = len([t for t in trades if t.get("type") == "close"])

        # Duration analysis
        durations = []
        regime_counts = Counter()

        for trade in trades:
            if trade.get("type") == "close":
                duration = trade.get("duration_s")
                if duration is not None:
                    durations.append(duration)

                regime = trade.get("regime_at_entry") or trade.get("regime")
                if regime:
                    regime_counts[regime] += 1

        # Performance metrics from closes
        close_events = [t for t in trades if t.get("type") == "close"]
        pcts = [t.get("pct", 0.0) for t in close_events if t.get("pct") is not None]

        # Calculate metrics
        volume_metrics = self._calculate_volume_metrics(durations)
        performance_metrics = self._calculate_performance_metrics(pcts)
        cf_metrics = self._calculate_counterfactual_metrics(cf_outcomes)
        regime_breakdown = self._calculate_regime_breakdown(close_events)
        signals = self._analyze_signals(trades, durations, pcts)
        diagnosis = self._generate_diagnosis(lane_id, performance_metrics, cf_metrics, signals)
        proposals = self._generate_lane_proposals(lane_id, diagnosis, performance_metrics, signals)

        return {
            "lane_id": lane_id,
            "intent": metadata["intent"],
            "invariants": metadata["invariants"],
            "volume": volume_metrics,
            "performance": performance_metrics,
            "counterfactual": cf_metrics,
            "regime_breakdown": regime_breakdown,
            "signals": signals,
            "diagnosis": diagnosis,
            "proposals": proposals
        }

    def _calculate_volume_metrics(self, durations: List[float]) -> Dict[str, Any]:
        """Calculate volume and duration metrics."""
        if not durations:
            return {
                "opens": 0,
                "closes": 0,
                "avg_duration_s": None,
                "p50_duration_s": None,
                "p90_duration_s": None
            }

        durations_sorted = sorted(durations)
        n = len(durations_sorted)

        return {
            "opens": len(durations),  # Approximate
            "closes": n,
            "avg_duration_s": round(statistics.mean(durations), 1) if durations else None,
            "p50_duration_s": durations_sorted[n//2] if n > 0 else None,
            "p90_duration_s": durations_sorted[int(n*0.9)] if n > 0 else None
        }

    def _calculate_performance_metrics(self, pcts: List[float]) -> Dict[str, Any]:
        """Calculate performance metrics from P&L percentages."""
        if not pcts:
            return {
                "pf": None,
                "win_rate": None,
                "gross_profit": 0.0,
                "gross_loss": 0.0,
                "avg_pct": None,
                "max_dd": None
            }

        wins = [p for p in pcts if p > 0]
        losses = [p for p in pcts if p < 0]

        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0

        pf = gross_profit / gross_loss if gross_loss > 0 else (float('inf') if gross_profit > 0 else 1.0)

        # Simple max drawdown approximation
        cumulative = 0.0
        max_dd = 0.0
        peak = 0.0
        for p in pcts:
            cumulative += p
            peak = max(peak, cumulative)
            max_dd = max(max_dd, peak - cumulative)

        # Add display-friendly PF information
        if pf == float('inf'):
            pf_display = "∞"
            pf_status = "no_losses"
        elif pf == 1.0 and gross_profit == 0 and gross_loss == 0:
            pf_display = "—"
            pf_status = "no_trades"
        else:
            pf_display = f"{pf:.2f}"
            pf_status = "normal"

        return {
            "pf": round(pf, 3) if pf != float('inf') else None,
            "pf_display": pf_display,
            "pf_status": pf_status,
            "win_rate": round(len(wins) / len(pcts), 3) if pcts else None,
            "gross_profit": round(gross_profit, 4),
            "gross_loss": round(gross_loss, 4),
            "avg_pct": round(statistics.mean(pcts), 6) if pcts else None,
            "max_dd": round(max_dd, 4)
        }

    def _calculate_counterfactual_metrics(self, cf_outcomes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate counterfactual performance metrics."""
        if not cf_outcomes:
            return {
                "outcomes_n": 0,
                "net_edge": None,
                "confidence_gradient": None,
                "blocking_efficiency": None
            }

        # Calculate weighted net edge
        deltas = []
        weights = []
        confidences = []
        blocking_signals = []

        for outcome in cf_outcomes:
            actual = outcome.get("actual_pnl_pct")
            cf = outcome.get("counterfactual_pnl_pct")
            if actual is not None and cf is not None:
                delta = actual - cf
                deltas.append(delta)
                weights.append(outcome.get("weight", 1.0))

                # For confidence gradient
                confidence = outcome.get("confidence_at_decision")
                if confidence is not None:
                    confidences.append((confidence, delta))

                # For blocking efficiency (if available)
                blocked = outcome.get("blocked", outcome.get("was_blocked"))
                if blocked is not None:
                    blocking_signals.append(1 if delta > 0 else 0)

        # Weighted mean for net_edge
        if deltas and weights:
            total_weight = sum(weights)
            weighted_sum = sum(d * w for d, w in zip(deltas, weights))
            net_edge = weighted_sum / total_weight if total_weight > 0 else statistics.mean(deltas)
        else:
            net_edge = statistics.mean(deltas) if deltas else None

        # Confidence gradient (correlation between confidence and delta)
        confidence_gradient = None
        if len(confidences) >= 2:
            conf_values, delta_values = zip(*confidences)
            try:
                # Simple correlation coefficient
                conf_mean = statistics.mean(conf_values)
                delta_mean = statistics.mean(delta_values)
                conf_std = statistics.stdev(conf_values) if len(conf_values) > 1 else 1
                delta_std = statistics.stdev(delta_values) if len(delta_values) > 1 else 1

                if conf_std > 0 and delta_std > 0:
                    correlation = sum((c - conf_mean) * (d - delta_mean)
                                    for c, d in zip(conf_values, delta_values))
                    correlation /= (len(conf_values) - 1) * conf_std * delta_std
                    confidence_gradient = round(correlation, 4)
            except:
                confidence_gradient = None

        # Blocking efficiency
        blocking_efficiency = None
        if blocking_signals:
            blocking_efficiency = round(sum(blocking_signals) / len(blocking_signals), 4)

        return {
            "outcomes_n": len(cf_outcomes),
            "net_edge": round(net_edge, 6) if net_edge is not None else None,
            "confidence_gradient": confidence_gradient,
            "blocking_efficiency": blocking_efficiency
        }

    def _calculate_regime_breakdown(self, close_events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate performance breakdown by regime."""
        regime_data = defaultdict(list)

        for event in close_events:
            regime = event.get("regime_at_entry") or event.get("regime") or "unknown"
            pct = event.get("pct")
            if pct is not None:
                regime_data[regime].append(pct)

        breakdown = {}
        for regime, pcts in regime_data.items():
            if pcts:
                wins = sum(1 for p in pcts if p > 0)
                gross_profit = sum(p for p in pcts if p > 0)
                gross_loss = abs(sum(p for p in pcts if p < 0))

                pf = gross_profit / gross_loss if gross_loss > 0 else (float('inf') if gross_profit > 0 else 1.0)

                breakdown[regime] = {
                    "n": len(pcts),
                    "pf": round(pf, 3) if pf != float('inf') else 999.0
                }

        return breakdown

    def _analyze_signals(self, trades: List[Dict[str, Any]], durations: List[float],
                        pcts: List[float]) -> Dict[str, Any]:
        """Analyze signal patterns and risk flags."""
        signals = {
            "top_contributors": [],
            "risk_flags": [],
            "micro_churn_analysis": {
                "rate_30s": 0.0,
                "rate_5min": 0.0,
                "count_30s": 0,
                "count_5min": 0,
                "pf_micro": None,
                "pf_non_micro": None,
                "total_trades": len(durations) if durations else 0
            }
        }

        if durations:
            # Micro-churn analysis
            micro_30s = [d for d in durations if d < 30]
            micro_5min = [d for d in durations if d < 300]  # 5 minutes

            signals["micro_churn_analysis"]["count_30s"] = len(micro_30s)
            signals["micro_churn_analysis"]["count_5min"] = len(micro_5min)
            signals["micro_churn_analysis"]["rate_30s"] = len(micro_30s) / len(durations)
            signals["micro_churn_analysis"]["rate_5min"] = len(micro_5min) / len(durations)

            # Separate PF for micro vs non-micro trades
            micro_indices = [i for i, d in enumerate(durations) if d < 30]
            non_micro_indices = [i for i, d in enumerate(durations) if d >= 30]

            if micro_indices and len(micro_indices) >= 3:  # Need minimum sample
                micro_pcts = [pcts[i] for i in micro_indices if i < len(pcts)]
                if micro_pcts:
                    wins = sum(1 for p in micro_pcts if p > 0)
                    gross_profit = sum(p for p in micro_pcts if p > 0)
                    gross_loss = abs(sum(p for p in micro_pcts if p < 0))
                    signals["micro_churn_analysis"]["pf_micro"] = round(gross_profit / gross_loss, 3) if gross_loss > 0 else (999.0 if gross_profit > 0 else 1.0)

            if non_micro_indices and len(non_micro_indices) >= 3:
                non_micro_pcts = [pcts[i] for i in non_micro_indices if i < len(pcts)]
                if non_micro_pcts:
                    wins = sum(1 for p in non_micro_pcts if p > 0)
                    gross_profit = sum(p for p in non_micro_pcts if p > 0)
                    gross_loss = abs(sum(p for p in non_micro_pcts if p < 0))
                    signals["micro_churn_analysis"]["pf_non_micro"] = round(gross_profit / gross_loss, 3) if gross_loss > 0 else (999.0 if gross_profit > 0 else 999.0)

            # Risk flags based on micro-churn
            if signals["micro_churn_analysis"]["rate_30s"] > 0.3:  # >30% micro-churn
                signals["risk_flags"].append("high_micro_churn_30s")
            elif signals["micro_churn_analysis"]["rate_30s"] > 0.1:  # >10% micro-churn
                signals["risk_flags"].append("moderate_micro_churn_30s")

            if signals["micro_churn_analysis"]["rate_5min"] > 0.5:  # >50% <5min
                signals["risk_flags"].append("high_micro_churn_5min")

        # Detect exit latency issues (separate from micro-churn)
        if durations:
            very_short_exits = sum(1 for d in durations if d < 60)
            if very_short_exits > len(durations) * 0.5:  # >50% very short
                signals["risk_flags"].append("exit_latency_short")

        # Placeholder for signal contribution analysis
        signals["top_contributors"] = ["meanrev", "timing"]  # Would analyze actual signals

        return signals

    def _generate_diagnosis(self, lane_id: str, performance: Dict[str, Any],
                          cf: Dict[str, Any], signals: Dict[str, Any]) -> Dict[str, Any]:
        """Generate diagnosis and confidence score."""
        confidence = 0.5  # Base confidence

        summary_parts = []

        # Performance assessment
        if performance.get("pf") and performance["pf"] > 1.05:
            summary_parts.append("profitable")
            confidence += 0.1
        elif performance.get("pf") and performance["pf"] < 0.95:
            summary_parts.append("unprofitable")
            confidence -= 0.1

        # Risk assessment
        if "micro_churn_cluster" in signals.get("risk_flags", []):
            summary_parts.append("micro-churny")
            confidence -= 0.1

        # Counterfactual assessment
        if cf.get("net_edge") and cf["net_edge"] > 0.0001:
            summary_parts.append("shows edge")
            confidence += 0.1
        elif cf.get("net_edge") and cf["net_edge"] < -0.0001:
            summary_parts.append("bleeding vs baseline")
            confidence -= 0.1

        summary = f"{lane_id.title()} is {' and '.join(summary_parts) if summary_parts else 'insufficient data'}."

        return {
            "summary": summary,
            "confidence_0_to_1": max(0.0, min(1.0, confidence))
        }

    def _generate_lane_proposals(self, lane_id: str, diagnosis: Dict[str, Any],
                               performance: Dict[str, Any], signals: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        """Generate adjustment proposals for the lane."""
        proposals = {"soft": [], "hard_candidates": []}

        confidence = diagnosis.get("confidence_0_to_1", 0.5)

        # Generate proposals based on signals and performance
        if "micro_churn_cluster" in signals.get("risk_flags", []):
            if confidence >= 0.6:
                proposals["soft"].append({
                    "kind": "threshold_delta",
                    "target": "chop_entry_min",
                    "delta": 0.02,
                    "why": "reduce churn frequency",
                    "risk": "low"
                })
            else:
                proposals["hard_candidates"].append({
                    "kind": "cooldown_minutes",
                    "target": f"{lane_id}_chop",
                    "value": 15,
                    "why": "prevent rapid re-entry loops",
                    "risk": "medium"
                })

        if performance.get("pf") and performance["pf"] < 0.95:
            proposals["hard_candidates"].append({
                "kind": "lane_status",
                "target": lane_id,
                "action": "reduce_exposure",
                "why": "poor risk-adjusted returns",
                "risk": "high"
            })

        return proposals

    def _analyze_legacy_lane(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze legacy trades that don't have lane_id (summary only)."""
        close_events = [t for t in trades if t.get("type") == "close"]
        durations = []
        regime_counts = Counter()
        pcts = []

        for trade in close_events:
            duration = trade.get("duration_s")
            if duration is not None:
                durations.append(duration)

            regime = trade.get("regime_at_entry") or trade.get("regime")
            if regime:
                regime_counts[regime] += 1

            pct = trade.get("pct")
            if pct is not None:
                pcts.append(pct)

        volume_metrics = self._calculate_volume_metrics(durations)
        performance_metrics = self._calculate_performance_metrics(pcts)
        regime_breakdown = self._calculate_regime_breakdown(close_events)

        return {
            "lane_id": "unknown",
            "intent": "legacy",
            "invariants": {
                "should_trade": None,
                "should_be_low_risk": None,
                "should_avoid_micro_churn": None
            },
            "volume": volume_metrics,
            "performance": performance_metrics,
            "counterfactual": {
                "outcomes_n": 0,
                "net_edge": None,
                "confidence_gradient": None,
                "blocking_efficiency": None
            },
            "regime_breakdown": regime_breakdown,
            "signals": {
                "top_contributors": [],
                "risk_flags": ["legacy_data"]
            },
            "diagnosis": {
                "summary": "Legacy trades without lane classification",
                "confidence_0_to_1": 0.0
            },
            "proposals": {
                "soft": [],
                "hard_candidates": []
            }
        }

    def _analyze_global(self) -> Dict[str, Any]:
        """Analyze global system health and market conditions."""
        # Read loop health
        system_health = {"loop_ok": True, "issues": []}

        loop_health_paths = [
            Path("reports/loop/loop_health.json"),
            Path("reports/loop_health.json")
        ]

        loop_health = None
        for path in loop_health_paths:
            if path.exists():
                try:
                    with open(path, 'r') as f:
                        loop_health = json.load(f)
                    break
                except (json.JSONDecodeError, IOError):
                    continue

        if loop_health:
            system_health["loop_ok"] = loop_health.get("ok", True)
            issues = []
            if not loop_health.get("ok", True):
                issues.append("loop_health_not_ok")
            system_health["issues"] = issues
        else:
            system_health["issues"] = ["loop_health_missing"]

        # Compute market mix from regime data in trades
        regime_totals = Counter()
        total_regime_events = 0

        # Aggregate regime data from all trades
        lane_trades = self._load_lane_trades()
        for trades in lane_trades.values():
            for trade in trades:
                if trade.get("type") == "close":
                    regime = trade.get("regime_at_entry") or trade.get("regime") or "unknown"
                    regime_totals[regime] += 1
                    total_regime_events += 1

        market_mix = {}
        if total_regime_events > 0:
            for regime, count in regime_totals.items():
                market_mix[regime] = round(count / total_regime_events, 3)

        return {
            "system_health": system_health,
            "market_mix": {"regimes": market_mix}
        }

    def _generate_recommendations(self) -> Dict[str, List[Any]]:
        """Generate global recommendations including micro-churn analysis."""
        # First generate the lanes data
        lanes_data = self._analyze_lanes()

        recommendations = {
            "soft": [],
            "hard_candidates": [],
            "micro_churn_summary": {
                "total_trades": 0,
                "micro_30s_rate": 0.0,
                "micro_5min_rate": 0.0,
                "micro_30s_count": 0,
                "micro_5min_count": 0,
                "pf_micro": None,
                "pf_non_micro": None,
                "risk_assessment": "unknown"
            }
        }

        # Aggregate micro-churn across all lanes
        total_trades = 0
        total_micro_30s = 0
        total_micro_5min = 0

        for lane_data in lanes_data.values():
            signals = lane_data.get("signals", {})
            micro_analysis = signals.get("micro_churn_analysis", {})

            total_trades += micro_analysis.get("total_trades", 0)
            total_micro_30s += micro_analysis.get("count_30s", 0)
            total_micro_5min += micro_analysis.get("count_5min", 0)

        if total_trades > 0:
            recommendations["micro_churn_summary"]["total_trades"] = total_trades
            recommendations["micro_churn_summary"]["micro_30s_rate"] = round(total_micro_30s / total_trades, 3)
            recommendations["micro_churn_summary"]["micro_5min_rate"] = round(total_micro_5min / total_trades, 3)
            recommendations["micro_churn_summary"]["micro_30s_count"] = total_micro_30s
            recommendations["micro_churn_summary"]["micro_5min_count"] = total_micro_5min

            # Risk assessment
            micro_rate = recommendations["micro_churn_summary"]["micro_30s_rate"]
            if micro_rate > 0.3:
                recommendations["micro_churn_summary"]["risk_assessment"] = "high_risk"
                recommendations["hard_candidates"].append({
                    "kind": "global_cooldown_policy",
                    "target": "all_lanes",
                    "action": "implement_minimum_hold_30s",
                    "why": f"High micro-churn rate ({micro_rate:.1%}) indicates need for minimum hold times",
                    "risk": "medium"
                })
            elif micro_rate > 0.1:
                recommendations["micro_churn_summary"]["risk_assessment"] = "moderate_risk"
                recommendations["soft"].append({
                    "kind": "global_cooldown_policy",
                    "target": "all_lanes",
                    "action": "monitor_micro_churn",
                    "why": f"Moderate micro-churn rate ({micro_rate:.1%}) - monitor for PF degradation",
                    "risk": "low"
                })
            else:
                recommendations["micro_churn_summary"]["risk_assessment"] = "low_risk"

        return recommendations


def generate_lane_reflection_artifact(window_hours: int = 24) -> Dict[str, Any]:
    """Generate and return the lane reflection artifact."""
    reflection = LaneReflection(window_hours=window_hours)
    return reflection.generate_reflection()


def save_lane_reflection_artifact(window_hours: int = 24) -> str:
    """Generate and save the lane reflection artifact with atomic writes."""
    artifact = generate_lane_reflection_artifact(window_hours)

    # Ensure directory exists
    output_dir = Path("reports/reflect")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Atomic write for main artifact
    output_file = output_dir / "lane_reflection.json"
    with tempfile.NamedTemporaryFile(
        mode='w',
        encoding='utf-8',
        dir=output_dir,
        delete=False,
        suffix='.tmp'
    ) as temp_file:
        json.dump(artifact, temp_file, indent=2)
        temp_path = Path(temp_file.name)

    # Atomic replace
    temp_path.replace(output_file)

    # Optional: append to log (not atomic since it's append-only)
    log_file = output_dir / "lane_reflection_log.jsonl"
    
    # Safely get generated_at with fallback
    generated_at = artifact.get("generated_at", datetime.now(timezone.utc).isoformat())
    
    with open(log_file, 'a') as f:
        f.write(json.dumps({
            "timestamp": generated_at,
            "window_hours": window_hours,
            "summary": {
                lane_id: {
                    "confidence": lane.get("diagnosis", {}).get("confidence_0_to_1", 0.0),
                    "soft_proposals": len(lane.get("proposals", {}).get("soft", [])),
                    "hard_proposals": len(lane.get("proposals", {}).get("hard_candidates", []))
                }
                for lane_id, lane in artifact.get("lanes", {}).items()
            }
        }) + "\n")

    return str(output_file)


if __name__ == "__main__":
    # Generate and save artifact
    output_file = save_lane_reflection_artifact()
    print(f"Generated lane reflection: {output_file}")

    # Print summary
    with open(output_file, 'r') as f:
        artifact = json.load(f)

    print("\nLane Summary:")
    for lane_id, lane in artifact.get("lanes", {}).items():
        diagnosis = lane.get("diagnosis", {})
        proposals = lane.get("proposals", {})
        print(f"  {lane_id}: confidence={diagnosis.get('confidence_0_to_1', 0.0):.2f}, "
              f"soft={len(proposals.get('soft', []))}, hard={len(proposals.get('hard_candidates', []))}")
