#!/usr/bin/env python3
"""
Chloe Auditor - AI Risk Officer

Comprehensive health check tool that answers:
"Is Chloe currently healthy, consistent, and ready to trade with maximum profit-seeking intelligence?"

Usage:
    python3 -m tools.chloe_auditor live      # Check live/PAPER state only
    python3 -m tools.chloe_auditor backtest  # Run canonical window backtests
    python3 -m tools.chloe_auditor full      # Full health check (live + backtest)

Exit codes:
    0 = Good to trade
    1 = Trade with caution / monitor
    2 = Stop and inspect before trading
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine_alpha.core.paths import REPORTS, CONFIG
from tools.pf_doctor_filtered import _load_trades, _filter_meaningful, _compute_metrics, _compute_regime_stats
from tools.chloe_checkin import _get_core_status, _get_pf_summary, _get_filtered_pf


# Canonical test windows for backtest health checks
CANONICAL_WINDOWS = [
    {
        "id": "trend_down_mvp",
        "label": "Trend-down MVP (2022 dump slice)",
        "symbol": "ETHUSDT",
        "timeframe": "1h",
        "start": "2022-04-01T00:00:00Z",
        "end": "2022-06-30T00:00:00Z",
        "window": 200,
    },
    {
        "id": "high_vol_mvp",
        "label": "High volatility slice (2021 spring rip)",
        "symbol": "ETHUSDT",
        "timeframe": "1h",
        "start": "2021-01-01T00:00:00Z",
        "end": "2021-03-31T00:00:00Z",
        "window": 200,
    },
    {
        "id": "chop_sanity",
        "label": "Chop sanity window (sideways market)",
        "symbol": "ETHUSDT",
        "timeframe": "1h",
        "start": "2021-09-01T00:00:00Z",
        "end": "2021-10-15T00:00:00Z",
        "window": 200,
    },
]


# Health check thresholds (tuneable)
LIVE_MIN_MEANINGFUL_CLOSES = 20
LIVE_MIN_PF = 1.1
LIVE_MAX_SCRATCH_RATIO = 0.7
BACKTEST_MIN_MEANINGFUL_CLOSES = 10
BACKTEST_MIN_PF = 1.1
BACKTEST_WARN_PF = 0.9
BACKTEST_MIN_EQUITY_RATIO = 0.9  # final_equity / start_equity


def _status_icon(status: str) -> str:
    """Return traffic light icon for status."""
    if status == "ok":
        return "✅"
    elif status == "warn":
        return "⚠️"
    else:
        return "❌"


def _compute_status(checks: Dict[str, bool], issues: List[str]) -> str:
    """Compute overall status from checks and issues."""
    if any(not v for v in checks.values()):
        return "fail"
    if issues:
        return "warn"
    return "ok"


def run_live_checks() -> Dict[str, Any]:
    """
    Check current live/PAPER trading state.
    
    Returns dict with status, metrics, and issues.
    """
    print("\n" + "=" * 80)
    print("[ LIVE HEALTH ]")
    print("=" * 80)
    
    issues: List[str] = []
    checks: Dict[str, bool] = {}
    
    # Get core status
    try:
        core_status = _get_core_status()
        rec = core_status.get("rec", "N/A")
        band = core_status.get("band", "N/A")
        mult = core_status.get("mult", "N/A")
        opens = core_status.get("opens", 0)
        closes = core_status.get("closes", 0)
    except Exception as e:
        issues.append(f"Failed to load core status: {e}")
        return {
            "status": "fail",
            "issues": issues,
            "pf_overall": 0.0,
            "meaningful_closes": 0,
            "scratch_ratio": 1.0,
            "per_regime": {},
        }
    
    # Get PF summary
    try:
        pf_summary = _get_pf_summary()
        total_closes = pf_summary.get("closes", 0)
        scratch_closes = pf_summary.get("scratch_closes", 0)
        meaningful_closes = pf_summary.get("meaningful_closes", 0)
        scratch_ratio = scratch_closes / total_closes if total_closes > 0 else 0.0
    except Exception as e:
        issues.append(f"Failed to compute PF summary: {e}")
        total_closes = 0
        scratch_closes = 0
        meaningful_closes = 0
        scratch_ratio = 0.0
    
    # Get filtered PF
    try:
        filtered_pf = _get_filtered_pf(threshold=0.0005, reasons={"tp", "sl"})
        pf_overall = filtered_pf.get("pf", 0.0)
        per_regime = filtered_pf.get("per_regime", {})
    except Exception as e:
        issues.append(f"Failed to compute filtered PF: {e}")
        pf_overall = 0.0
        per_regime = {}
    
    # Compute health checks
    checks["enough_trades"] = meaningful_closes >= LIVE_MIN_MEANINGFUL_CLOSES
    checks["pf_ok"] = pf_overall >= LIVE_MIN_PF
    checks["scratch_ok"] = scratch_ratio <= LIVE_MAX_SCRATCH_RATIO
    
    # Check regime performance (only for regimes that are NOT gated off)
    # trend_down and high_vol should have good PF
    # chop and trend_up are gated off, so we don't fail on them
    bad_regimes = []
    for regime in ["trend_down", "high_vol"]:
        regime_pf = per_regime.get(regime, {}).get("pf", 0.0)
        regime_closes = per_regime.get(regime, {}).get("closes", 0)
        if regime_closes > 10 and regime_pf < 0.9:
            bad_regimes.append(f"{regime} PF={regime_pf:.2f} (closes={regime_closes})")
    
    if bad_regimes:
        issues.append(f"Poor PF in allowed regimes: {', '.join(bad_regimes)}")
    
    if not checks["enough_trades"]:
        issues.append(f"Insufficient meaningful closes: {meaningful_closes} < {LIVE_MIN_MEANINGFUL_CLOSES}")
    
    if not checks["pf_ok"]:
        issues.append(f"PF below threshold: {pf_overall:.2f} < {LIVE_MIN_PF}")
    
    if not checks["scratch_ok"]:
        issues.append(f"Scratch ratio too high: {scratch_ratio:.2f} > {LIVE_MAX_SCRATCH_RATIO}")
    
    status = _compute_status(checks, issues)
    
    # Print report
    icon = _status_icon(status)
    print(f"\n  Status: {icon} {status.upper()}")
    if meaningful_closes > 0:
        print(f"  PF: {pf_overall:.2f} ({meaningful_closes} meaningful closes)")
    else:
        print(f"  PF: N/A (no meaningful closes yet)")
    print(f"  Scratch ratio: {scratch_ratio:.2f} ({'OK' if checks['scratch_ok'] else 'HIGH'})")
    print(f"  REC: {rec} | Band: {band} | Mult: {mult}")
    print(f"  Trades: {opens} opens, {closes} closes")
    
    print(f"\n  Regime PF:")
    for regime in ["trend_down", "high_vol", "chop", "trend_up"]:
        regime_data = per_regime.get(regime, {})
        regime_pf = regime_data.get("pf", 0.0)
        regime_closes = regime_data.get("closes", 0)
        if regime_closes > 0:
            pf_label = "strong" if regime_pf >= 1.5 else ("good" if regime_pf >= 1.1 else "weak")
            gated = regime in ["chop", "trend_up"]
            gated_str = " (gated off)" if gated else ""
            print(f"    {regime:12s}: PF={regime_pf:.2f} (closes={regime_closes}) {pf_label}{gated_str}")
        else:
            print(f"    {regime:12s}: No data")
    
    if issues:
        print(f"\n  Issues:")
        for issue in issues:
            print(f"    - {issue}")
    else:
        print(f"\n  Issues: none")
    
    return {
        "status": status,
        "pf_overall": pf_overall,
        "meaningful_closes": meaningful_closes,
        "scratch_ratio": scratch_ratio,
        "per_regime": per_regime,
        "issues": issues,
        "checks": checks,
    }


def run_backtest_checks(csv_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Run canonical window backtests and analyze results.
    
    Returns dict with status, window results, and issues.
    """
    print("\n" + "=" * 80)
    print("[ BACKTEST HEALTH ]")
    print("=" * 80)
    
    if csv_path is None:
        csv_path = "data/ohlcv/ETHUSDT_1h_merged.csv"
    
    issues: List[str] = []
    window_results: List[Dict[str, Any]] = []
    
    # Import backtest harness
    try:
        from tools.backtest_harness import run_backtest
        from tools.backtest_report import load_trades
        from tools.pf_doctor_filtered import _filter_meaningful, _compute_metrics
    except ImportError as e:
        issues.append(f"Failed to import backtest tools: {e}")
        return {
            "status": "fail",
            "windows": [],
            "issues": issues,
        }
    
    print(f"\n  Running {len(CANONICAL_WINDOWS)} canonical window backtests...")
    
    for window_config in CANONICAL_WINDOWS:
        window_id = window_config["id"]
        print(f"\n  Window: {window_id} ({window_config['label']})")
        
        try:
            # Run backtest
            run_dir = run_backtest(
                symbol=window_config["symbol"],
                timeframe=window_config["timeframe"],
                start=window_config["start"],
                end=window_config["end"],
                csv_path=csv_path,
                window=window_config["window"],
            )
            
            # Load summary
            summary_path = run_dir / "summary.json"
            if not summary_path.exists():
                issues.append(f"{window_id}: summary.json not found")
                window_results.append({
                    "id": window_id,
                    "label": window_config["label"],
                    "status": "fail",
                    "issues": ["summary.json not found"],
                })
                continue
            
            summary = json.loads(summary_path.read_text())
            closes = summary.get("closes", 0)
            pf = summary.get("pf", 0.0)
            start_equity = summary.get("start_equity", 10000.0)
            final_equity = summary.get("final_equity", 10000.0)
            equity_ratio = final_equity / start_equity if start_equity > 0 else 1.0
            
            # Load trades and compute meaningful closes
            trades_path = run_dir / "trades.jsonl"
            trades = load_trades(trades_path) if trades_path.exists() else []
            all_closes = [t for t in trades if t.get("type") == "close"]
            meaningful_closes = _filter_meaningful(
                all_closes,
                threshold=0.0005,
                allowed_reasons={"tp", "sl"},
                ignore_scratch=True,
            )
            meaningful_count = len(meaningful_closes)
            
            # Compute meaningful PF
            meaningful_metrics = _compute_metrics(meaningful_closes) if meaningful_closes else {"pf": 0.0}
            meaningful_pf = meaningful_metrics.get("pf", 0.0)
            
            # Determine window status
            window_issues = []
            window_status = "ok"
            
            # Special handling for chop_sanity (entries are gated off)
            if window_id == "chop_sanity":
                if meaningful_count == 0:
                    # This is expected - chop is gated off
                    window_status = "ok"
                elif meaningful_pf < BACKTEST_MIN_PF:
                    window_issues.append(f"PF={meaningful_pf:.2f} (but entries gated off, so OK)")
                    window_status = "ok"
            else:
                # Normal windows (trend_down, high_vol)
                if meaningful_count < BACKTEST_MIN_MEANINGFUL_CLOSES:
                    window_issues.append(f"Too few meaningful closes: {meaningful_count} < {BACKTEST_MIN_MEANINGFUL_CLOSES}")
                    window_status = "warn" if meaningful_count > 0 else "fail"
                
                if meaningful_pf < BACKTEST_WARN_PF:
                    window_issues.append(f"PF too low: {meaningful_pf:.2f} < {BACKTEST_WARN_PF}")
                    window_status = "fail"
                elif meaningful_pf < BACKTEST_MIN_PF:
                    window_issues.append(f"PF borderline: {meaningful_pf:.2f} < {BACKTEST_MIN_PF}")
                    window_status = "warn"
            
            if equity_ratio < BACKTEST_MIN_EQUITY_RATIO:
                window_issues.append(f"Equity bleed: {equity_ratio:.2f} < {BACKTEST_MIN_EQUITY_RATIO}")
                window_status = "fail"
            
            window_results.append({
                "id": window_id,
                "label": window_config["label"],
                "closes": closes,
                "meaningful": meaningful_count,
                "pf": meaningful_pf,
                "final_equity": final_equity,
                "start_equity": start_equity,
                "equity_ratio": equity_ratio,
                "status": window_status,
                "issues": window_issues,
                "run_dir": str(run_dir),
            })
            
            # Print window result
            icon = _status_icon(window_status)
            print(f"    {icon} Closes: {closes} (meaningful: {meaningful_count})")
            print(f"       PF: {meaningful_pf:.2f}")
            print(f"       Equity: ${start_equity:,.2f} → ${final_equity:,.2f} ({equity_ratio:.2f}x)")
            if window_issues:
                print(f"       Issues: {', '.join(window_issues)}")
        
        except Exception as e:
            issues.append(f"{window_id}: {e}")
            window_results.append({
                "id": window_id,
                "label": window_config["label"],
                "status": "fail",
                "issues": [str(e)],
            })
    
    # Compute overall backtest status
    window_statuses = [w.get("status", "fail") for w in window_results]
    if "fail" in window_statuses:
        overall_status = "fail"
    elif "warn" in window_statuses:
        overall_status = "warn"
    else:
        overall_status = "ok"
    
    # Aggregate issues
    all_window_issues = []
    for w in window_results:
        if w.get("issues"):
            all_window_issues.extend([f"{w['id']}: {issue}" for issue in w["issues"]])
    
    issues.extend(all_window_issues)
    
    print(f"\n  Overall: {_status_icon(overall_status)} {overall_status.upper()}")
    
    return {
        "status": overall_status,
        "windows": window_results,
        "issues": issues,
    }


