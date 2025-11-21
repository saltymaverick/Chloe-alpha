#!/usr/bin/env python3
"""
Burst Trade Analyzer - One-off micro-reflection tool
Analyzes a specific burst of trades (e.g., 13 trades) without affecting live trading.

PURPOSE:
--------
This tool performs a micro-reflection on a specific burst of trades to understand:
- Which buckets fired in the burst
- Exit reason distribution and exit_conf curve
- Market regime confirmation (was it actually chop?)
- Timing resolution (did all trades occur in one bar?)
- Bias detection (repeated entries, false signal clusters)
- Micro-performance evaluation (PF of the burst)

SAFETY:
-------
- This is READ-ONLY. No changes to live trading.
- Does not touch thresholds, risk adapter, or nightly reflection.
- Just a one-off analysis snapshot.

USAGE:
------
    python3 -m tools.analyze_burst --num-trades 13
    python3 -m tools.analyze_burst --num-trades 13 --gpt
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

from engine_alpha.core.paths import REPORTS


def extract_burst_trades(num_trades: int = 13) -> List[Dict[str, Any]]:
    """
    Extract the last N trades from trades.jsonl.
    
    Returns:
        List of trade dictionaries
    """
    trades_path = REPORTS / "trades.jsonl"
    if not trades_path.exists():
        raise FileNotFoundError(f"Trades file not found: {trades_path}")
    
    trades = []
    with trades_path.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                trade = json.loads(line)
                trades.append(trade)
            except json.JSONDecodeError:
                continue
    
    if len(trades) < num_trades:
        print(f"⚠️  Only {len(trades)} trades found, using all of them")
        return trades
    
    return trades[-num_trades:]


def build_burst_reflection_input(burst_trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Build a minimal reflection input structure for the burst.
    
    Returns:
        Reflection input dictionary
    """
    closes = [t for t in burst_trades if t.get("type") == "close" or t.get("event") == "CLOSE"]
    opens = [t for t in burst_trades if t.get("type") == "open" or t.get("event") == "OPEN"]
    
    # Extract exit reasons and confidences
    exit_reasons = {}
    exit_confs = []
    regimes = {}
    risk_bands = {}
    
    for close in closes:
        reason = close.get("exit_reason", "unknown")
        exit_reasons[reason] = exit_reasons.get(reason, 0) + 1
        
        conf = close.get("exit_conf")
        if conf is not None:
            exit_confs.append(float(conf))
        
        regime = close.get("regime")
        if regime:
            regimes[regime] = regimes.get(regime, 0) + 1
        
        band = close.get("risk_band")
        if band:
            risk_bands[band] = risk_bands.get(band, 0) + 1
    
    # Compute burst PF
    wins = sum(float(t.get("pct", 0.0)) for t in closes if float(t.get("pct", 0.0)) > 0)
    losses = -sum(float(t.get("pct", 0.0)) for t in closes if float(t.get("pct", 0.0)) < 0)
    pf = wins / losses if losses > 0 else (float("inf") if wins > 0 else 0.0)
    
    # Time compression analysis
    timestamps = [t.get("ts") for t in burst_trades if t.get("ts")]
    time_span = None
    if len(timestamps) >= 2:
        try:
            first_ts = datetime.fromisoformat(timestamps[0].replace("Z", "+00:00"))
            last_ts = datetime.fromisoformat(timestamps[-1].replace("Z", "+00:00"))
            time_span = (last_ts - first_ts).total_seconds()
        except Exception:
            pass
    
    reflection_input = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "analysis_type": "burst_micro_reflection",
        "burst_window": {
            "num_trades": len(burst_trades),
            "num_closes": len(closes),
            "num_opens": len(opens),
            "first_ts": timestamps[0] if timestamps else None,
            "last_ts": timestamps[-1] if timestamps else None,
            "time_span_seconds": time_span,
        },
        "burst_trades": burst_trades,
        "burst_summary": {
            "pf": pf,
            "wins": wins,
            "losses": losses,
            "exit_reasons": exit_reasons,
            "exit_conf_avg": sum(exit_confs) / len(exit_confs) if exit_confs else None,
            "exit_conf_min": min(exit_confs) if exit_confs else None,
            "exit_conf_max": max(exit_confs) if exit_confs else None,
            "regime_distribution": regimes,
            "risk_band_distribution": risk_bands,
        },
    }
    
    return reflection_input


