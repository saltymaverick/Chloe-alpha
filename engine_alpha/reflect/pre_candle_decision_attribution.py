"""
Pre-Candle Intelligence (PCI) - Decision Attribution Report Module
Phase 3 (Alt): Analysis-only report on PCI scores across decision events

Analyzes PCI scores in decision logs (why_blocked, gate logs) to understand:
- PCI distribution across regimes and block reasons
- Correlation between high PCI and blocked decisions
- PCI behavior patterns even when trades are halted
"""

from __future__ import annotations

import json
import csv
import glob
import os
import statistics
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timezone
from collections import defaultdict

from engine_alpha.core.paths import REPORTS, CONFIG


# Default thresholds from config
DEFAULT_TRAP_BLOCK = 0.70
DEFAULT_FAKEOUT_BLOCK = 0.65
DEFAULT_CROWDING_TIGHTEN = 0.70


def _load_pci_config() -> Dict[str, float]:
    """Load PCI config to get default thresholds."""
    try:
        config_path = CONFIG / "engine_config.json"
        if config_path.exists():
            with config_path.open() as f:
                cfg = json.load(f)
                pci_cfg = cfg.get("pre_candle", {})
                thresholds = pci_cfg.get("thresholds", {})
                return {
                    "trap_block": thresholds.get("trap_block", DEFAULT_TRAP_BLOCK),
                    "fakeout_block": thresholds.get("fakeout_block", DEFAULT_FAKEOUT_BLOCK),
                    "crowding_tighten": thresholds.get("crowding_tighten", DEFAULT_CROWDING_TIGHTEN),
                }
    except Exception:
        pass
    return {
        "trap_block": DEFAULT_TRAP_BLOCK,
        "fakeout_block": DEFAULT_FAKEOUT_BLOCK,
        "crowding_tighten": DEFAULT_CROWDING_TIGHTEN,
    }


def _find_decision_logs() -> List[Path]:
    """Auto-discover decision log files."""
    candidates = []
    
    # Common locations
    search_paths = [
        REPORTS / "debug" / "why_blocked.jsonl",
        REPORTS / "**" / "why_blocked*.jsonl",
        REPORTS / "**" / "gate*.jsonl",
        REPORTS / "**" / "signals_history*.jsonl",
        REPORTS / "**" / "latest_signals*.json",
    ]
    
    for pattern in search_paths:
        if "*" in str(pattern):
            candidates.extend(Path(REPORTS).glob(str(pattern.relative_to(REPORTS))))
        else:
            if pattern.exists():
                candidates.append(pattern)
    
    # Also check logs/ and data/ if they exist
    for base_dir in [Path("logs"), Path("data")]:
        if base_dir.exists():
            candidates.extend(base_dir.glob("**/why_blocked*.jsonl"))
            candidates.extend(base_dir.glob("**/gate*.jsonl"))
    
    # Deduplicate and return existing files
    seen = set()
    found = []
    for path in candidates:
        if path.exists() and path not in seen:
            seen.add(path)
            found.append(path)
    
    return found


def _parse_timestamp(ts: Any) -> Optional[datetime]:
    """Parse timestamp from various formats."""
    if ts is None:
        return None
    
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            return None
    
    if isinstance(ts, str):
        try:
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            pass
        
        for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]:
            try:
                return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
            except Exception:
                continue
    
    return None


