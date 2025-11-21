#!/usr/bin/env python3
"""
Council Weight Learner - Phase 50
Offline learning system for council weight optimization.

PURPOSE:
--------
This module implements an offline learning pipeline for optimizing council weights:

1. Loads base weights from config/council_weights.yaml
2. Generates N candidate weight sets using mutate_weights.py
3. Runs backtests for each candidate using tools.backtest_harness
4. Collects metrics from backtest summary.json (PF, drawdown, equity_change%)
5. Ranks candidates by PF > drawdown safety
6. Saves leaderboard to reports/council_learning/run_<id>/leaderboard.json

ARCHITECTURE:
--------------
- All experiments are isolated in backtest runs
- Mutated weights are saved to reports/council_learning/run_<id>/candidate_<n>.yaml
- Backtests write results to reports/backtest/<run_id>/
- Leaderboard ranks candidates by: PF > drawdown safety (PF must be > 1.0, drawdown must be < 10%)

SAFETY:
-------
- This is OFFLINE ONLY. No changes are applied to live trading automatically.
- All experiments are isolated in backtest runs.
- Weight mutations are temporary files used only for backtests.
- Live trading continues using config/council_weights.yaml (or defaults).

ASSUMPTIONS:
-----------
- config/council_weights.yaml exists
- tools.backtest_harness is available
- tools.mutate_weights is available
- Backtest harness writes summary.json with equity_change_pct
- PF and drawdown can be computed from backtest trades.jsonl or equity_curve.jsonl

USAGE:
------
    python3 -m tools.council_weight_learner \\
        --symbol ETHUSDT \\
        --timeframe 1h \\
        --start 2025-01-01T00:00:00Z \\
        --end 2025-01-07T00:00:00Z \\
        --num-candidates 5
"""

from __future__ import annotations

import argparse
import json
import subprocess
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

from engine_alpha.core.paths import REPORTS


BASE_WEIGHTS_PATH = Path(__file__).parent.parent / "config" / "council_weights.yaml"
LEARNING_DIR = REPORTS / "council_learning"
MEMORY_LESSONS_PATH = REPORTS / "memory" / "long_term_lessons.json"


def _compute_pf_from_trades(trades_path: Path) -> Optional[float]:
    """
    Compute PF from trades.jsonl file.
    
    Returns:
        Profit factor or None if no trades or error
    """
    if not trades_path.exists():
        return None
    
    wins = 0.0
    losses = 0.0
    
    try:
        with trades_path.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trade = json.loads(line)
                    if trade.get("type") != "close":
                        continue
                    pct = trade.get("pct")
                    if pct is None:
                        continue
                    pct = float(pct)
                    if pct > 0:
                        wins += pct
                    elif pct < 0:
                        losses += abs(pct)
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue
    except Exception:
        return None
    
    if losses == 0:
        return float("inf") if wins > 0 else None
    
    return wins / losses


def _compute_drawdown_from_equity(equity_curve_path: Path) -> Optional[float]:
    """
    Compute max drawdown from equity_curve.jsonl file.
    
    Returns:
        Max drawdown as fraction (0.0-1.0) or None if error
    """
    if not equity_curve_path.exists():
        return None
    
    equity_points = []
    try:
        with equity_curve_path.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    point = json.loads(line)
                    equity = point.get("equity")
                    if equity is not None:
                        equity_points.append(float(equity))
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue
    except Exception:
        return None
    
    if len(equity_points) < 2:
        return None
    
    peak = equity_points[0]
    max_dd = 0.0
    
    for equity in equity_points:
        if equity > peak:
            peak = equity
        dd = max(0.0, 1.0 - (equity / peak)) if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    
    return max_dd


