#!/usr/bin/env python3
"""
GPT Threshold Tuner - GPT-guided entry threshold tuning

Uses OpenAI GPT to read signal return analysis summary and propose updated
per-regime entry thresholds.

Example usage:
    # Dry run (just prints recommendations)
    python3 -m tools.gpt_threshold_tuner \
      --summary reports/analysis/conf_ret_summary.json
    
    # Apply recommendations to config/entry_thresholds.json
    python3 -m tools.gpt_threshold_tuner \
      --summary reports/analysis/conf_ret_summary.json \
      --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Any, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from openai import OpenAI
except ImportError:
    print("❌ Error: openai package not installed. Install with: pip install openai")
    sys.exit(1)

from engine_alpha.core.paths import CONFIG
from engine_alpha.loop.exit_rules import DEFAULT_EXIT, ExitParams


# Default thresholds (must match autonomous_trader.py)
ENTRY_THRESHOLDS_DEFAULT = {
    "trend_down": 0.50,
    "high_vol": 0.55,
    "trend_up": 0.60,
    "chop": 0.65,
}

# Default regime enable flags (must match autonomous_trader.py)
REGIME_ENABLE_DEFAULT = {
    "trend_down": True,
    "high_vol": True,
    "trend_up": False,
    "chop": False,
}


def load_current_thresholds() -> Dict[str, float]:
    """Load current thresholds from config/entry_thresholds.json."""
    cfg_path = CONFIG / "entry_thresholds.json"
    if not cfg_path.exists():
        return dict(ENTRY_THRESHOLDS_DEFAULT)
    
    try:
        data = json.loads(cfg_path.read_text())
        merged = dict(ENTRY_THRESHOLDS_DEFAULT)
        merged.update({k: float(v) for k, v in data.items() if isinstance(v, (int, float, str))})
        return merged
    except Exception:
        return dict(ENTRY_THRESHOLDS_DEFAULT)


def load_regime_enable() -> Dict[str, bool]:
    """Load current regime enable flags from config/regime_enable.json."""
    cfg_path = CONFIG / "regime_enable.json"
    if not cfg_path.exists():
        return dict(REGIME_ENABLE_DEFAULT)
    
    try:
        data = json.loads(cfg_path.read_text())
        merged = dict(REGIME_ENABLE_DEFAULT)
        # Only keep boolean-like entries
        for k, v in data.items():
            if isinstance(v, bool):
                merged[k] = v
        return merged
    except Exception:
        return dict(REGIME_ENABLE_DEFAULT)


def save_entry_thresholds(thresholds: Dict[str, float]) -> None:
    """Save thresholds to config/entry_thresholds.json."""
    cfg_path = CONFIG / "entry_thresholds.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Preserve any existing non-threshold fields
    existing_data = {}
    if cfg_path.exists():
        try:
            existing_data = json.loads(cfg_path.read_text())
        except Exception:
            pass
    
    # Update threshold fields
    for regime, threshold in thresholds.items():
        existing_data[regime] = float(threshold)
    
    cfg_path.write_text(json.dumps(existing_data, indent=2, sort_keys=True))


def load_exit_rules() -> Dict[str, Dict[str, Any]]:
    """Load current exit rules from config/exit_rules.json."""
    cfg_path = CONFIG / "exit_rules.json"
    if not cfg_path.exists():
        return {"default": {
            "min_hold_bars": DEFAULT_EXIT.min_hold_bars,
            "tp_return_min": DEFAULT_EXIT.tp_return_min,
            "sl_return": DEFAULT_EXIT.sl_return,
            "tp_conf_min": DEFAULT_EXIT.tp_conf_min,
            "sl_conf_min": DEFAULT_EXIT.sl_conf_min,
            "decay_bars": DEFAULT_EXIT.decay_bars,
            "drop_return_max": DEFAULT_EXIT.drop_return_max,
        }}
    
    try:
        return json.loads(cfg_path.read_text())
    except Exception:
        return {"default": {
            "min_hold_bars": DEFAULT_EXIT.min_hold_bars,
            "tp_return_min": DEFAULT_EXIT.tp_return_min,
            "sl_return": DEFAULT_EXIT.sl_return,
            "tp_conf_min": DEFAULT_EXIT.tp_conf_min,
            "sl_conf_min": DEFAULT_EXIT.sl_conf_min,
            "decay_bars": DEFAULT_EXIT.decay_bars,
            "drop_return_max": DEFAULT_EXIT.drop_return_max,
        }}


def save_exit_rules(exit_rules: Dict[str, Dict[str, Any]]) -> None:
    """Save exit rules to config/exit_rules.json."""
    cfg_path = CONFIG / "exit_rules.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Validate and normalize
    normalized = {}
    for regime, params in exit_rules.items():
        normalized[regime] = {
            "min_hold_bars": int(params.get("min_hold_bars", DEFAULT_EXIT.min_hold_bars)),
            "tp_return_min": float(params.get("tp_return_min", DEFAULT_EXIT.tp_return_min)),
            "sl_return": float(params.get("sl_return", DEFAULT_EXIT.sl_return)),
            "tp_conf_min": float(params.get("tp_conf_min", DEFAULT_EXIT.tp_conf_min)),
            "sl_conf_min": float(params.get("sl_conf_min", DEFAULT_EXIT.sl_conf_min)),
            "decay_bars": int(params.get("decay_bars", DEFAULT_EXIT.decay_bars)),
            "drop_return_max": float(params.get("drop_return_max", DEFAULT_EXIT.drop_return_max)),
        }
    
    cfg_path.write_text(json.dumps(normalized, indent=2))


def save_regime_enable(enable_flags: Dict[str, bool]) -> None:
    """Save regime enable flags to config/regime_enable.json."""
    cfg_path = CONFIG / "regime_enable.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Preserve any existing non-boolean fields (if any)
    existing_data = {}
    if cfg_path.exists():
        try:
            existing_data = json.loads(cfg_path.read_text())
        except Exception:
            pass
    
    # Update enable flags (only boolean values)
    for regime, enabled in enable_flags.items():
        if isinstance(enabled, bool):
            existing_data[regime] = enabled
    
    cfg_path.write_text(json.dumps(existing_data, indent=2, sort_keys=True))


def load_summary(summary_path: Path) -> Dict[str, Any]:
    """Load the signal return analysis summary."""
    if not summary_path.exists():
        raise FileNotFoundError(f"Summary file not found: {summary_path}")
    
    with open(summary_path, "r") as f:
        return json.load(f)


def aggregate_by_regime(summary: Dict[str, Any], min_count: int = 20) -> Dict[str, Dict[str, Any]]:
    """Aggregate bins by regime, filtering out low-count bins."""
    regime_stats = defaultdict(lambda: {
        "count": 0,
        "wins": 0,
        "losses": 0,
        "pos_sum": 0.0,
        "neg_sum": 0.0,
        "bins": [],
    })
    
    for bin_data in summary.get("bins", []):
        count = bin_data.get("count", 0)
        if count < min_count:
            continue
        
        regime = bin_data.get("regime", "unknown")
        stats = regime_stats[regime]
        
        stats["count"] += count
        stats["wins"] += bin_data.get("wins", 0)
        stats["losses"] += bin_data.get("losses", 0)
        stats["pos_sum"] += bin_data.get("pos_sum", 0.0)
        stats["neg_sum"] += bin_data.get("neg_sum", 0.0)
        stats["bins"].append(bin_data)
    
    # Compute PF per regime
    for regime, stats in regime_stats.items():
        pos_sum = stats["pos_sum"]
        neg_sum = stats["neg_sum"]
        if neg_sum > 0:
            stats["pf"] = pos_sum / neg_sum
        elif pos_sum > 0:
            stats["pf"] = float("inf")
        else:
            stats["pf"] = 0.0
    
    return dict(regime_stats)


def aggregate_by_regime_horizon(summary: Dict[str, Any], min_count: int = 20) -> Dict[str, Dict[int, Dict[str, Any]]]:
    """Aggregate bins by regime × horizon, filtering out low-count bins."""
    regime_horizon_stats: Dict[str, Dict[int, Dict[str, Any]]] = defaultdict(lambda: defaultdict(lambda: {
        "count": 0,
        "wins": 0,
        "losses": 0,
        "pos_sum": 0.0,
        "neg_sum": 0.0,
        "mean_ret": 0.0,
        "returns": [],
    }))
    
    for bin_data in summary.get("bins", []):
        count = bin_data.get("count", 0)
        if count < min_count:
            continue
        
        regime = bin_data.get("regime", "unknown")
        horizon = bin_data.get("horizon", 1)
        stats = regime_horizon_stats[regime][horizon]
        
        stats["count"] += count
        stats["wins"] += bin_data.get("wins", 0)
        stats["losses"] += bin_data.get("losses", 0)
        stats["pos_sum"] += bin_data.get("pos_sum", 0.0)
        stats["neg_sum"] += bin_data.get("neg_sum", 0.0)
        
        # For regime × horizon aggregation, keep stats from the best performing bin (by PF)
        current_pf = stats.get("pf", 0.0)
        bin_pf = bin_data.get("pf", 0.0)
        
        # Update detailed stats if this bin has better PF, or if we don't have stats yet
        if bin_pf > current_pf or current_pf == 0.0:
            stats["mean_ret"] = bin_data.get("mean_ret", 0.0)
            stats["win_rate"] = bin_data.get("win_rate", 0.0)
            stats["avg_win"] = bin_data.get("avg_win", 0.0)
            stats["avg_loss"] = bin_data.get("avg_loss", 0.0)
            stats["p95"] = bin_data.get("p95", 0.0)
            stats["p5"] = bin_data.get("p5", 0.0)
            stats["p95_ret"] = bin_data.get("p95_ret", 0.0)
            stats["p5_ret"] = bin_data.get("p5_ret", 0.0)
        
        # Collect returns for percentile analysis (if available)
        if "returns" in bin_data:
            stats["returns"].extend(bin_data.get("returns", []))
    
    # Compute PF and percentiles per regime × horizon
    for regime, horizon_dict in regime_horizon_stats.items():
        for horizon, stats in horizon_dict.items():
            pos_sum = stats["pos_sum"]
            neg_sum = abs(stats["neg_sum"])
            if neg_sum > 0:
                stats["pf"] = pos_sum / neg_sum
            elif pos_sum > 0:
                stats["pf"] = float("inf")
            else:
                stats["pf"] = 0.0
            
            # Compute percentiles if returns available
            returns = stats["returns"]
            if returns:
                sorted_returns = sorted(returns)
                stats["p50"] = sorted_returns[len(sorted_returns) // 2] if sorted_returns else 0.0
                stats["p75"] = sorted_returns[int(len(sorted_returns) * 0.75)] if sorted_returns else 0.0
                stats["p90"] = sorted_returns[int(len(sorted_returns) * 0.90)] if sorted_returns else 0.0
                stats["p95"] = sorted_returns[int(len(sorted_returns) * 0.95)] if sorted_returns else 0.0
                stats["p5"] = sorted_returns[int(len(sorted_returns) * 0.05)] if sorted_returns else 0.0
                
                # Separate positive/negative for p95_ret and p5_ret
                pos_returns = [r for r in returns if r > 0]
                if pos_returns:
                    sorted_pos = sorted(pos_returns)
                    stats["p95_ret"] = sorted_pos[int(len(sorted_pos) * 0.95)] if sorted_pos else 0.0
                else:
                    stats["p95_ret"] = 0.0
                
                # p5_ret is the worst tail (5th percentile of all returns)
                stats["p5_ret"] = stats["p5"]
    
    return dict(regime_horizon_stats)


def build_gpt_prompt(summary: Dict[str, Any], current_thresholds: Dict[str, float], current_exit_rules: Dict[str, Dict[str, Any]]) -> tuple[str, str]:
    """Build SYSTEM and USER prompts for GPT."""
    
    system_prompt = """You are a trading strategy analyst helping tune entry thresholds AND exit rules for an algorithmic trading bot.

