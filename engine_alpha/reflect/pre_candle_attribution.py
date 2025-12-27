"""
Pre-Candle Intelligence (PCI) - Attribution Report Module
Phase 3: Analysis-only report on "would-have-blocked" losses

Reads trade logs and PCI signal data to compute:
- Which losing trades would PCI have blocked?
- False positive rate (high-risk that preceded winners)
- Threshold sweep analysis
- Segment analysis by regime/volatility
"""

from __future__ import annotations

import json
import csv
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timezone
from collections import defaultdict

from engine_alpha.core.paths import REPORTS, CONFIG


# Default thresholds from config
DEFAULT_TRAP_BLOCK = 0.70
DEFAULT_FAKEOUT_BLOCK = 0.65
DEFAULT_CROWDING_TIGHTEN = 0.70

# Threshold sweep range
THRESHOLD_SWEEP = [0.55, 0.60, 0.65, 0.70, 0.75, 0.80]


def _load_pci_config() -> Dict[str, Any]:
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


def _find_trade_logs() -> List[Path]:
    """Auto-discover trade log files."""
    candidates = [
        REPORTS / "trades.jsonl",
        REPORTS / "trade_log.jsonl",
        REPORTS / "loop" / "recovery_lane_v2_trades.jsonl",
    ]
    found = []
    for path in candidates:
        if path.exists():
            found.append(path)
    return found