def _run_backtest_for_candidate(
    candidate_id: int,
    weights_file: Path,
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
    limit: int,
) -> Optional[Dict[str, Any]]:
    """
    Run a backtest for a weight candidate.
    
    Returns:
        Dict with backtest results including PF, drawdown, equity_change_pct
    """
    try:
        import os
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).parent.parent)
        env["COUNCIL_WEIGHTS_FILE"] = str(weights_file.absolute())
        
        cmd = [
            "python3", "-m", "tools.backtest_harness",
            "--symbol", symbol,
            "--timeframe", timeframe,
            "--start", start,
            "--end", end,
            "--limit", str(limit),
            "--weights-file", str(weights_file.absolute()),
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
            env=env,
        )
        
        if result.returncode != 0:
            print(f"   ⚠️  Backtest failed: {result.stderr[:200]}")
            return None
        
        # Find the backtest run directory (last created)
        backtest_base = REPORTS / "backtest"
        if not backtest_base.exists():
            return None
        
        runs = sorted(backtest_base.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        if not runs:
            return None
        
        run_dir = runs[0]
        
        # Read summary.json
        summary_path = run_dir / "summary.json"
        if not summary_path.exists():
            return None
        
        with summary_path.open("r") as f:
            summary = json.load(f)
        
        # Compute PF from trades.jsonl
        trades_path = run_dir / "trades.jsonl"
        pf = _compute_pf_from_trades(trades_path)
        
        # Compute drawdown from equity_curve.jsonl
        equity_curve_path = run_dir / "equity_curve.jsonl"
        drawdown = _compute_drawdown_from_equity(equity_curve_path)
        
        return {
            "run_dir": str(run_dir),
            "summary": summary,
            "weights_file": str(weights_file),
            "pf": pf,
            "drawdown": drawdown,
            "equity_change_pct": summary.get("equity_change_pct", 0.0),
        }
    except Exception as e:
        print(f"   ⚠️  Error running backtest: {e}")
        return None


def _rank_candidates(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Rank candidates by PF > drawdown safety.
    
    Ranking criteria:
    1. PF must be > 1.0 (profitable)
    2. Drawdown must be < 10% (safe)
    3. Higher PF is better
    4. Lower drawdown is better (if PF > 1.0)
    
    Returns:
        Sorted list of results (best first)
    """
    def score_candidate(candidate: Dict[str, Any]) -> tuple[bool, float, float]:
        """Return (is_safe, pf_score, dd_score) for sorting."""
        pf = candidate.get("pf")
        dd = candidate.get("drawdown")
        
        # Check safety: PF > 1.0 and DD < 0.10
        is_safe = (
            pf is not None and pf > 1.0 and
            dd is not None and dd < 0.10
        )
        
        # Score: PF (higher is better), negative DD (lower is better)
        pf_score = pf if pf is not None and pf != float("inf") else 0.0
        dd_score = -dd if dd is not None else 0.0
        
        return (is_safe, pf_score, dd_score)
    
    # Sort: safe candidates first, then by PF (desc), then by DD (asc)
    sorted_results = sorted(results, key=score_candidate, reverse=True)
    
    return sorted_results


def _load_memory_lessons() -> Dict[str, Any]:
    """
    Load lessons from memory aggregator.
    
    Returns:
        Dict with lessons, bucket_memory, and performance_history
    """
    if not MEMORY_LESSONS_PATH.exists():
        return {}
    
    try:
        with MEMORY_LESSONS_PATH.open("r") as f:
            return json.load(f)
    except Exception:
        return {}


def run_council_learning(
    symbol: str = "ETHUSDT",
    timeframe: str = "1h",
    start: str = None,
    end: str = None,
    limit: int = 200,
    num_candidates: int = 5,
    use_memory_lessons: bool = True,
) -> Dict[str, Any]:
    """
    Main council weight learning function.
    
    Returns:
        Dict with learning results including leaderboard
    """
    # Create learning run directory
    run_id = uuid.uuid4().hex[:8]
    learning_run_dir = LEARNING_DIR / f"run_{run_id}"
    learning_run_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Council Weight Learning - Phase 50")
    print(f"Run ID: {run_id}")
    print(f"Learning directory: {learning_run_dir}")
    
    # Load memory lessons if available
    memory_lessons = {}
    if use_memory_lessons:
        memory_lessons = _load_memory_lessons()
        if memory_lessons:
            print(f"\n📚 Memory lessons loaded:")
            global_lessons = memory_lessons.get("global_lessons", [])
            bucket_memory = memory_lessons.get("bucket_memory", {})
            if global_lessons:
                for lesson in global_lessons:
                    print(f"   • {lesson}")
            if bucket_memory.get("bucket_weights"):
                print(f"   • Bucket weight suggestions: {bucket_memory['bucket_weights']}")
        else:
            print(f"\n⚠️  No memory lessons found (run memory aggregator first)")
    
    # Check base weights file
    if not BASE_WEIGHTS_PATH.exists():
        print(f"❌ Base weights file not found: {BASE_WEIGHTS_PATH}")
        return {}
    
    # Use default date range if not provided
    if not start or not end:
        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(days=7)
        start = start_dt.isoformat()
        end = end_dt.isoformat()
    
    print(f"\n1. Generating {num_candidates} weight candidates...")
    candidates = []
    
    for i in range(1, num_candidates + 1):
        weights_file = learning_run_dir / f"candidate_{i}.yaml"
        
        try:
            from tools.mutate_weights import mutate_weights
            mutate_weights(
                base_weights_path=BASE_WEIGHTS_PATH,
                output_path=weights_file,
                num_mutations=2,  # Mutate 2 buckets per regime
            )
            candidates.append({
                "candidate_id": i,
                "weights_file": str(weights_file),
            })
            print(f"   ✅ Candidate {i} generated")
        except Exception as e:
            print(f"   ⚠️  Failed to generate candidate {i}: {e}")
    
    if not candidates:
        print("❌ No candidates generated")
        return {}
    
    # Run backtests for each candidate
    print(f"\n2. Running backtests for {len(candidates)} candidates...")
    results = []
    
    for candidate in candidates:
        candidate_id = candidate["candidate_id"]
        weights_file = Path(candidate["weights_file"])
        
        print(f"\n   Candidate {candidate_id}/{len(candidates)}:")
        result = _run_backtest_for_candidate(
            candidate_id=candidate_id,
            weights_file=weights_file,
            symbol=symbol,
            timeframe=timeframe,
            start=start,
            end=end,
            limit=limit,
        )
        
        if result:
            results.append({
                "candidate_id": candidate_id,
                **result,
            })
            pf_str = f"{result.get('pf', 'N/A'):.3f}" if result.get('pf') else "N/A"
            dd_str = f"{result.get('drawdown', 0.0)*100:.2f}%" if result.get('drawdown') is not None else "N/A"
            print(f"   ✅ PF={pf_str}, DD={dd_str}, Equity={result.get('equity_change_pct', 0.0):+.2f}%")
        else:
            print(f"   ⚠️  Backtest failed")
    
    if not results:
        print("❌ No successful backtests")
        return {}
    
    # Rank candidates
    print(f"\n3. Ranking candidates by PF > drawdown safety...")
    ranked_results = _rank_candidates(results)
    
    # Build leaderboard
    leaderboard = []
    for rank, result in enumerate(ranked_results, 1):
        pf = result.get("pf")
        dd = result.get("drawdown")
        is_safe = (
            pf is not None and pf > 1.0 and
            dd is not None and dd < 0.10
        )
        
        leaderboard.append({
            "rank": rank,
            "candidate_id": result.get("candidate_id"),
            "pf": pf,
            "drawdown": dd,
            "equity_change_pct": result.get("equity_change_pct"),
            "is_safe": is_safe,
            "weights_file": result.get("weights_file"),
            "run_dir": result.get("run_dir"),
        })
    
    # Save leaderboard
    leaderboard_path = learning_run_dir / "leaderboard.json"
    with leaderboard_path.open("w") as f:
        json.dump({
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "timeframe": timeframe,
            "start": start,
            "end": end,
            "num_candidates": num_candidates,
            "memory_lessons_used": bool(memory_lessons),
            "memory_lessons": memory_lessons,
            "leaderboard": leaderboard,
        }, f, indent=2)
    
    print(f"\n✅ Learning complete!")
    print(f"   Results: {learning_run_dir}")
    print(f"   Leaderboard: {leaderboard_path}")
    
    # Print top 3
    print(f"\n   Top 3 candidates:")
    for entry in leaderboard[:3]:
        pf_str = f"{entry.get('pf', 0.0):.3f}" if entry.get('pf') else "N/A"
        dd_str = f"{entry.get('drawdown', 0.0)*100:.2f}%" if entry.get('drawdown') is not None else "N/A"
        safe_str = "✅ SAFE" if entry.get("is_safe") else "⚠️  UNSAFE"
        print(f"      Rank {entry.get('rank')}: PF={pf_str}, DD={dd_str}, {safe_str}")
    
    return {
        "run_id": run_id,
        "learning_dir": str(learning_run_dir),
        "leaderboard": leaderboard,
    }


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Council Weight Learner - Offline learning for weight optimization"
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="ETHUSDT",
        help="Trading symbol (default: ETHUSDT)",
    )
    parser.add_argument(
        "--timeframe",
        type=str,
        default="1h",
        help="Timeframe (default: 1h)",
    )
    parser.add_argument(
        "--start",
        type=str,
        help="Start timestamp (ISO8601, optional - defaults to 7 days ago)",
    )
    parser.add_argument(
        "--end",
        type=str,
        help="End timestamp (ISO8601, optional - defaults to now)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Number of candles to fetch (default: 200)",
    )
    parser.add_argument(
        "--num-candidates",
        type=int,
        default=5,
        help="Number of weight candidates to generate (default: 5)",
    )
    parser.add_argument(
        "--no-memory",
        action="store_true",
        help="Skip loading memory lessons (default: use memory lessons)",
    )
    
    args = parser.parse_args()
    
    try:
        result = run_council_learning(
            symbol=args.symbol,
            timeframe=args.timeframe,
            start=args.start,
            end=args.end,
            limit=args.limit,
            num_candidates=args.num_candidates,
            use_memory_lessons=not args.no_memory,
        )
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"❌ Error: {e}", file=__import__("sys").stderr)
        import traceback
        traceback.print_exc()
        exit(1)


if __name__ == "__main__":
    main()