def run_full_checks(csv_path: Optional[str] = None) -> int:
    """
    Run both live and backtest checks, plus optional threshold analysis.
    
    Returns exit code: 0=good, 1=warn, 2=fail
    """
    print("=" * 80)
    print("CHLOE AUDITOR - FULL HEALTH CHECK")
    print("=" * 80)
    
    # Run live checks
    live_result = run_live_checks()
    
    # Run backtest checks
    backtest_result = run_backtest_checks(csv_path=csv_path)
    
    # Optional: Check signal return analysis if available
    analysis_path = REPORTS / "analysis" / "conf_ret_summary.json"
    if analysis_path.exists():
        print("\n" + "=" * 80)
        print("[ SIGNAL ANALYSIS SUMMARY ]")
        print("=" * 80)
        try:
            analysis = json.loads(analysis_path.read_text())
            bins = analysis.get("bins", [])
            
            # Group by regime and find best confidence ranges
            regime_bins: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for bin_data in bins:
                regime = bin_data.get("regime", "unknown")
                regime_bins[regime].append(bin_data)
            
            print(f"\n  Best confidence ranges by regime:")
            for regime in ["trend_down", "high_vol", "chop", "trend_up"]:
                regime_bin_list = regime_bins.get(regime, [])
                if not regime_bin_list:
                    continue
                
                # Sort by PF
                sorted_bins = sorted(regime_bin_list, key=lambda b: b.get("pf", 0.0), reverse=True)
                top_bin = sorted_bins[0] if sorted_bins else None
                
                if top_bin and top_bin.get("count", 0) >= 20:
                    conf_min = top_bin.get("conf_min", 0.0)
                    conf_max = top_bin.get("conf_max", 1.0)
                    pf = top_bin.get("pf", 0.0)
                    count = top_bin.get("count", 0)
                    print(f"    {regime:12s}: conf ∈ [{conf_min:.2f}, {conf_max:.2f}) → PF={pf:.2f} (n={count})")
        except Exception as e:
            print(f"  ⚠️  Failed to load analysis summary: {e}")
    
    # Compute final status
    live_status = live_result.get("status", "fail")
    backtest_status = backtest_result.get("status", "fail")
    
    # Aggregate all issues
    all_issues = []
    all_issues.extend(live_result.get("issues", []))
    all_issues.extend(backtest_result.get("issues", []))
    
    # Determine exit code
    if live_status == "fail" or backtest_status == "fail":
        exit_code = 2
    elif live_status == "warn" or backtest_status == "warn":
        exit_code = 1
    else:
        exit_code = 0
    
    # Print final summary
    print("\n" + "=" * 80)
    print("CHLOE AUDITOR SUMMARY")
    print("=" * 80)
    print(f"\nLIVE:     {_status_icon(live_status)} {live_status.upper()}")
    print(f"BACKTEST: {_status_icon(backtest_status)} {backtest_status.upper()}")
    
    if all_issues:
        print(f"\nIssues:")
        for issue in all_issues[:10]:  # Limit to first 10
            print(f"  - {issue}")
        if len(all_issues) > 10:
            print(f"  ... and {len(all_issues) - 10} more issues")
    else:
        print(f"\nIssues: none")
    
    # Recommendations
    recommendations = []
    
    if live_status == "fail":
        recommendations.append("⚠️  Do NOT trade live until issues are resolved")
    elif live_status == "warn":
        recommendations.append("⚠️  Trade with caution and monitor closely")
    
    if backtest_status == "fail":
        recommendations.append("⚠️  Backtest failures detected - investigate before trading")
    elif backtest_status == "warn":
        recommendations.append("⚠️  Some backtest windows show borderline performance")
    
    if live_result.get("meaningful_closes", 0) < LIVE_MIN_MEANINGFUL_CLOSES:
        recommendations.append(f"📊 Collect more live trades (need {LIVE_MIN_MEANINGFUL_CLOSES}, have {live_result.get('meaningful_closes', 0)})")
    
    if recommendations:
        print(f"\nRecommendation:")
        for rec in recommendations:
            print(f"  {rec}")
    else:
        print(f"\nRecommendation: ✅ Chloe is ready to trade")
    
    print(f"\nExit code: {exit_code}")
    
    return exit_code


