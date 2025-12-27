#!/usr/bin/env python3
"""
Chloe Check-in Tool - Unified status and performance summary.

Provides a single command to view:
- Core status (REC, risk band, opens/closes)
- PF summary (all closes, meaningful only)
- Filtered PF (TP/SL, by regime)
- Last 5 meaningful trades
- Optional GPT reflection

This is a read-only diagnostic tool; it does not modify trading behavior.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from engine_alpha.core.paths import REPORTS

# Import utilities from existing tools
from tools.pf_doctor import _load_trades, _summarize
from tools.pf_doctor_filtered import _filter_meaningful, _compute_metrics, _compute_regime_stats, _format_pf
from tools.status import _load_json, _format_ts


def _get_mode() -> str:
    """Get current MODE from environment."""
    return os.getenv("MODE", "PAPER").upper()


def _get_core_status() -> Dict[str, Any]:
    """Get core status similar to tools.status."""
    orch = _load_json(REPORTS / "orchestrator_snapshot.json")
    risk = _load_json(REPORTS / "risk_adapter.json")
    live_state = _load_json(REPORTS / "live_loop_state.json")
    
    policy = orch.get("policy", {}) if isinstance(orch, dict) else {}
    inputs = orch.get("inputs", {}) if isinstance(orch, dict) else {}
    
    rec = orch.get("recommendation") or inputs.get("rec") or "N/A"
    allow_opens = policy.get("allow_opens")
    allow_pa = policy.get("allow_pa")
    
    band = risk.get("band", "N/A")
    mult = risk.get("mult", "N/A")
    drawdown = risk.get("drawdown") or risk.get("dd") or risk.get("max_drawdown")
    
    live_ts = live_state.get("ts") if isinstance(live_state, dict) else None
    
    # Count opens/closes
    trades_path = REPORTS / "trades.jsonl"
    trades = _load_trades(trades_path)
    open_count = sum(1 for t in trades if str(t.get("type") or t.get("event") or "").lower() == "open")
    close_count = sum(1 for t in trades if str(t.get("type") or t.get("event") or "").lower() == "close")
    
    return {
        "rec": rec,
        "allow_opens": allow_opens,
        "allow_pa": allow_pa,
        "band": band,
        "mult": mult,
        "drawdown": drawdown,
        "live_ts": live_ts,
        "opens": open_count,
        "closes": close_count,
    }


def _get_pf_summary() -> Dict[str, Any]:
    """Get PF summary from pf_doctor logic."""
    trades_path = REPORTS / "trades.jsonl"
    trades = _load_trades(trades_path)
    summary = _summarize(trades, include_scratch=False)
    return summary


def _get_filtered_pf(threshold: float = 0.0005, reasons: Optional[Set[str]] = None) -> Dict[str, Any]:
    """Get filtered PF using pf_doctor_filtered logic."""
    trades_path = REPORTS / "trades.jsonl"
    trades = _load_trades(trades_path)
    
    meaningful = _filter_meaningful(
        trades,
        threshold=threshold,
        allowed_reasons=reasons,
        ignore_scratch=True,
    )
    
    overall_metrics = _compute_metrics(meaningful)
    regime_stats = _compute_regime_stats(meaningful)
    
    return {
        "count": len(meaningful),
        "overall": overall_metrics,
        "by_regime": regime_stats,
    }


def _get_last_meaningful_trades(count: int = 5, threshold: float = 0.0005, reasons: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
    """Get last N meaningful trades."""
    trades_path = REPORTS / "trades.jsonl"
    trades = _load_trades(trades_path)
    
    meaningful = _filter_meaningful(
        trades,
        threshold=threshold,
        allowed_reasons=reasons,
        ignore_scratch=True,
    )
    
    return meaningful[-count:] if len(meaningful) > count else meaningful


def _format_trade_summary(trade: Dict[str, Any]) -> str:
    """Format a single trade for display."""
    ts = trade.get("ts", "N/A")
    pct = trade.get("pct", 0.0)
    exit_reason = trade.get("exit_reason", "unknown")
    exit_label = trade.get("exit_label", exit_reason)
    regime = trade.get("regime", "unknown")
    risk_band = trade.get("risk_band", "N/A")
    risk_mult = trade.get("risk_mult", "N/A")
    
    # Format pct with sign
    pct_str = f"{pct:+.6f}" if pct != 0.0 else "0.000000"
    
    # Format exit reason
    exit_str = f"{exit_reason}({exit_label})" if exit_label != exit_reason else exit_reason
    
    return f"  {ts}  pct={pct_str}  exit={exit_str}  regime={regime}  band={risk_band} mult={risk_mult}"


def _get_gpt_reflection() -> Optional[Dict[str, Any]]:
    """Get GPT reflection if available."""
    try:
        from tools.run_reflection_gpt import build_reflection_input, call_gpt_api
        from engine_alpha.reflect.gpt_reflection_template import build_example_prompt_bundle
        
        # Build reflection input
        reflection_input = build_reflection_input()
        
        # Build prompts
        bundle = build_example_prompt_bundle(reflection_input)
        system_prompt = bundle["system"]
        user_prompt = bundle["user"]
        
        # Try to call GPT API
        try:
            gpt_response = call_gpt_api(system_prompt, user_prompt)
            return {
                "success": True,
                "reflection_input": reflection_input,
                "gpt_response": gpt_response,
            }
        except Exception as e:
            # If GPT fails, return None (will be handled gracefully)
            return None
    except ImportError:
        return None
    except Exception:
        return None


def _print_header(mode: str):
    """Print check-in header."""
    now = datetime.now(timezone.utc)
    ts_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    print("=" * 70)
    print(f"Chloe Check-in — {ts_str} (MODE={mode})")
    print("=" * 70)
    print()


def _print_core_status(status: Dict[str, Any]):
    """Print core status section."""
    print("[CORE STATUS]")
    rec = status["rec"]
    opens = status["allow_opens"]
    pa = status["allow_pa"]
    band = status["band"]
    mult = status["mult"]
    dd = status["drawdown"] if status["drawdown"] is not None else "N/A"
    open_count = status["opens"]
    close_count = status["closes"]
    
    print(f"  REC={rec} opens={opens} pa={pa} | Risk band={band} mult={mult} dd={dd}")
    print(f"  Trades (open/close): {open_count} / {close_count}")
    print()


def _print_pf_summary(pf_summary: Dict[str, Any]):
    """Print PF summary section."""
    print("[PF SUMMARY — ALL CLOSES]")
    scratch = pf_summary["scratch"]
    meaningful = pf_summary["meaningful_closes"]
    sum_pos = pf_summary["sum_pos"]
    sum_neg = pf_summary["sum_neg"]
    pf = pf_summary["pf"]
    
    if scratch > 0:
        print(f"  Scratch closes (excluded): {scratch}")
    print(f"  Meaningful closes:         {meaningful}")
    print(f"  Positive pct sum:          {sum_pos:+.6f}")
    print(f"  Negative pct sum:          {sum_neg:+.6f}")
    
    if math.isinf(pf):
        print(f"  PF (meaningful only):      infinity (no losses)")
    else:
        print(f"  PF (meaningful only):      {pf:.6f}")
    print()


def _print_filtered_pf(filtered: Dict[str, Any]):
    """Print filtered PF section."""
    print("[FILTERED PF — TP/SL, |pct| >= 0.0005]")
    
    count = filtered["count"]
    overall = filtered["overall"]
    by_regime = filtered["by_regime"]
    
    wins = overall["wins"]
    losses = overall["losses"]
    pf_str = _format_pf(overall["pf"])
    
    print(f"  Overall: count={count} wins={wins} losses={losses} PF={pf_str}")
    
    if by_regime:
        print("  By regime:")
        # Sort regimes for consistent output
        sorted_regimes = sorted(by_regime.keys())
        for regime in sorted_regimes:
            stats = by_regime[regime]
            regime_padded = f"{regime:10s}"
            pf_str_regime = _format_pf(stats["pf"])
            print(
                f"    {regime_padded}: closes={stats['closes']:3d} "
                f"wins={stats['wins']:2d} losses={stats['losses']:2d} PF={pf_str_regime:>6s}"
            )
    print()


def _print_last_trades(trades: List[Dict[str, Any]]):
    """Print last meaningful trades section."""
    print(f"[LAST {len(trades)} MEANINGFUL TRADES]")
    if not trades:
        print("  (no meaningful trades found)")
    else:
        for trade in trades:
            print(_format_trade_summary(trade))
    print()


def _print_gpt_reflection(reflection: Dict[str, Any]):
    """Print GPT reflection section."""
    print("[GPT REFLECTION — FILTERED PF]")
    
    reflection_input = reflection.get("reflection_input", {})
    gpt_response = reflection.get("gpt_response")
    
    # Show filtered_pf summary
    filtered_pf = reflection_input.get("filtered_pf", {})
    if filtered_pf:
        overall = filtered_pf.get("overall", {})
        by_regime = filtered_pf.get("by_regime", {})
        
        pf_str = _format_pf(overall.get("pf", 0.0))
        count = overall.get("count", 0)
        wins = overall.get("wins", 0)
        losses = overall.get("losses", 0)
        
        print(f"filtered_pf.overall: PF={pf_str} (count={count}, wins={wins}, losses={losses})")
        
        if by_regime:
            print("filtered_pf.by_regime:")
            sorted_regimes = sorted(by_regime.keys())
            for regime in sorted_regimes:
                stats = by_regime[regime]
                pf_str_regime = _format_pf(stats.get("pf", 0.0))
                closes = stats.get("closes", 0)
                print(f"  {regime:10s} PF={pf_str_regime:>6s} over {closes} trades")
    
    # Show GPT summary if available
    if gpt_response:
        print()
        print("GPT summary:")
        # Extract a short summary from GPT response
        if isinstance(gpt_response, str):
            # Try to extract first few sentences
            lines = gpt_response.split("\n")
            for line in lines[:5]:  # Show first 5 lines
                if line.strip():
                    print(f"  {line}")
        elif isinstance(gpt_response, dict):
            # If it's structured, try to extract summary
            summary = gpt_response.get("summary") or gpt_response.get("analysis") or str(gpt_response)
            print(f"  {summary}")
    else:
        print("  (GPT response not available)")
    
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Chloe Check-in - Unified status and performance summary"
    )
    parser.add_argument(
        "--reflect",
        action="store_true",
        help="Include GPT reflection (requires OpenAI API key)",
    )
    args = parser.parse_args()
    
    mode = _get_mode()
    
    # Print header
    _print_header(mode)
    
    # Get and print core status
    status = _get_core_status()
    _print_core_status(status)
    
    # Get and print PF summary
    pf_summary = _get_pf_summary()
    _print_pf_summary(pf_summary)
    
    # Get and print filtered PF
    filtered = _get_filtered_pf(threshold=0.0005, reasons={"tp", "sl"})
    _print_filtered_pf(filtered)
    
    # Get and print last meaningful trades
    last_trades = _get_last_meaningful_trades(count=5, threshold=0.0005, reasons={"tp", "sl"})
    _print_last_trades(last_trades)
    
    # Optional GPT reflection
    if args.reflect:
        reflection = _get_gpt_reflection()
        if reflection:
            _print_gpt_reflection(reflection)
        else:
            print("[GPT REFLECTION]")
            print("  (GPT reflection not available - check OpenAI API key and openai library)")
            print()
    
    print("=" * 70)
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

