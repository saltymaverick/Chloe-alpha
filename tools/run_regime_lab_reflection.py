#!/usr/bin/env python3
"""
Run GPT Reflection on Regime Lab Backtest Results
Analyzes a single regime's performance and produces regime-local recommendations.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional

from engine_alpha.reflect.regime_lab_reflection_template import (
    SYSTEM_PROMPT,
    build_user_prompt,
)


def load_trades(trades_path: Path, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Load trades from trades.jsonl, optionally limited."""
    trades = []
    if not trades_path.exists():
        return trades
    
    with trades_path.open("r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                trades.append(json.loads(line))
                if limit and len(trades) >= limit:
                    break
            except Exception:
                continue
    
    return trades


def load_summary(summary_path: Path) -> Dict[str, Any]:
    """Load summary.json."""
    if not summary_path.exists():
        return {}
    try:
        return json.loads(summary_path.read_text())
    except Exception:
        return {}


def load_meta(meta_path: Path) -> Dict[str, Any]:
    """Load meta.json."""
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text())
    except Exception:
        return {}


def compute_report(trades_path: Path, summary: Dict[str, Any]) -> Dict[str, Any]:
    """Compute report stats from trades."""
    from collections import Counter
    
    trades = load_trades(trades_path)
    closes = [t for t in trades if t.get("type") == "close"]
    
    if not closes:
        return {
            "closes": 0,
            "wins": 0,
            "losses": 0,
            "pf": 0.0,
            "exit_reasons": {},
            "avg_bars_open": 0.0,
        }
    
    wins = [c for c in closes if c.get("pct", 0) > 0]
    losses = [c for c in closes if c.get("pct", 0) < 0]
    pos_sum = sum(c.get("pct", 0) for c in wins)
    neg_sum = abs(sum(c.get("pct", 0) for c in losses))
    pf = pos_sum / neg_sum if neg_sum > 0 else (float("inf") if pos_sum > 0 else 0.0)
    
    exit_reasons = Counter(c.get("exit_reason", "unknown") for c in closes)
    
    bars_open_list = [c.get("bars_open", 0) for c in closes if c.get("bars_open") is not None]
    avg_bars_open = sum(bars_open_list) / len(bars_open_list) if bars_open_list else 0.0
    
    return {
        "closes": len(closes),
        "wins": len(wins),
        "losses": len(losses),
        "pf": pf,
        "pos_sum": pos_sum,
        "neg_sum": -neg_sum,
        "exit_reasons": dict(exit_reasons),
        "avg_bars_open": avg_bars_open,
    }


def run_reflection(
    run_dir: Path,
    api_key: Optional[str] = None,
    model: str = "gpt-4o-mini",
    max_tokens: int = 2000,
) -> Dict[str, Any]:
    """
    Run GPT reflection on regime lab results.
    
    Args:
        run_dir: Path to backtest run directory
        api_key: OpenAI API key (or use OPENAI_API_KEY env var)
        model: GPT model to use
        max_tokens: Max tokens for response
    
    Returns:
        Dict with reflection results
    """
    try:
        import openai
    except ImportError:
        raise ImportError("openai package required. Install with: pip install openai")
    
    # Load data
    meta_path = run_dir / "meta.json"
    summary_path = run_dir / "summary.json"
    trades_path = run_dir / "trades.jsonl"
    
    meta = load_meta(meta_path)
    summary = load_summary(summary_path)
    report = compute_report(trades_path, summary)
    
    regime = meta.get("regime", "unknown")
    
    # Load sample trades (closes only, first 20)
    all_trades = load_trades(trades_path)
    closes_sample = [t for t in all_trades if t.get("type") == "close"][:20]
    
    # Build prompts
    system_prompt = SYSTEM_PROMPT
    user_prompt = build_user_prompt(regime, summary, report, closes_sample)
    
    # Get API key
    api_key = api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable not set and no api_key provided")
    
    # Call GPT
    client = openai.OpenAI(api_key=api_key)
    
    print(f"🤖 Calling GPT ({model}) for regime: {regime}")
    print(f"   Trades: {summary.get('closes', 0)} closes")
    print(f"   PF: {report.get('pf', 0.0):.3f}")
    print()
    
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=max_tokens,
        temperature=0.7,
    )
    
    reflection_text = response.choices[0].message.content
    
    # Try to extract JSON from response
    import re
    json_match = re.search(r'\{[^{}]*"regime"[^{}]*\{[^{}]*\}', reflection_text, re.DOTALL)
    if json_match:
        try:
            recommendations = json.loads(json_match.group(0))
        except Exception:
            recommendations = None
    else:
        recommendations = None
    
    return {
        "regime": regime,
        "reflection": reflection_text,
        "recommendations": recommendations,
        "meta": meta,
        "summary": summary,
        "report": report,
    }


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run GPT reflection on Regime Lab backtest results"
    )
    parser.add_argument(
        "--run-dir",
        type=str,
        required=True,
        help="Path to backtest run directory",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="OpenAI API key (or use OPENAI_API_KEY env var)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gpt-4o-mini",
        help="GPT model to use (default: gpt-4o-mini)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=2000,
        help="Max tokens for response (default: 2000)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path (default: run_dir/reflection.json)",
    )
    
    args = parser.parse_args()
    run_dir = Path(args.run_dir)
    
    if not run_dir.exists():
        print(f"❌ Error: Run directory not found: {run_dir}")
        return
    
    try:
        result = run_reflection(
            run_dir=run_dir,
            api_key=args.api_key,
            model=args.model,
            max_tokens=args.max_tokens,
        )
        
        # Save result
        output_path = Path(args.output) if args.output else run_dir / "reflection.json"
        output_path.write_text(json.dumps(result, indent=2))
        
        print(f"\n✅ Reflection complete!")
        print(f"   Saved to: {output_path}")
        print(f"\n📊 Reflection Summary:")
        print("=" * 70)
        print(result["reflection"])
        print("=" * 70)
        
        if result.get("recommendations"):
            print(f"\n💡 Recommendations JSON:")
            print(json.dumps(result["recommendations"], indent=2))
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()