def main():
    parser = argparse.ArgumentParser(description="Chloe Auditor - AI Risk Officer")
    subparsers = parser.add_subparsers(dest="command", help="Subcommand to run")
    
    # Live subcommand
    live_parser = subparsers.add_parser("live", help="Check live/PAPER state only")
    
    # Backtest subcommand
    backtest_parser = subparsers.add_parser("backtest", help="Run canonical window backtests")
    backtest_parser.add_argument("--csv", help="Path to CSV file (default: data/ohlcv/ETHUSDT_1h_merged.csv)")
    
    # Full subcommand
    full_parser = subparsers.add_parser("full", help="Full health check (live + backtest)")
    full_parser.add_argument("--csv", help="Path to CSV file (default: data/ohlcv/ETHUSDT_1h_merged.csv)")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    if args.command == "live":
        result = run_live_checks()
        exit_code = 0 if result.get("status") == "ok" else (1 if result.get("status") == "warn" else 2)
        return exit_code
    
    elif args.command == "backtest":
        result = run_backtest_checks(csv_path=args.csv)
        exit_code = 0 if result.get("status") == "ok" else (1 if result.get("status") == "warn" else 2)
        return exit_code
    
    elif args.command == "full":
        exit_code = run_full_checks(csv_path=args.csv)
        return exit_code
    
    return 1


if __name__ == "__main__":
    sys.exit(main())