def run_gpt_analysis(reflection_input: Dict[str, Any]) -> str:
    """
    Run GPT analysis on the burst reflection input.
    
    Returns:
        GPT analysis text
    """
    try:
        from engine_alpha.reflect.gpt_reflection_template import build_example_prompt_bundle
        import os
    except ImportError as e:
        raise ImportError(f"Missing required dependencies: {e}")
    
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("OpenAI package not installed. Install with: pip install openai")
    
    bundle = build_example_prompt_bundle(reflection_input)
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable not set")
    
    try:
        client = OpenAI(api_key=api_key)
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": bundle["system"]},
                {"role": "user", "content": bundle["user"]},
            ],
            temperature=0.7,
        )
        
        return response.choices[0].message.content
    except Exception as e:
        raise RuntimeError(f"GPT analysis failed: {e}")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Analyze a burst of trades (micro-reflection)"
    )
    parser.add_argument(
        "--num-trades",
        type=int,
        default=13,
        help="Number of trades to analyze (default: 13)",
    )
    parser.add_argument(
        "--gpt",
        action="store_true",
        help="Run GPT analysis on the burst",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output file for reflection input JSON (optional)",
    )
    
    args = parser.parse_args()
    
    try:
        print(f"🔍 Extracting last {args.num_trades} trades...")
        burst_trades = extract_burst_trades(args.num_trades)
        
        if not burst_trades:
            print("❌ No trades found")
            return
        
        print(f"✅ Found {len(burst_trades)} trades")
        
        print(f"\n📊 Building burst reflection input...")
        reflection_input = build_burst_reflection_input(burst_trades)
        
        # Print summary
        summary = reflection_input["burst_summary"]
        print(f"\n📈 Burst Summary:")
        print(f"   Trades: {reflection_input['burst_window']['num_trades']}")
        print(f"   Closes: {reflection_input['burst_window']['num_closes']}")
        print(f"   PF: {summary['pf']:.3f}" if summary['pf'] != float('inf') else f"   PF: ∞")
        print(f"   Exit reasons: {summary['exit_reasons']}")
        print(f"   Regimes: {summary['regime_distribution']}")
        print(f"   Risk bands: {summary['risk_band_distribution']}")
        if reflection_input['burst_window']['time_span_seconds']:
            span = reflection_input['burst_window']['time_span_seconds']
            print(f"   Time span: {span:.1f} seconds ({span/60:.1f} minutes)")
        
        # Save reflection input if requested
        if args.output:
            output_path = Path(args.output)
            with output_path.open("w") as f:
                json.dump(reflection_input, f, indent=2)
            print(f"\n✅ Saved reflection input to {output_path}")
        
        # Run GPT analysis if requested
        if args.gpt:
            print(f"\n🤖 Running GPT analysis...")
            try:
                analysis = run_gpt_analysis(reflection_input)
                print(f"\n{'='*60}")
                print(f"GPT ANALYSIS:")
                print(f"{'='*60}\n")
                print(analysis)
                print(f"\n{'='*60}")
            except Exception as e:
                print(f"❌ GPT analysis failed: {e}")
                import traceback
                traceback.print_exc()
        else:
            print(f"\n💡 Tip: Add --gpt flag to run GPT analysis")
            print(f"   Example: python3 -m tools.analyze_burst --num-trades 13 --gpt")
        
    except Exception as e:
        print(f"❌ Error: {e}", file=__import__("sys").stderr)
        import traceback
        traceback.print_exc()
        exit(1)


if __name__ == "__main__":
    main()