The bot trades ETHUSDT on 1h candles and uses:
- Regime classification: trend_down, trend_up, high_vol, chop
- Confidence scores: 0.0 to 1.0 (rounded to 2 decimals)
- Entry thresholds: minimum confidence required to open a trade in each regime
- Exit rules: per-regime parameters for TP/SL/drop/decay exits

You are given:
1. Historical performance data aggregated by regime × confidence bin × horizon (1, 2, 4 bars)
2. Current entry thresholds per regime
3. Current exit rules per regime

ENTRY THRESHOLD RULES (same as before):

1. **Good bands (PF ≥ 1.2, n ≥ 100):**
   - Set threshold to lower_edge - 0.02 (e.g., if good band is [0.65-0.70), set threshold to 0.63)
   - This captures the good band while allowing some margin for rounding
   - If multiple good bands exist, use the one with highest PF or most samples

2. **Only meh bands (1.0 ≤ PF < 1.2, n ≥ 100):**
   - Keep current threshold (don't change unless current is clearly wrong)
   - If current threshold is below all meh bands, raise to lower_edge of best meh band - 0.02

3. **All bad bands (PF < 1.0, n ≥ 100):**
   - Raise threshold to avoid trading (set to 0.75+)
   - This regime should be disabled for live trading anyway

4. **Low sample size (n < 100):**
   - Ignore these bands unless they show overwhelming edge (PF > 1.5)
   - Prefer bands with n ≥ 100 for reliability

5. **Safety constraints:**
   - Hard clamp all thresholds to [0.35, 0.85]
   - Keep trend_up/chop thresholds high (≥0.65) unless data shows overwhelming, stable edge
   - Currently only trend_down and high_vol are enabled for live trading

EXIT RULES TUNING (NEW):

Based on multi-horizon performance data, propose optimal exit parameters:

1. **min_hold_bars**: Minimum bars before TP/SL can fire
   - Look at horizon with best PF (often H=2 or H=4)
   - Set min_hold_bars to that horizon (or slightly less)
   - Range: [1, 12]

2. **tp_return_min**: Minimum fractional return for TP (e.g., 0.008 = 0.8%)
   - Use p75 or p90 of positive returns at optimal horizon
   - Ensure it's achievable (not higher than p90)
   - Range: [0.001, 0.05]

3. **sl_return**: Stop-loss trigger (e.g., -0.012 = -1.2%)
   - Use p50 or p75 of negative returns at optimal horizon
   - Should be tighter than tp_return_min in absolute terms
   - Range: [-0.05, -0.002]

4. **tp_conf_min**: Minimum confidence for TP
   - Use confidence bin where PF is highest
   - Range: [0.4, 0.9]

5. **sl_conf_min**: Minimum confidence for SL
   - Usually lower than tp_conf_min (0.25-0.45)
   - Range: [0.1, 0.9]

6. **decay_bars**: Bars before decay exit allowed
   - Set to optimal horizon + 1-2 bars
   - Range: [1, 24]

7. **drop_return_max**: Max return for drop/scratch classification
   - Usually 0.0005 (0.05%) or slightly higher
   - Range: [0.0002, 0.002]

You must respond with ONLY valid JSON in this exact format:
{
  "entry_thresholds": {
    "trend_down": {"enabled": true,  "entry_min_conf": 0.52},
    "high_vol":   {"enabled": true,  "entry_min_conf": 0.58},
    "trend_up":   {"enabled": false, "entry_min_conf": 0.65},
    "chop":       {"enabled": false, "entry_min_conf": 0.75}
  },
  "exit_rules": {
    "trend_down": {
      "min_hold_bars": 2,
      "tp_return_min": 0.008,
      "sl_return": -0.012,
      "tp_conf_min": 0.65,
      "sl_conf_min": 0.30,
      "decay_bars": 6,
      "drop_return_max": 0.0005
    },
    "high_vol": {
      "min_hold_bars": 1,
      "tp_return_min": 0.012,
      "sl_return": -0.015,
      "tp_conf_min": 0.60,
      "sl_conf_min": 0.35,
      "decay_bars": 4,
      "drop_return_max": 0.0007
    },
    "chop": {
      "min_hold_bars": 2,
      "tp_return_min": 0.004,
      "sl_return": -0.006,
      "tp_conf_min": 0.75,
      "sl_conf_min": 0.40,
      "decay_bars": 3,
      "drop_return_max": 0.0005
    },
    "trend_up": {
      "min_hold_bars": 2,
      "tp_return_min": 0.007,
      "sl_return": -0.01,
      "tp_conf_min": 0.65,
      "sl_conf_min": 0.30,
      "decay_bars": 4,
      "drop_return_max": 0.0005
    }
  }
}

Do not include any explanation or markdown formatting - only the JSON object."""
    
    # Aggregate by regime for entry threshold tuning
    regime_stats = aggregate_by_regime(summary, min_count=20)
    
    # Aggregate by regime × horizon for exit rules tuning
    regime_horizon_stats = aggregate_by_regime_horizon(summary, min_count=20)
    
    # Build user message with band classification
    user_parts = [
        "## Current Entry Thresholds",
        json.dumps(current_thresholds, indent=2),
        "",
        "## Current Exit Rules",
        json.dumps(current_exit_rules, indent=2),
        "",
        "## Performance Summary by Regime (for Entry Thresholds)",
    ]
    
    for regime in ["trend_down", "high_vol", "trend_up", "chop"]:
        if regime in regime_stats:
            stats = regime_stats[regime]
            user_parts.append(f"\n### {regime}")
            user_parts.append(f"- Total bars: {stats['count']}")
            user_parts.append(f"- Wins/Losses: {stats['wins']}/{stats['losses']}")
            user_parts.append(f"- PF: {stats['pf']:.3f}")
            user_parts.append(f"- Current threshold: {current_thresholds.get(regime, 0.65):.2f}")
            
            # Classify bins by performance
            bins = sorted(stats["bins"], key=lambda b: b.get("conf_min", 0.0))
            good_bands = []
            meh_bands = []
            bad_bands = []
            
            for bin_data in bins:
                conf_min = bin_data["conf_min"]
                conf_max = bin_data["conf_max"]
                count = bin_data["count"]
                pf = bin_data["pf"]
                
                if count < 100:
                    continue  # Skip low sample size
                
                if pf >= 1.2:
                    good_bands.append((conf_min, conf_max, pf, count))
                elif pf >= 1.0:
                    meh_bands.append((conf_min, conf_max, pf, count))
                else:
                    bad_bands.append((conf_min, conf_max, pf, count))
            
            # Show classified bands
            if good_bands:
                user_parts.append(f"\n✅ GOOD bands (PF≥1.2, n≥100):")
                for conf_min, conf_max, pf, count in sorted(good_bands, key=lambda x: x[2], reverse=True):
                    user_parts.append(f"   [{conf_min:.2f}-{conf_max:.2f}): PF={pf:.3f}, n={count}")
                    user_parts.append(f"      → Suggested threshold: {conf_min - 0.02:.2f} (lower_edge - 0.02)")
            
            if meh_bands:
                user_parts.append(f"\n⚠️  MEH bands (1.0≤PF<1.2, n≥100):")
                for conf_min, conf_max, pf, count in sorted(meh_bands, key=lambda x: x[2], reverse=True)[:3]:
                    user_parts.append(f"   [{conf_min:.2f}-{conf_max:.2f}): PF={pf:.3f}, n={count}")
            
            if bad_bands:
                user_parts.append(f"\n❌ BAD bands (PF<1.0, n≥100): {len(bad_bands)} bands")
                # Show worst ones
                for conf_min, conf_max, pf, count in sorted(bad_bands, key=lambda x: x[2])[:3]:
                    user_parts.append(f"   [{conf_min:.2f}-{conf_max:.2f}): PF={pf:.3f}, n={count}")
            
            # Show all bins for reference (sorted by confidence)
            user_parts.append(f"\nAll confidence bins (sorted by conf_min):")
            for bin_data in bins:
                conf_min = bin_data["conf_min"]
                conf_max = bin_data["conf_max"]
                count = bin_data["count"]
                pf = bin_data["pf"]
                wins = bin_data["wins"]
                losses = bin_data["losses"]
                status = "GOOD" if pf >= 1.2 and count >= 100 else ("meh" if pf >= 1.0 and count >= 100 else ("BAD" if count >= 100 else "low_n"))
                user_parts.append(f"   [{conf_min:.2f}-{conf_max:.2f}): n={count}, wins={wins}, losses={losses}, PF={pf:.3f} [{status}]")
        else:
            user_parts.append(f"\n### {regime}")
            user_parts.append("- No data (or insufficient sample size)")
    
    # Add multi-horizon stats for exit rules tuning
    user_parts.append("\n\n## Performance Summary by Regime × Horizon (for Exit Rules)")
    for regime in ["trend_down", "high_vol", "trend_up", "chop"]:
        user_parts.append(f"\n### {regime}")
        if regime in regime_horizon_stats:
            horizon_dict = regime_horizon_stats[regime]
            for horizon in sorted(horizon_dict.keys()):
                stats = horizon_dict[horizon]
                pf = stats.get("pf", 0.0)
                mean_ret = stats.get("mean_ret", 0.0)
                count = stats.get("count", 0)
                win_rate = stats.get("win_rate", 0.0)
                avg_win = stats.get("avg_win", 0.0)
                avg_loss = stats.get("avg_loss", 0.0)
                p50 = stats.get("p50", 0.0)
                p75 = stats.get("p75", 0.0)
                p90 = stats.get("p90", 0.0)
                p95 = stats.get("p95", 0.0)
                p5 = stats.get("p5", 0.0)
                p95_ret = stats.get("p95_ret", 0.0)
                p5_ret = stats.get("p5_ret", 0.0)
                
                user_parts.append(f"\n  Horizon {horizon} bars:")
                user_parts.append(f"    - Count: {count}")
                user_parts.append(f"    - PF: {pf:.3f}")
                user_parts.append(f"    - Mean return: {mean_ret:.4f} ({mean_ret*100:.2f}%)")
                user_parts.append(f"    - Win rate: {stats.get('win_rate', 0.0):.2%}")
                user_parts.append(f"    - Avg win: {stats.get('avg_win', 0.0):.4f} ({stats.get('avg_win', 0.0)*100:.2f}%)")
                user_parts.append(f"    - Avg loss: {stats.get('avg_loss', 0.0):.4f} ({stats.get('avg_loss', 0.0)*100:.2f}%)")
                if p50 is not None:
                    user_parts.append(f"    - p50: {p50:.4f} ({p50*100:.2f}%)")
                    user_parts.append(f"    - p75: {p75:.4f} ({p75*100:.2f}%)")
                    user_parts.append(f"    - p90: {p90:.4f} ({p90*100:.2f}%)")
                    user_parts.append(f"    - p95: {stats.get('p95', 0.0):.4f} ({stats.get('p95', 0.0)*100:.2f}%)")
                    user_parts.append(f"    - p5: {stats.get('p5', 0.0):.4f} ({stats.get('p5', 0.0)*100:.2f}%)")
                    p95_ret = stats.get('p95_ret', 0.0)
                    p5_ret = stats.get('p5_ret', 0.0)
                    if p95_ret > 0:
                        user_parts.append(f"    - p95_ret (positive): {p95_ret:.4f} ({p95_ret*100:.2f}%)")
                    if p5_ret < 0:
                        user_parts.append(f"    - p5_ret (worst tail): {p5_ret:.4f} ({p5_ret*100:.2f}%)")
                
                # Suggest optimal exit parameters based on this horizon
                if pf >= 1.2 and count >= 50:
                    p95_ret = stats.get('p95_ret', p75 if p75 else 0.0)
                    p5_ret = stats.get('p5_ret', p50 if p50 else 0.0)
                    tp_suggestion = max(0.001, p95_ret * 0.8)  # Use 80% of p95 for TP
                    sl_suggestion = min(-0.002, p5_ret * 1.2)  # Use 120% of p5 for SL (wider)
                    user_parts.append(f"    → SUGGESTION: min_hold_bars={horizon}, tp_return_min≈{tp_suggestion:.4f}, sl_return≈{sl_suggestion:.4f}")
        else:
            user_parts.append("- No data (or insufficient sample size)")
    
    user_prompt = "\n".join(user_parts)
    
    return system_prompt, user_prompt


def call_gpt_api(system_prompt: str, user_prompt: str, model: str = "gpt-4o") -> str:
    """Call OpenAI API and return response content."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in the environment.")
    
    client = OpenAI(api_key=api_key)
    
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
    )
    
    return response.choices[0].message.content


