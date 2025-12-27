"""
Quality Scores - Compute volatility-adjusted symbol quality score per symbol.

Score is a weighted blend of PF, sample size, and Dream scenario labels.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, Optional

ROOT = Path(__file__).resolve().parents[1]
GPT_REPORT_DIR = ROOT / "reports" / "gpt"
QUALITY_SCORES_PATH = GPT_REPORT_DIR / "quality_scores.json"


def load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def compute_quality_score(
    exp_pf: Optional[float],
    exp_trades: int,
    norm_pf: Optional[float],
    norm_trades: int,
    dream_good: int,
    dream_bad: int,
    dream_improve: int,
) -> float:
    """
    Compute quality score (0-100) based on multiple factors.
    
    Scoring:
    - BaseScore from PF:
      - exp_pf >= 2.0 → +25
      - exp_pf around 1.0 → ~+10
      - exp_pf < 0.5 → negative contribution
    - SampleSize bonus:
      - exp_trades >= 8 → +10
      - 4-7 → +5
      - <4 → 0
    - Dream labels:
      - each "good" → +2
      - each "bad" → -3
      - each "improve" → -1
    """
    score = 50.0  # Base score
    
    # PF contribution
    if exp_pf is not None:
        if exp_pf == float("inf"):
            score += 30
        elif exp_pf >= 2.0:
            score += 25
        elif exp_pf >= 1.5:
            score += 20
        elif exp_pf >= 1.0:
            score += 10
        elif exp_pf >= 0.5:
            score += 5
        elif exp_pf < 0.5:
            score -= 10 * (0.5 - exp_pf)  # Penalty for low PF
    
    # Normal PF contribution (smaller weight)
    if norm_pf is not None and norm_trades > 0:
        if norm_pf == float("inf"):
            score += 5
        elif norm_pf >= 1.5:
            score += 5
        elif norm_pf >= 1.0:
            score += 2
        elif norm_pf < 0.5:
            score -= 5
    
    # Sample size bonus
    if exp_trades >= 8:
        score += 10
    elif exp_trades >= 4:
        score += 5
    
    if norm_trades >= 2:
        score += 2
    
    # Dream labels
    score += dream_good * 2
    score -= dream_bad * 3
    score -= dream_improve * 1
    
    # Clamp between 0 and 100
    return max(0.0, min(100.0, score))


def main() -> None:
    """Compute and display quality scores."""
    print("QUALITY SCORES")
    print("=" * 70)
    print()
    
    # Load data
    refl_in = load_json(GPT_REPORT_DIR / "reflection_input.json")
    dream_out = load_json(GPT_REPORT_DIR / "dream_output.json")
    
    # Build Dream stats per symbol
    dream_stats: Dict[str, Dict[str, int]] = {}
    scenarios = dream_out.get("scenario_reviews", [])
    
    for sc in scenarios:
        sym = sc.get("symbol")
        if not sym:
            continue
        dream_stats.setdefault(sym, {"good": 0, "bad": 0, "improve": 0, "flat": 0})
        label = sc.get("label", "").lower()
        if label in ("good", "bad", "improve", "flat"):
            dream_stats[sym][label] += 1
    
    # Get symbol stats from reflection_input
    symbols_data = refl_in.get("symbols", {})
    
    quality_scores: Dict[str, Dict[str, Any]] = {}
    
    for sym, data in symbols_data.items():
        # Extract stats
        exp_pf = data.get("exploration_pf")
        exp_trades = data.get("exploration_trades", 0)
        norm_pf = data.get("normal_pf")
        norm_trades = data.get("normal_trades", 0)
        
        # Get Dream stats
        ds = dream_stats.get(sym, {})
        dream_good = ds.get("good", 0)
        dream_bad = ds.get("bad", 0)
        dream_improve = ds.get("improve", 0)
        
        # Compute score
        score = compute_quality_score(
            exp_pf, exp_trades, norm_pf, norm_trades,
            dream_good, dream_bad, dream_improve
        )
        
        quality_scores[sym] = {
            "score": round(score, 1),
            "exp_pf": exp_pf if exp_pf != float("inf") else "inf",
            "exp_trades": exp_trades,
            "norm_pf": norm_pf if norm_pf != float("inf") else "inf",
            "norm_trades": norm_trades,
            "dream_good": dream_good,
            "dream_bad": dream_bad,
            "dream_improve": dream_improve,
        }
    
    if not quality_scores:
        print("⚠️  No symbol data found")
        print("   Run reflection cycle first: python3 -m tools.run_reflection_cycle")
        return
    
    # Write JSON
    GPT_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    QUALITY_SCORES_PATH.write_text(json.dumps(quality_scores, indent=2, sort_keys=True))
    print(f"✅ Quality scores written to: {QUALITY_SCORES_PATH}")
    print()
    
    # Print console view sorted by score
    print("QUALITY SCORES (sorted by score):")
    print("-" * 70)
    print(f"{'Symbol':<12} {'Score':>6} {'ExpPF':>7} {'ExpTrades':>10} {'Dream':>10}")
    print("-" * 70)
    
    sorted_syms = sorted(quality_scores.items(), key=lambda x: x[1]["score"], reverse=True)
    
    for sym, data in sorted_syms:
        exp_pf_str = str(data["exp_pf"]) if data["exp_pf"] != "inf" else "∞"
        dream_str = f"G:{data['dream_good']} B:{data['dream_bad']} I:{data['dream_improve']}"
        print(f"{sym:<12} {data['score']:>6.1f} {exp_pf_str:>7} {data['exp_trades']:>10} {dream_str:>10}")
    
    print()


if __name__ == "__main__":
    main()