def _load_decision_logs(log_paths: List[Path]) -> List[Dict[str, Any]]:
    """Load decision logs from jsonl files."""
    decisions = []
    
    for path in log_paths:
        if not path.exists():
            continue
        
        try:
            with path.open("r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        decisions.append(entry)
                    except Exception:
                        continue
        except Exception:
            continue
    
    return decisions


def _extract_pci_from_decision(decision: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """Extract PCI scores from decision record."""
    # Try direct pre_candle field
    pre_candle = decision.get("pre_candle")
    if pre_candle and isinstance(pre_candle, dict):
        scores = pre_candle.get("scores")
        if scores and isinstance(scores, dict):
            return scores
    
    # Try nested in signal_dict or similar
    signal_dict = decision.get("signal_dict", {})
    if signal_dict:
        pre_candle = signal_dict.get("pre_candle")
        if pre_candle and isinstance(pre_candle, dict):
            scores = pre_candle.get("scores")
            if scores and isinstance(scores, dict):
                return scores
    
    return None


def _compute_statistics(values: List[float]) -> Dict[str, float]:
    """Compute statistics for a list of values."""
    if not values:
        return {"mean": 0.0, "median": 0.0, "p90": 0.0, "min": 0.0, "max": 0.0, "count": 0}
    
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    
    return {
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "p90": sorted_vals[int(n * 0.9)] if n > 0 else 0.0,
        "min": min(values),
        "max": max(values),
        "count": n,
    }


def _classify_high_risk(
    pci_scores: Optional[Dict[str, float]],
    trap_threshold: float,
    fakeout_threshold: float
) -> Dict[str, bool]:
    """Classify if PCI indicates high risk."""
    if not pci_scores:
        return {
            "high_trap": False,
            "high_fakeout": False,
            "high_overall": False,
        }
    
    liquidity_trap = pci_scores.get("liquidity_trap_score", 0.0)
    fakeout_risk = pci_scores.get("fakeout_risk", 0.0)
    overall_score = pci_scores.get("overall_score", 0.0)
    
    high_trap = liquidity_trap >= trap_threshold
    high_fakeout = fakeout_risk >= fakeout_threshold
    high_overall = (
        overall_score >= max(trap_threshold, fakeout_threshold) or
        high_trap or
        high_fakeout
    )
    
    return {
        "high_trap": high_trap,
        "high_fakeout": high_fakeout,
        "high_overall": high_overall,
    }


def analyze_decision_attribution(log_paths: Optional[List[Path]] = None) -> Dict[str, Any]:
    """
    Analyze PCI scores across decision events.
    
    Args:
        log_paths: Optional list of log file paths (auto-discovers if None)
    
    Returns:
        Dict with analysis results
    """
    # Load config
    config = _load_pci_config()
    trap_threshold = config["trap_block"]
    fakeout_threshold = config["fakeout_block"]
    
    # Find and load decision logs
    if log_paths is None:
        log_paths = _find_decision_logs()
    
    if not log_paths:
        return {
            "error": "No decision log files found",
            "searched_paths": [],
        }
    
    decisions = _load_decision_logs(log_paths)
    
    if not decisions:
        return {
            "error": "No decision records found in log files",
            "log_paths": [str(p) for p in log_paths],
        }
    
    # Analyze decisions
    total_decisions = len(decisions)
    decisions_with_pci = 0
    
    # Collectors
    block_reason_counts = defaultdict(int)
    regime_counts = defaultdict(int)
    dir_counts = defaultdict(int)
    
    # PCI score collectors
    trap_scores = []
    fakeout_scores = []
    crowding_scores = []
    overall_scores = []
    
    # Segmented collectors
    trap_by_reason = defaultdict(list)
    fakeout_by_reason = defaultdict(list)
    overall_by_reason = defaultdict(list)
    
    trap_by_regime = defaultdict(list)
    fakeout_by_regime = defaultdict(list)
    overall_by_regime = defaultdict(list)
    
    trap_by_dir = defaultdict(list)
    fakeout_by_dir = defaultdict(list)
    overall_by_dir = defaultdict(list)
    
    # High-risk flags
    high_trap_count = 0
    high_fakeout_count = 0
    high_overall_count = 0
    
    high_trap_by_reason = defaultdict(int)
    high_fakeout_by_reason = defaultdict(int)
    high_overall_by_reason = defaultdict(int)
    
    high_trap_by_regime = defaultdict(int)
    high_fakeout_by_regime = defaultdict(int)
    high_overall_by_regime = defaultdict(int)
    
    high_trap_by_dir = defaultdict(int)
    high_fakeout_by_dir = defaultdict(int)
    high_overall_by_dir = defaultdict(int)
    
    # Examples for CSV
    examples = []
    
    for decision in decisions:
        # Extract basic fields
        block_reason = decision.get("reason", "unknown")
        regime = decision.get("regime", "unknown")
        direction = decision.get("dir", 0)
        dir_key = "dir_zero" if direction == 0 else "directional"
        
        block_reason_counts[block_reason] += 1
        regime_counts[regime] += 1
        dir_counts[dir_key] += 1
        
        # Extract PCI
        pci_scores = _extract_pci_from_decision(decision)
        
        if pci_scores:
            decisions_with_pci += 1
            
            liquidity_trap = pci_scores.get("liquidity_trap_score", 0.0)
            fakeout_risk = pci_scores.get("fakeout_risk", 0.0)
            crowding_risk = pci_scores.get("crowding_risk_score", 0.0)
            overall_score = pci_scores.get("overall_score", 0.0)
            
            trap_scores.append(liquidity_trap)
            fakeout_scores.append(fakeout_risk)
            crowding_scores.append(crowding_risk)
            overall_scores.append(overall_score)
            
            # Segment by reason
            trap_by_reason[block_reason].append(liquidity_trap)
            fakeout_by_reason[block_reason].append(fakeout_risk)
            overall_by_reason[block_reason].append(overall_score)
            
            # Segment by regime
            trap_by_regime[regime].append(liquidity_trap)
            fakeout_by_regime[regime].append(fakeout_risk)
            overall_by_regime[regime].append(overall_score)
            
            # Segment by direction
            trap_by_dir[dir_key].append(liquidity_trap)
            fakeout_by_dir[dir_key].append(fakeout_risk)
            overall_by_dir[dir_key].append(overall_score)
            
            # High-risk classification
            risk_flags = _classify_high_risk(pci_scores, trap_threshold, fakeout_threshold)
            
            if risk_flags["high_trap"]:
                high_trap_count += 1
                high_trap_by_reason[block_reason] += 1
                high_trap_by_regime[regime] += 1
                high_trap_by_dir[dir_key] += 1
            
            if risk_flags["high_fakeout"]:
                high_fakeout_count += 1
                high_fakeout_by_reason[block_reason] += 1
                high_fakeout_by_regime[regime] += 1
                high_fakeout_by_dir[dir_key] += 1
            
            if risk_flags["high_overall"]:
                high_overall_count += 1
                high_overall_by_reason[block_reason] += 1
                high_overall_by_regime[regime] += 1
                high_overall_by_dir[dir_key] += 1
            
            # Collect examples
            examples.append({
                "ts": decision.get("ts", ""),
                "symbol": decision.get("symbol", ""),
                "block_reason": block_reason,
                "regime": regime,
                "dir": direction,
                "conf": decision.get("conf", 0.0),
                "liquidity_trap_score": liquidity_trap,
                "fakeout_risk": fakeout_risk,
                "crowding_risk_score": crowding_risk,
                "derivatives_tension": pci_scores.get("derivatives_tension", 0.0),
                "overall_score": overall_score,
                "high_trap": risk_flags["high_trap"],
                "high_fakeout": risk_flags["high_fakeout"],
                "high_overall": risk_flags["high_overall"],
            })
    
    # Compute statistics
    pci_pct = (decisions_with_pci / total_decisions * 100.0) if total_decisions > 0 else 0.0
    
    trap_stats = _compute_statistics(trap_scores)
    fakeout_stats = _compute_statistics(fakeout_scores)
    crowding_stats = _compute_statistics(crowding_scores)
    overall_stats = _compute_statistics(overall_scores)
    
    # Compute rates
    high_trap_rate = (high_trap_count / decisions_with_pci * 100.0) if decisions_with_pci > 0 else 0.0
    high_fakeout_rate = (high_fakeout_count / decisions_with_pci * 100.0) if decisions_with_pci > 0 else 0.0
    high_overall_rate = (high_overall_count / decisions_with_pci * 100.0) if decisions_with_pci > 0 else 0.0
    
    # Compute segmented statistics
    trap_stats_by_reason = {
        reason: _compute_statistics(scores) for reason, scores in trap_by_reason.items()
    }
    fakeout_stats_by_reason = {
        reason: _compute_statistics(scores) for reason, scores in fakeout_by_reason.items()
    }
    overall_stats_by_reason = {
        reason: _compute_statistics(scores) for reason, scores in overall_by_reason.items()
    }
    
    trap_stats_by_regime = {
        regime: _compute_statistics(scores) for regime, scores in trap_by_regime.items()
    }
    fakeout_stats_by_regime = {
        regime: _compute_statistics(scores) for regime, scores in fakeout_by_regime.items()
    }
    overall_stats_by_regime = {
        regime: _compute_statistics(scores) for regime, scores in overall_by_regime.items()
    }
    
    # Sort examples by overall_score (descending)
    examples.sort(key=lambda x: x.get("overall_score", 0.0), reverse=True)
    
    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "log_paths": [str(p) for p in log_paths],
        "total_decisions": total_decisions,
        "decisions_with_pci": decisions_with_pci,
        "pci_presence_pct": pci_pct,
        "thresholds": {
            "trap_block": trap_threshold,
            "fakeout_block": fakeout_threshold,
        },
        "block_reason_counts": dict(sorted(block_reason_counts.items(), key=lambda x: x[1], reverse=True)),
        "regime_counts": dict(sorted(regime_counts.items(), key=lambda x: x[1], reverse=True)),
        "dir_counts": dict(dir_counts),
        "pci_distributions": {
            "liquidity_trap_score": trap_stats,
            "fakeout_risk": fakeout_stats,
            "crowding_risk_score": crowding_stats,
            "overall_score": overall_stats,
        },
        "high_risk_rates": {
            "high_trap": {
                "count": high_trap_count,
                "rate_pct": high_trap_rate,
            },
            "high_fakeout": {
                "count": high_fakeout_count,
                "rate_pct": high_fakeout_rate,
            },
            "high_overall": {
                "count": high_overall_count,
                "rate_pct": high_overall_rate,
            },
        },
        "high_risk_by_reason": {
            "high_trap": dict(high_trap_by_reason),
            "high_fakeout": dict(high_fakeout_by_reason),
            "high_overall": dict(high_overall_by_reason),
        },
        "high_risk_by_regime": {
            "high_trap": dict(high_trap_by_regime),
            "high_fakeout": dict(high_fakeout_by_regime),
            "high_overall": dict(high_overall_by_regime),
        },
        "high_risk_by_dir": {
            "high_trap": dict(high_trap_by_dir),
            "high_fakeout": dict(high_fakeout_by_dir),
            "high_overall": dict(high_overall_by_dir),
        },
        "pci_stats_by_reason": {
            "liquidity_trap_score": trap_stats_by_reason,
            "fakeout_risk": fakeout_stats_by_reason,
            "overall_score": overall_stats_by_reason,
        },
        "pci_stats_by_regime": {
            "liquidity_trap_score": trap_stats_by_regime,
            "fakeout_risk": fakeout_stats_by_regime,
            "overall_score": overall_stats_by_regime,
        },
        "top_examples": examples[:50],
    }


def _generate_markdown_report(analysis: Dict[str, Any]) -> str:
    """Generate markdown report."""
    lines = []
    lines.append("# Pre-Candle Intelligence (PCI) Decision Attribution Report")
    lines.append("")
    lines.append(f"**Generated:** {analysis.get('generated', 'N/A')}")
    lines.append("")
    
    # Log paths used
    log_paths = analysis.get("log_paths", [])
    if log_paths:
        lines.append("## Data Sources")
        lines.append("")
        for path in log_paths:
            lines.append(f"- `{path}`")
        lines.append("")
    
    # Summary
    total = analysis.get("total_decisions", 0)
    with_pci = analysis.get("decisions_with_pci", 0)
    pci_pct = analysis.get("pci_presence_pct", 0.0)
    
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Total Decisions:** {total}")
    lines.append(f"- **Decisions with PCI:** {with_pci} ({pci_pct:.1f}%)")
    lines.append("")
    
    if with_pci == 0:
        lines.append("⚠️ **No PCI data found in decision logs.**")
        lines.append("")
        lines.append("PCI scores are not currently included in decision logs.")
        lines.append("To enable decision-level attribution, PCI snapshots need to be added to `why_blocked` entries.")
        lines.append("")
        return "\n".join(lines)
    
    # Thresholds
    thresholds = analysis.get("thresholds", {})
    lines.append("## Thresholds")
    lines.append("")
    lines.append(f"- **Trap Block:** {thresholds.get('trap_block', 0.0):.2f}")
    lines.append(f"- **Fakeout Block:** {thresholds.get('fakeout_block', 0.0):.2f}")
    lines.append("")
    
    # Block reason counts
    block_reasons = analysis.get("block_reason_counts", {})
    if block_reasons:
        lines.append("## Top Block Reasons")
        lines.append("")
        lines.append("| Reason | Count |")
        lines.append("|--------|-------|")
        for reason, count in list(block_reasons.items())[:10]:
            lines.append(f"| {reason[:50]} | {count} |")
        lines.append("")
    
    # Regime counts
    regime_counts = analysis.get("regime_counts", {})
    if regime_counts:
        lines.append("## Regime Distribution")
        lines.append("")
        lines.append("| Regime | Count |")
        lines.append("|--------|-------|")
        for regime, count in sorted(regime_counts.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"| {regime} | {count} |")
        lines.append("")
    
    # PCI distributions
    distributions = analysis.get("pci_distributions", {})
    if distributions:
        lines.append("## PCI Score Distributions")
        lines.append("")
        lines.append("| Score | Mean | Median | P90 | Min | Max | Count |")
        lines.append("|-------|------|--------|-----|-----|-----|-------|")
        for score_name, stats in distributions.items():
            lines.append(
                f"| {score_name} | {stats.get('mean', 0.0):.3f} | {stats.get('median', 0.0):.3f} | "
                f"{stats.get('p90', 0.0):.3f} | {stats.get('min', 0.0):.3f} | {stats.get('max', 0.0):.3f} | "
                f"{stats.get('count', 0)} |"
            )
        lines.append("")
    
    # High-risk rates
    high_risk = analysis.get("high_risk_rates", {})
    if high_risk:
        lines.append("## High-Risk PCI Rates")
        lines.append("")
        lines.append("| Risk Type | Count | Rate (%) |")
        lines.append("|-----------|-------|----------|")
        for risk_type, data in high_risk.items():
            count = data.get("count", 0)
            rate = data.get("rate_pct", 0.0)
            lines.append(f"| {risk_type} | {count} | {rate:.1f}% |")
        lines.append("")
    
    # High-risk by regime
    high_risk_by_regime = analysis.get("high_risk_by_regime", {})
    if high_risk_by_regime:
        lines.append("## High-Risk Rates by Regime")
        lines.append("")
        regimes = set()
        for risk_data in high_risk_by_regime.values():
            regimes.update(risk_data.keys())
        
        if regimes:
            lines.append("| Regime | High Trap | High Fakeout | High Overall |")
            lines.append("|--------|-----------|--------------|-------------|")
            for regime in sorted(regimes):
                trap_count = high_risk_by_regime.get("high_trap", {}).get(regime, 0)
                fakeout_count = high_risk_by_regime.get("high_fakeout", {}).get(regime, 0)
                overall_count = high_risk_by_regime.get("high_overall", {}).get(regime, 0)
                lines.append(f"| {regime} | {trap_count} | {fakeout_count} | {overall_count} |")
            lines.append("")
    
    # PCI stats by block reason
    stats_by_reason = analysis.get("pci_stats_by_reason", {})
    if stats_by_reason and stats_by_reason.get("overall_score"):
        lines.append("## PCI Overall Score by Block Reason")
        lines.append("")
        lines.append("| Block Reason | Mean | Median | P90 | Count |")
        lines.append("|--------------|------|--------|-----|-------|")
        for reason, stats in list(stats_by_reason["overall_score"].items())[:10]:
            lines.append(
                f"| {reason[:40]} | {stats.get('mean', 0.0):.3f} | {stats.get('median', 0.0):.3f} | "
                f"{stats.get('p90', 0.0):.3f} | {stats.get('count', 0)} |"
            )
        lines.append("")
    
    # Top examples
    examples = analysis.get("top_examples", [])
    if examples:
        lines.append("## Top 10 High-Risk Decisions")
        lines.append("")
        lines.append("| TS | Symbol | Reason | Regime | Dir | Conf | Trap | Fakeout | Overall |")
        lines.append("|----|--------|--------|--------|-----|------|------|---------|---------|")
        for ex in examples[:10]:
            ts_short = ex.get("ts", "")[:19] if ex.get("ts") else "N/A"
            lines.append(
                f"| {ts_short} | {ex.get('symbol', 'N/A')} | {ex.get('block_reason', 'N/A')[:20]} | "
                f"{ex.get('regime', 'N/A')} | {ex.get('dir', 0)} | {ex.get('conf', 0.0):.2f} | "
                f"{ex.get('liquidity_trap_score', 0.0):.3f} | {ex.get('fakeout_risk', 0.0):.3f} | "
                f"{ex.get('overall_score', 0.0):.3f} |"
            )
        lines.append("")
    
    return "\n".join(lines)


def generate_decision_attribution_report(log_paths: Optional[List[Path]] = None) -> Dict[str, Any]:
    """
    Generate PCI decision attribution report.
    
    Args:
        log_paths: Optional list of log file paths (auto-discovers if None)
    
    Returns:
        Dict with report data and file paths
    """
    # Run analysis
    analysis = analyze_decision_attribution(log_paths)
    
    if "error" in analysis:
        return analysis
    
    # Generate reports
    output_dir = REPORTS / "pre_candle"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # JSON report
    json_path = output_dir / "pre_candle_decision_report.json"
    json_path.write_text(json.dumps(analysis, indent=2))
    
    # Markdown report
    md_path = output_dir / "pre_candle_decision_report.md"
    md_content = _generate_markdown_report(analysis)
    md_path.write_text(md_content)
    
    # CSV samples
    csv_path = output_dir / "pre_candle_decision_samples.csv"
    examples = analysis.get("top_examples", [])
    if examples:
        with csv_path.open("w", newline="") as f:
            fieldnames = [
                "ts", "symbol", "block_reason", "regime", "dir", "conf",
                "liquidity_trap_score", "fakeout_risk", "crowding_risk_score",
                "derivatives_tension", "overall_score", "high_trap", "high_fakeout", "high_overall"
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for ex in examples[:50]:
                writer.writerow({
                    "ts": ex.get("ts", ""),
                    "symbol": ex.get("symbol", ""),
                    "block_reason": ex.get("block_reason", ""),
                    "regime": ex.get("regime", ""),
                    "dir": ex.get("dir", 0),
                    "conf": ex.get("conf", 0.0),
                    "liquidity_trap_score": ex.get("liquidity_trap_score", 0.0),
                    "fakeout_risk": ex.get("fakeout_risk", 0.0),
                    "crowding_risk_score": ex.get("crowding_risk_score", 0.0),
                    "derivatives_tension": ex.get("derivatives_tension", 0.0),
                    "overall_score": ex.get("overall_score", 0.0),
                    "high_trap": ex.get("high_trap", False),
                    "high_fakeout": ex.get("high_fakeout", False),
                    "high_overall": ex.get("high_overall", False),
                })
    
    return {
        "success": True,
        "json_path": str(json_path),
        "md_path": str(md_path),
        "csv_path": str(csv_path) if examples else None,
        "summary": {
            "total_decisions": analysis.get("total_decisions", 0),
            "decisions_with_pci": analysis.get("decisions_with_pci", 0),
            "pci_presence_pct": analysis.get("pci_presence_pct", 0.0),
            "high_overall_rate": analysis.get("high_risk_rates", {}).get("high_overall", {}).get("rate_pct", 0.0),
        },
    }


if __name__ == "__main__":
    import sys
    
    log_paths = None
    if len(sys.argv) > 1:
        log_paths = [Path(p) for p in sys.argv[1:]]
    
    result = generate_decision_attribution_report(log_paths)
    
    if "error" in result:
        print(f"Error: {result['error']}")
        sys.exit(1)
    
    print("PCI Decision Attribution Report Generated")
    print("=" * 50)
    print(f"JSON: {result['json_path']}")
    print(f"Markdown: {result['md_path']}")
    if result.get("csv_path"):
        print(f"CSV: {result['csv_path']}")
    print()
    print("Summary:")
    summary = result["summary"]
    print(f"  Total decisions: {summary['total_decisions']}")
    print(f"  Decisions with PCI: {summary['decisions_with_pci']} ({summary['pci_presence_pct']:.1f}%)")
    print(f"  High overall risk rate: {summary['high_overall_rate']:.1f}%")