def parse_gpt_response(response_text: str) -> Dict[str, Dict[str, Any]]:
    """Parse GPT response JSON, handling markdown code blocks if present."""
    text = response_text.strip()
    
    # Remove markdown code blocks if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Find first line that's not ``` or ```json
        start_idx = 1
        if lines[0].startswith("```json"):
            start_idx = 1
        # Find closing ```
        end_idx = len(lines) - 1
        if lines[-1].strip() == "```":
            end_idx = len(lines) - 1
        text = "\n".join(lines[start_idx:end_idx])
    
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"❌ Error parsing GPT response as JSON:")
        print(f"   {e}")
        print(f"\nRaw response:")
        print(response_text)
        raise


def main():
    parser = argparse.ArgumentParser(description="GPT-guided entry threshold tuning")
    parser.add_argument("--summary", default="reports/analysis/conf_ret_summary.json", help="Path to analysis summary JSON")
    parser.add_argument("--apply", action="store_true", help="Apply recommendations to config/entry_thresholds.json")
    parser.add_argument("--model", default="gpt-4o", help="OpenAI model to use")
    parser.add_argument("--dry-run", action="store_true", help="Alias for not applying (default)")
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("GPT Threshold Tuner")
    print("=" * 80)
    print(f"\n📋 Configuration:")
    print(f"   Summary:      {args.summary}")
    print(f"   Model:        {args.model}")
    print(f"   Apply:        {args.apply}")
    
    # Load summary
    print(f"\n📂 Loading summary...")
    summary_path = Path(args.summary)
    summary = load_summary(summary_path)
    print(f"   ✅ Loaded summary with {len(summary.get('bins', []))} bins")
    
    # Load current thresholds, regime enable flags, and exit rules
    current_thresholds = load_current_thresholds()
    current_regime_enable = load_regime_enable()
    current_exit_rules = load_exit_rules()
    
    print(f"\n📊 Current entry thresholds:")
    for regime, thr in sorted(current_thresholds.items()):
        print(f"   {regime:12s}: {thr:.2f}")
    
    print(f"\n📊 Current regime enable flags:")
    for regime, enabled in sorted(current_regime_enable.items()):
        status = "✅ enabled" if enabled else "❌ disabled"
        print(f"   {regime:12s}: {status}")
    
    print(f"\n📊 Current exit rules:")
    for regime in ["trend_down", "high_vol", "chop", "trend_up"]:
        if regime in current_exit_rules:
            params = current_exit_rules[regime]
            print(f"   {regime:12s}: min_hold={params.get('min_hold_bars', 1)}, tp={params.get('tp_return_min', 0.003):.4f}, sl={params.get('sl_return', -0.01):.4f}")
    
    # Build GPT prompt
    print(f"\n🤖 Building GPT prompt...")
    system_prompt, user_prompt = build_gpt_prompt(summary, current_thresholds, current_exit_rules)
    
    # Call GPT
    print(f"\n🤖 Calling GPT API ({args.model})...")
    try:
        response_text = call_gpt_api(system_prompt, user_prompt, model=args.model)
        recommendations = parse_gpt_response(response_text)
    except Exception as e:
        print(f"❌ Error calling GPT: {e}")
        return 1
    
    # Extract entry_thresholds and exit_rules from response
    entry_recommendations = recommendations.get("entry_thresholds", {})
    exit_recommendations = recommendations.get("exit_rules", {})
    
    # Validate entry threshold recommendations
    expected_regimes = ["trend_down", "high_vol", "trend_up", "chop"]
    for regime in expected_regimes:
        if regime not in entry_recommendations:
            print(f"⚠️  Warning: Missing regime '{regime}' in entry_thresholds")
            continue
        
        rec = entry_recommendations[regime]
        if "enabled" not in rec or "entry_min_conf" not in rec:
            print(f"⚠️  Warning: Invalid format for regime '{regime}'")
            continue
        
        conf = rec["entry_min_conf"]
        if not isinstance(conf, (int, float)):
            print(f"⚠️  Warning: Invalid threshold type for '{regime}': {conf}")
            continue
        # Hard clamp to [0.35, 0.85]
        if conf < 0.35:
            print(f"⚠️  Warning: Threshold for '{regime}' too low ({conf}), clamping to 0.35")
            rec["entry_min_conf"] = 0.35
        elif conf > 0.85:
            print(f"⚠️  Warning: Threshold for '{regime}' too high ({conf}), clamping to 0.85")
            rec["entry_min_conf"] = 0.85
    
    # Validate exit rules recommendations
    for regime in expected_regimes:
        if regime not in exit_recommendations:
            print(f"⚠️  Warning: Missing regime '{regime}' in exit_rules, using current values")
            continue
        
        rec = exit_recommendations[regime]
        # Validate and clamp each parameter
        rec["min_hold_bars"] = max(1, min(12, int(rec.get("min_hold_bars", DEFAULT_EXIT.min_hold_bars))))
        rec["tp_return_min"] = max(0.001, min(0.05, float(rec.get("tp_return_min", DEFAULT_EXIT.tp_return_min))))
        rec["sl_return"] = max(-0.05, min(-0.002, float(rec.get("sl_return", DEFAULT_EXIT.sl_return))))
        rec["tp_conf_min"] = max(0.4, min(0.9, float(rec.get("tp_conf_min", DEFAULT_EXIT.tp_conf_min))))
        rec["sl_conf_min"] = max(0.1, min(0.9, float(rec.get("sl_conf_min", DEFAULT_EXIT.sl_conf_min))))
        rec["decay_bars"] = max(1, min(24, int(rec.get("decay_bars", DEFAULT_EXIT.decay_bars))))
        rec["drop_return_max"] = max(0.0002, min(0.002, float(rec.get("drop_return_max", DEFAULT_EXIT.drop_return_max))))
    
    # Print entry threshold recommendations table
    print(f"\n" + "=" * 80)
    print("GPT Recommendations - Entry Thresholds")
    print("=" * 80)
    print(f"\n{'Regime':<12} {'Enabled':<8} {'OldThr':<8} {'NewThr':<8} {'OldEnable':<10} {'NewEnable':<10}")
    print("-" * 70)
    
    new_thresholds = {}
    new_regime_enable = {}
    
    for regime in expected_regimes:
        old_thr = current_thresholds.get(regime, 0.65)
        old_enabled = current_regime_enable.get(regime, REGIME_ENABLE_DEFAULT.get(regime, False))
        
        if regime in entry_recommendations:
            rec = entry_recommendations[regime]
            enabled = rec.get("enabled", old_enabled)
            enabled = bool(enabled)  # Ensure boolean
            new_thr = rec.get("entry_min_conf", old_thr)
            
            # Clamp threshold to sane range
            try:
                new_thr = float(new_thr)
            except (TypeError, ValueError):
                new_thr = old_thr
            
            if new_thr < 0.35:
                new_thr = 0.35
            if new_thr > 0.85:
                new_thr = 0.85
            
            new_thresholds[regime] = new_thr
            new_regime_enable[regime] = enabled
            
            enabled_str = "✅ true" if enabled else "❌ false"
            old_enabled_str = "✅" if old_enabled else "❌"
            print(f"{regime:<12} {enabled_str:<8} {old_thr:<8.2f} {new_thr:<8.2f} {old_enabled_str:<10} {enabled_str:<10}")
        else:
            new_thresholds[regime] = old_thr
            new_regime_enable[regime] = old_enabled
            old_enabled_str = "✅" if old_enabled else "❌"
            print(f"{regime:<12} {'true':<8} {old_thr:<8.2f} {old_thr:<8.2f} {old_enabled_str:<10} {old_enabled_str:<10} (unchanged)")
    
    # Print exit rules recommendations table
    print(f"\n" + "=" * 80)
    print("GPT Recommendations - Exit Rules")
    print("=" * 80)
    print(f"\n{'Regime':<12} {'min_hold':<8} {'tp_min':<8} {'sl':<8} {'tp_conf':<8} {'decay':<8}")
    print("-" * 70)
    
    new_exit_rules = {}
    for regime in expected_regimes:
        old_params = current_exit_rules.get(regime, current_exit_rules.get("default", {}))
        
        if regime in exit_recommendations:
            new_params = exit_recommendations[regime]
            new_exit_rules[regime] = new_params
            
            print(f"{regime:<12} {new_params.get('min_hold_bars', 1):<8} "
                  f"{new_params.get('tp_return_min', 0.003):<8.4f} "
                  f"{new_params.get('sl_return', -0.01):<8.4f} "
                  f"{new_params.get('tp_conf_min', 0.65):<8.2f} "
                  f"{new_params.get('decay_bars', 6):<8}")
        else:
            new_exit_rules[regime] = old_params
            print(f"{regime:<12} {old_params.get('min_hold_bars', 1):<8} "
                  f"{old_params.get('tp_return_min', 0.003):<8.4f} "
                  f"{old_params.get('sl_return', -0.01):<8.4f} "
                  f"{old_params.get('tp_conf_min', 0.65):<8.2f} "
                  f"{old_params.get('decay_bars', 6):<8} (unchanged)")
    
    # Apply if requested
    if args.apply:
        print(f"\n💾 Applying recommendations...")
        
        # Save entry thresholds
        save_entry_thresholds(new_thresholds)
        threshold_path = CONFIG / "entry_thresholds.json"
        print(f"   ✅ Updated entry thresholds written to {threshold_path}")
        
        # Save regime enable flags
        save_regime_enable(new_regime_enable)
        enable_path = CONFIG / "regime_enable.json"
        print(f"   ✅ Updated regime enable flags written to {enable_path}")
        
        # Save exit rules
        save_exit_rules(new_exit_rules)
        exit_rules_path = CONFIG / "exit_rules.json"
        print(f"   ✅ Updated exit rules written to {exit_rules_path}")
        
        print(f"\n💡 Next steps:")
        print(f"   1. Review the new thresholds, enable flags, and exit rules above")
        print(f"   2. Restart Chloe service: sudo systemctl restart chloe.service")
        print(f"   3. Monitor: python3 -m tools.chloe_checkin")
        print(f"   4. Check PF: python3 -m tools.pf_doctor_filtered --threshold 0.0005 --reasons tp,sl")
    else:
        print(f"\n💡 Dry run complete - no changes applied")
        print(f"   Run with --apply to write updated thresholds and regime enable flags")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