def _load_trades(trades_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Load trades from jsonl file."""
    if trades_path is None:
        candidates = _find_trade_logs()
        if not candidates:
            return []
        trades_path = candidates[0]  # Use first found
    
    trades = []
    if not trades_path.exists():
        return trades
    
    try:
        for line in trades_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                trade = json.loads(line)
                trades.append(trade)
            except Exception:
                continue
    except Exception:
        pass
    
    return trades


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
        # Try ISO format
        try:
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            pass
        
        # Try other formats
        for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]:
            try:
                return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
            except Exception:
                continue
    
    return None


def _extract_completed_trades(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract completed trades (have both open and close)."""
    # Group by symbol and track open/close pairs
    positions: Dict[str, Dict[str, Any]] = {}
    completed: List[Dict[str, Any]] = []
    
    for trade in trades:
        symbol = trade.get("symbol", "ETHUSDT")
        trade_type = str(trade.get("type", trade.get("event", ""))).lower()
        ts = _parse_timestamp(trade.get("ts"))
        
        if trade_type == "open":
            positions[symbol] = {
                "symbol": symbol,
                "entry_time": ts,
                "entry_ts": trade.get("ts"),
                "dir": trade.get("dir", 0),
                "conf": trade.get("conf", 0.0),
                "pci": trade.get("pre_candle"),  # PCI snapshot from Phase 3.1 (scores + optional features)
            }
        elif trade_type == "close" and symbol in positions:
            entry = positions[symbol]
            pnl = float(trade.get("pct", 0.0))
            exit_time = ts
            exit_ts = trade.get("ts")
            
            completed_trade = {
                "symbol": symbol,
                "entry_time": entry["entry_time"],
                "entry_ts": entry["entry_ts"],
                "exit_time": exit_time,
                "exit_ts": exit_ts,
                "dir": entry["dir"],
                "conf": entry.get("conf", 0.0),
                "pnl": pnl,
                "is_win": pnl > 0.0,
                "is_loss": pnl < 0.0,
                "pci_at_entry": entry.get("pci"),  # PCI snapshot at entry
                "pci_at_exit": trade.get("pre_candle"),  # PCI snapshot at exit (if logged)
            }
            completed.append(completed_trade)
            del positions[symbol]
    
    return completed


def _would_have_blocked(
    pci_scores: Optional[Dict[str, float]],
    trap_threshold: float,
    fakeout_threshold: float
) -> Tuple[bool, str]:
    """
    Determine if PCI would have blocked this trade.
    
    Returns:
        (blocked: bool, reason: str)
    """
    if not pci_scores:
        return (False, "no_pci_data")
    
    liquidity_trap = pci_scores.get("liquidity_trap_score", 0.0)
    fakeout_risk = pci_scores.get("fakeout_risk", 0.0)
    
    if liquidity_trap >= trap_threshold:
        return (True, f"liquidity_trap_{liquidity_trap:.3f}")
    
    if fakeout_risk >= fakeout_threshold:
        return (True, f"fakeout_risk_{fakeout_risk:.3f}")
    
    return (False, "below_threshold")


def _compute_attribution_metrics(
    completed_trades: List[Dict[str, Any]],
    trap_threshold: float,
    fakeout_threshold: float
) -> Dict[str, Any]:
    """Compute attribution metrics for given thresholds."""
    blocked_losses = []
    blocked_wins = []
    total_losses = []
    total_wins = []
    
    for trade in completed_trades:
        pci = trade.get("pci_at_entry")
        if not pci:
            # No PCI data - skip attribution but count in totals
            if trade["is_loss"]:
                total_losses.append(trade)
            elif trade["is_win"]:
                total_wins.append(trade)
            continue
        
        scores = pci.get("scores", {}) if isinstance(pci, dict) else {}
        blocked, reason = _would_have_blocked(scores, trap_threshold, fakeout_threshold)
        
        if blocked:
            if trade["is_loss"]:
                blocked_losses.append({**trade, "block_reason": reason})
            elif trade["is_win"]:
                blocked_wins.append({**trade, "block_reason": reason})
        
        # Count in totals
        if trade["is_loss"]:
            total_losses.append(trade)
        elif trade["is_win"]:
            total_wins.append(trade)
    
    # Compute metrics
    losses_blocked_count = len(blocked_losses)
    wins_blocked_count = len(blocked_wins)
    gross_loss_avoided = -sum(t["pnl"] for t in blocked_losses)  # Losses are negative
    gross_profit_missed = sum(t["pnl"] for t in blocked_wins)
    net_benefit = gross_loss_avoided - gross_profit_missed
    
    total_loss_count = len(total_losses)
    total_loss_amount = -sum(t["pnl"] for t in total_losses)
    
    block_precision = 0.0
    if losses_blocked_count + wins_blocked_count > 0:
        block_precision = losses_blocked_count / (losses_blocked_count + wins_blocked_count)
    
    loss_coverage_pct = 0.0
    if total_loss_amount > 0:
        loss_coverage_pct = (gross_loss_avoided / total_loss_amount) * 100.0
    
    return {
        "trap_threshold": trap_threshold,
        "fakeout_threshold": fakeout_threshold,
        "blocked_losses_count": losses_blocked_count,
        "blocked_wins_count": wins_blocked_count,
        "gross_loss_avoided": gross_loss_avoided,
        "gross_profit_missed": gross_profit_missed,
        "net_benefit": net_benefit,
        "block_precision": block_precision,
        "total_loss_count": total_loss_count,
        "total_loss_amount": total_loss_amount,
        "loss_coverage_pct": loss_coverage_pct,
        "blocked_losses": blocked_losses[:50],  # Top 50 examples
        "blocked_wins": blocked_wins[:50],  # Top 50 false positives
    }


def _threshold_sweep(completed_trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sweep thresholds and compute metrics for each combination."""
    results = []
    
    for trap_thresh in THRESHOLD_SWEEP:
        for fakeout_thresh in THRESHOLD_SWEEP:
            metrics = _compute_attribution_metrics(completed_trades, trap_thresh, fakeout_thresh)
            results.append(metrics)
    
    return results


def _find_best_thresholds(sweep_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Find best threshold combinations by net_benefit and precision."""
    if not sweep_results:
        return {}
    
    # Best by net benefit
    best_net = max(sweep_results, key=lambda x: x.get("net_benefit", -1e9))
    
    # Best by precision (with minimum sample size)
    precision_candidates = [r for r in sweep_results if (r.get("blocked_losses_count", 0) + r.get("blocked_wins_count", 0)) >= 5]
    best_precision = max(precision_candidates, key=lambda x: x.get("block_precision", 0.0)) if precision_candidates else best_net
    
    # Best balanced (net benefit * precision)
    for r in sweep_results:
        r["balanced_score"] = r.get("net_benefit", 0.0) * r.get("block_precision", 0.0)
    best_balanced = max(sweep_results, key=lambda x: x.get("balanced_score", -1e9))
    
    return {
        "by_net_benefit": best_net,
        "by_precision": best_precision,
        "by_balanced": best_balanced,
    }


def _generate_markdown_report(
    default_metrics: Dict[str, Any],
    sweep_results: List[Dict[str, Any]],
    best_thresholds: Dict[str, Any],
    trades_path: Optional[Path]
) -> str:
    """Generate markdown report."""
    lines = []
    lines.append("# Pre-Candle Intelligence (PCI) Attribution Report")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now(timezone.utc).isoformat()}")
    if trades_path:
        lines.append(f"**Trade Log:** {trades_path}")
    lines.append("")
    
    # Default thresholds summary
    lines.append("## Default Thresholds Summary")
    lines.append("")
    lines.append(f"- **Trap Block:** {default_metrics.get('trap_threshold', 0.0):.2f}")
    lines.append(f"- **Fakeout Block:** {default_metrics.get('fakeout_threshold', 0.0):.2f}")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Blocked Losses | {default_metrics.get('blocked_losses_count', 0)} |")
    lines.append(f"| Blocked Wins (False Positives) | {default_metrics.get('blocked_wins_count', 0)} |")
    lines.append(f"| Gross Loss Avoided | {default_metrics.get('gross_loss_avoided', 0.0):.4f} |")
    lines.append(f"| Gross Profit Missed | {default_metrics.get('gross_profit_missed', 0.0):.4f} |")
    lines.append(f"| Net Benefit | {default_metrics.get('net_benefit', 0.0):.4f} |")
    lines.append(f"| Block Precision | {default_metrics.get('block_precision', 0.0):.2%} |")
    lines.append(f"| Loss Coverage | {default_metrics.get('loss_coverage_pct', 0.0):.2f}% |")
    lines.append("")
    
    # Best thresholds
    if best_thresholds:
        lines.append("## Best Threshold Combinations")
        lines.append("")
        
        if "by_net_benefit" in best_thresholds:
            best = best_thresholds["by_net_benefit"]
            lines.append("### By Net Benefit")
            lines.append(f"- Trap: {best.get('trap_threshold', 0.0):.2f}, Fakeout: {best.get('fakeout_threshold', 0.0):.2f}")
            lines.append(f"- Net Benefit: {best.get('net_benefit', 0.0):.4f}")
            lines.append(f"- Precision: {best.get('block_precision', 0.0):.2%}")
            lines.append("")
        
        if "by_precision" in best_thresholds:
            best = best_thresholds["by_precision"]
            lines.append("### By Precision")
            lines.append(f"- Trap: {best.get('trap_threshold', 0.0):.2f}, Fakeout: {best.get('fakeout_threshold', 0.0):.2f}")
            lines.append(f"- Precision: {best.get('block_precision', 0.0):.2%}")
            lines.append(f"- Net Benefit: {best.get('net_benefit', 0.0):.4f}")
            lines.append("")
        
        if "by_balanced" in best_thresholds:
            best = best_thresholds["by_balanced"]
            lines.append("### By Balanced Score")
            lines.append(f"- Trap: {best.get('trap_threshold', 0.0):.2f}, Fakeout: {best.get('fakeout_threshold', 0.0):.2f}")
            lines.append(f"- Balanced Score: {best.get('balanced_score', 0.0):.4f}")
            lines.append("")
    
    # Top examples
    blocked_losses = default_metrics.get("blocked_losses", [])
    if blocked_losses:
        lines.append("## Top Would-Have-Blocked Losses")
        lines.append("")
        lines.append("| Symbol | Entry Time | PnL | Trap Score | Fakeout Score | Reason |")
        lines.append("|--------|------------|-----|------------|---------------|--------|")
        for trade in blocked_losses[:10]:
            pci = trade.get("pci_at_entry", {})
            scores = pci.get("scores", {}) if isinstance(pci, dict) else {}
            lines.append(
                f"| {trade.get('symbol', 'N/A')} | {trade.get('entry_ts', 'N/A')} | "
                f"{trade.get('pnl', 0.0):.4f} | {scores.get('liquidity_trap_score', 0.0):.3f} | "
                f"{scores.get('fakeout_risk', 0.0):.3f} | {trade.get('block_reason', 'N/A')} |"
            )
        lines.append("")
    
    blocked_wins = default_metrics.get("blocked_wins", [])
    if blocked_wins:
        lines.append("## Top False Positives (Blocked Wins)")
        lines.append("")
        lines.append("| Symbol | Entry Time | PnL | Trap Score | Fakeout Score | Reason |")
        lines.append("|--------|------------|-----|------------|---------------|--------|")
        for trade in blocked_wins[:10]:
            pci = trade.get("pci_at_entry", {})
            scores = pci.get("scores", {}) if isinstance(pci, dict) else {}
            lines.append(
                f"| {trade.get('symbol', 'N/A')} | {trade.get('entry_ts', 'N/A')} | "
                f"{trade.get('pnl', 0.0):.4f} | {scores.get('liquidity_trap_score', 0.0):.3f} | "
                f"{scores.get('fakeout_risk', 0.0):.3f} | {trade.get('block_reason', 'N/A')} |"
            )
        lines.append("")
    
    return "\n".join(lines)


def generate_attribution_report(trades_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Generate PCI attribution report.
    
    Args:
        trades_path: Optional path to trades.jsonl (auto-discovers if None)
    
    Returns:
        Dict with report data and file paths
    """
    # Load config
    config = _load_pci_config()
    trap_threshold = config["trap_block"]
    fakeout_threshold = config["fakeout_block"]
    
    # Load trades
    trades = _load_trades(trades_path)
    if not trades:
        trades_path_str = str(trades_path) if trades_path else "auto-discovery failed"
        print(f"PRE_CANDLE_SKIP reason=no_trades_found trades_path={trades_path_str}")
        return {
            "error": "No trades found",
            "trades_path": trades_path_str,
        }

    # Extract completed trades
    completed_trades = _extract_completed_trades(trades)

    if not completed_trades:
        print(f"PRE_CANDLE_SKIP reason=no_completed_trades total_trades={len(trades)}")
        return {
            "error": "No completed trades found",
            "total_trades": len(trades),
        }
    
    # Compute default metrics
    default_metrics = _compute_attribution_metrics(completed_trades, trap_threshold, fakeout_threshold)
    
    # Threshold sweep
    sweep_results = _threshold_sweep(completed_trades)
    best_thresholds = _find_best_thresholds(sweep_results)
    
    # Generate reports
    output_dir = REPORTS / "pre_candle"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # JSON report
    json_path = output_dir / "pre_candle_attribution.json"
    json_data = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "trades_path": str(trades_path) if trades_path else "auto-discovered",
        "total_trades": len(trades),
        "completed_trades": len(completed_trades),
        "default_metrics": default_metrics,
        "threshold_sweep": sweep_results,
        "best_thresholds": best_thresholds,
    }
    json_path.write_text(json.dumps(json_data, indent=2))
    
    # Markdown report
    md_path = output_dir / "pre_candle_attribution.md"
    md_content = _generate_markdown_report(default_metrics, sweep_results, best_thresholds, trades_path)
    md_path.write_text(md_content)
    
    # CSV samples (optional)
    csv_path = output_dir / "pre_candle_samples.csv"
    blocked_losses = default_metrics.get("blocked_losses", [])
    if blocked_losses:
        with csv_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["symbol", "entry_ts", "exit_ts", "pnl", "trap_score", "fakeout_score", "reason"])
            writer.writeheader()
            for trade in blocked_losses[:50]:
                pci = trade.get("pci_at_entry", {})
                scores = pci.get("scores", {}) if isinstance(pci, dict) else {}
                writer.writerow({
                    "symbol": trade.get("symbol", ""),
                    "entry_ts": trade.get("entry_ts", ""),
                    "exit_ts": trade.get("exit_ts", ""),
                    "pnl": trade.get("pnl", 0.0),
                    "trap_score": scores.get("liquidity_trap_score", 0.0),
                    "fakeout_score": scores.get("fakeout_risk", 0.0),
                    "reason": trade.get("block_reason", ""),
                })
    
    print(f"PRE_CANDLE_SUCCESS completed_trades={len(completed_trades)} blocked_losses={default_metrics.get('blocked_losses_count', 0)} net_benefit={default_metrics.get('net_benefit', 0.0):.4f}")
    return {
        "success": True,
        "json_path": str(json_path),
        "md_path": str(md_path),
        "csv_path": str(csv_path) if blocked_losses else None,
        "summary": {
            "total_trades": len(trades),
            "completed_trades": len(completed_trades),
            "blocked_losses": default_metrics.get("blocked_losses_count", 0),
            "blocked_wins": default_metrics.get("blocked_wins_count", 0),
            "net_benefit": default_metrics.get("net_benefit", 0.0),
        },
    }


if __name__ == "__main__":
    import sys
    
    trades_path = None
    if len(sys.argv) > 1:
        trades_path = Path(sys.argv[1])
    
    result = generate_attribution_report(trades_path)
    
    if "error" in result:
        print(f"Error: {result['error']}")
        sys.exit(1)
    
    print("PCI Attribution Report Generated")
    print("=" * 50)
    print(f"JSON: {result['json_path']}")
    print(f"Markdown: {result['md_path']}")
    if result.get("csv_path"):
        print(f"CSV: {result['csv_path']}")
    print()
    print("Summary:")
    summary = result["summary"]
    print(f"  Total trades: {summary['total_trades']}")
    print(f"  Completed trades: {summary['completed_trades']}")
    print(f"  Blocked losses: {summary['blocked_losses']}")
    print(f"  Blocked wins (false positives): {summary['blocked_wins']}")
    print(f"  Net benefit: {summary['net_benefit']:.4f}")
