"""
Weighted GPT Tuner - Hybrid Self-Learning Mode

Uses weighted analyzer stats to update thresholds with guardrails.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, Optional

ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"
REPORTS_DIR = ROOT_DIR / "reports"
RESEARCH_DIR = REPORTS_DIR / "research"
RESEARCH_ROOT = RESEARCH_DIR

THRESHOLDS_PATH = CONFIG_DIR / "entry_thresholds.json"
REGIME_THRESHOLDS_PATH = CONFIG_DIR / "regime_thresholds.json"
REGIME_ENABLE_PATH = CONFIG_DIR / "regime_enable.json"
ANALYZER_OUT_PATH = RESEARCH_DIR / "multi_horizon_stats.json"
CONF_MAP_PATH = CONFIG_DIR / "confidence_map.json"
STRENGTH_PATH = RESEARCH_DIR / "strategy_strength.json"

from engine_alpha.tools.weighted_analyzer import load_weights_config


def _symbol_research_dir(symbol: str) -> Path:
    """Get per-symbol research directory."""
    d = RESEARCH_ROOT / symbol
    d.mkdir(parents=True, exist_ok=True)
    return d


def _strategy_strength_path(symbol: str) -> Path:
    """Get per-symbol strategy strength path."""
    return _symbol_research_dir(symbol) / "strategy_strength.json"


def _confidence_map_path(symbol: str) -> Path:
    """Get per-symbol confidence map path."""
    return _symbol_research_dir(symbol) / "confidence_map.json"


def _regime_thresholds_path(symbol: str) -> Path:
    """Get per-symbol regime thresholds path."""
    return _symbol_research_dir(symbol) / "regime_thresholds.json"


def _load_analyzer_stats(path: Path) -> Dict[str, Any]:
    """Load analyzer output."""
    if not path.exists():
        return {}
    with path.open("r") as f:
        return json.load(f)


def _load_current_thresholds(path: Path = THRESHOLDS_PATH) -> Dict[str, float]:
    """Load current entry thresholds."""
    if not path.exists():
        return {
            "trend_down": 0.50,
            "high_vol": 0.55,
            "trend_up": 0.60,
            "chop": 0.65,
        }
    with path.open("r") as f:
        return json.load(f)


def _bounded_step(old: float, target: float, max_step: float) -> float:
    """Apply bounded step to threshold update."""
    delta = target - old
    if abs(delta) <= max_step:
        return target
    return old + max_step * (1 if delta > 0 else -1)


def run_gpt_tuner(
    analyzer_path: Path = ANALYZER_OUT_PATH,
    thresholds_path: Path = THRESHOLDS_PATH,
    symbol: Optional[str] = None,
) -> Path:
    """
    Use weighted analyzer stats to update regime thresholds with guardrails.
    """
    if symbol:
        return run_gpt_tuner_for_symbol(symbol, analyzer_path)
    weights_cfg = load_weights_config()
    stats = _load_analyzer_stats(analyzer_path)
    
    if not stats:
        print("⚠️  No analyzer stats found, skipping tuning")
        return thresholds_path
    
    cur = _load_current_thresholds(thresholds_path)

    # Choose horizon to optimize for (e.g. main trading horizon)
    target_horizon = "ret_4h" if "ret_4h" in stats else list(stats.keys())[0]
    horizon_stats = stats[target_horizon]["stats"]

    updated = cur.copy()

    # Aggregate stats by regime (across all confidence buckets)
    regime_stats: Dict[str, Dict[str, Any]] = {}
    
    for key, s in horizon_stats.items():
        regime, bucket_str = key.split("|")
        bucket = int(bucket_str)
        
        if regime not in regime_stats:
            regime_stats[regime] = {
                "total_count": 0,
                "total_weighted_count": 0.0,
                "weighted_mean": 0.0,
                "weight_sum": 0.0,
            }
        
        count = s.get("count", 0)
        wcount = s.get("weighted_count", 0.0)
        mean = s.get("mean", 0.0)
        
        # Aggregate weighted mean
        regime_stats[regime]["total_count"] += count
        regime_stats[regime]["total_weighted_count"] += wcount
        regime_stats[regime]["weight_sum"] += wcount
        regime_stats[regime]["weighted_mean"] += mean * wcount

    # Normalize weighted means
    for regime in regime_stats:
        wsum = regime_stats[regime]["weight_sum"]
        if wsum > 0:
            regime_stats[regime]["weighted_mean"] /= wsum
        else:
            regime_stats[regime]["weighted_mean"] = 0.0

    # Update thresholds based on regime-level stats
    for regime, rstats in regime_stats.items():
        count = rstats["total_count"]
        wcount = rstats["total_weighted_count"]
        edge = rstats["weighted_mean"]

        # Enforce min sample sizes
        if count < weights_cfg.min_trades_per_regime or wcount < weights_cfg.min_weighted_trades_per_regime:
            # Not enough data, don't loosen anything
            continue

        old_thr = float(updated.get(regime, 0.5))

        # If expectancy is clearly negative, move threshold *up* (fewer trades)
        if edge < -weights_cfg.min_expectancy_edge:
            target_thr = min(1.0, old_thr + 0.1)  # desire: trade less in bad regime
            new_thr = _bounded_step(old_thr, target_thr, weights_cfg.max_threshold_step_per_night)
            updated[regime] = new_thr
            print(f"  {regime}: {old_thr:.2f} → {new_thr:.2f} (tightened, edge={edge:.5f})")

        # If expectancy is clearly positive, we can lower threshold a bit (more trades)
        elif edge > weights_cfg.min_expectancy_edge:
            target_thr = max(0.1, old_thr - 0.05)  # desire: trade more in good regime
            new_thr = _bounded_step(old_thr, target_thr, weights_cfg.max_threshold_step_per_night)
            updated[regime] = new_thr
            print(f"  {regime}: {old_thr:.2f} → {new_thr:.2f} (loosened, edge={edge:.5f})")

        # If edge is ~flat, do nothing (let history accumulate)

    # Write entry_thresholds.json (simple format for backward compatibility)
    thresholds_path.parent.mkdir(parents=True, exist_ok=True)
    with thresholds_path.open("w") as f:
        json.dump(updated, f, indent=2)

    # Write regime_thresholds.json (rich format with enabled flags)
    regime_thresholds: Dict[str, Dict[str, Any]] = {}
    regime_enable: Dict[str, bool] = {}
    
    for regime, rstats in regime_stats.items():
        count = rstats["total_count"]
        wcount = rstats["total_weighted_count"]
        edge = rstats["weighted_mean"]
        entry_min_conf = updated.get(regime, 0.5)
        
        # Determine if regime should be enabled
        # Enable if: sufficient samples AND positive edge OR neutral edge with good samples
        enabled = (
            count >= weights_cfg.min_trades_per_regime
            and wcount >= weights_cfg.min_weighted_trades_per_regime
            and edge >= -weights_cfg.min_expectancy_edge  # Allow neutral or positive
        )
        
        # Build notes
        if not enabled:
            if count < weights_cfg.min_trades_per_regime:
                notes = f"Insufficient samples ({count} < {weights_cfg.min_trades_per_regime})"
            elif wcount < weights_cfg.min_weighted_trades_per_regime:
                notes = f"Insufficient weighted samples ({wcount:.1f} < {weights_cfg.min_weighted_trades_per_regime})"
            elif edge < -weights_cfg.min_expectancy_edge:
                notes = f"Negative edge ({edge:.5f})"
            else:
                notes = "Disabled by tuner"
        else:
            if edge > weights_cfg.min_expectancy_edge:
                notes = f"Good positive edge ({edge:.5f})"
            else:
                notes = f"Neutral edge ({edge:.5f}), enabled for observation"
        
        regime_thresholds[regime] = {
            "enabled": enabled,
            "entry_min_conf": float(entry_min_conf),
            "notes": notes,
        }
        regime_enable[regime] = enabled
    
    # Ensure all regimes are present
    for regime in ["trend_down", "trend_up", "high_vol", "chop"]:
        if regime not in regime_thresholds:
            regime_thresholds[regime] = {
                "enabled": False,
                "entry_min_conf": updated.get(regime, 0.5),
                "notes": "No data available",
            }
            regime_enable[regime] = False
    
    # Write regime_thresholds.json
    REGIME_THRESHOLDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REGIME_THRESHOLDS_PATH.open("w") as f:
        json.dump(regime_thresholds, f, indent=2)
    print(f"✅ Regime thresholds written to {REGIME_THRESHOLDS_PATH}")
    
    # Write regime_enable.json (for backward compatibility)
    with REGIME_ENABLE_PATH.open("w") as f:
        json.dump(regime_enable, f, indent=2)
    print(f"✅ Regime enable flags written to {REGIME_ENABLE_PATH}")

    # Generate confidence_map.json and strategy_strength.json
    _generate_confidence_map(stats, target_horizon)
    _generate_strategy_strength(stats, target_horizon, regime_stats)

    return REGIME_THRESHOLDS_PATH


def _generate_confidence_map(stats: Dict[str, Any], horizon: str) -> None:
    """Generate confidence_map.json from analyzer stats."""
    if horizon not in stats or "stats" not in stats[horizon]:
        return
    
    horizon_stats = stats[horizon]["stats"]
    
    # Aggregate by confidence bucket (0-9) across all regimes
    bucket_stats: Dict[int, Dict[str, Any]] = {}
    
    for key, s in horizon_stats.items():
        regime, bucket_str = key.split("|")
        bucket = int(bucket_str)
        
        if bucket not in bucket_stats:
            bucket_stats[bucket] = {
                "count": 0,
                "weighted_count": 0.0,
                "weighted_mean": 0.0,
                "weight_sum": 0.0,
            }
        
        count = s.get("count", 0)
        wcount = s.get("weighted_count", 0.0)
        mean = s.get("mean", 0.0)
        
        bucket_stats[bucket]["count"] += count
        bucket_stats[bucket]["weighted_count"] += wcount
        bucket_stats[bucket]["weight_sum"] += wcount
        bucket_stats[bucket]["weighted_mean"] += mean * wcount
    
    # Normalize weighted means
    for bucket in bucket_stats:
        wsum = bucket_stats[bucket]["weight_sum"]
        if wsum > 0:
            bucket_stats[bucket]["weighted_mean"] /= wsum
        else:
            bucket_stats[bucket]["weighted_mean"] = 0.0
    
    # Build confidence map (0-9 buckets)
    conf_map = {}
    for bucket in range(10):
        if bucket in bucket_stats:
            bstats = bucket_stats[bucket]
            mean_val = bstats["weighted_mean"]
            # Handle NaN/Inf
            if not isinstance(mean_val, (int, float)) or (isinstance(mean_val, float) and (mean_val != mean_val or abs(mean_val) == float('inf'))):
                mean_val = 0.0
            conf_map[str(bucket)] = {
                "expected_return": float(mean_val),
                "count": int(bstats["count"]),
            }
        else:
            conf_map[str(bucket)] = {
                "expected_return": 0.0,
                "count": 0,
            }
    
    CONF_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONF_MAP_PATH.open("w") as f:
        json.dump(conf_map, f, indent=2)
    
    print(f"✅ Confidence map written to {CONF_MAP_PATH}")


def _generate_strategy_strength(
    stats: Dict[str, Any],
    horizon: str,
    regime_stats: Dict[str, Dict[str, Any]],
) -> None:
    """Generate strategy_strength.json from analyzer stats."""
    if horizon not in stats or "stats" not in stats[horizon]:
        return
    
    horizon_stats = stats[horizon]["stats"]
    
    # Compute win rate and hit rate per regime
    strength_map = {}
    
    for regime, rstats in regime_stats.items():
        total_count = rstats["total_count"]
        wcount = rstats["total_weighted_count"]
        edge = rstats["weighted_mean"]
        
        # Compute win rate from horizon stats
        wins = 0
        losses = 0
        for key, s in horizon_stats.items():
            if key.startswith(f"{regime}|"):
                wins += s.get("wins", 0)
                losses += s.get("losses", 0)
        
        win_rate = wins / (wins + losses) if (wins + losses) > 0 else 0.0
        
        # Strength is a combination of edge and win rate
        strength = (edge * 0.7) + (win_rate * 0.3) if wcount > 0 else 0.0
        
        # Handle NaN/Inf
        def safe_float(v):
            if not isinstance(v, (int, float)) or (isinstance(v, float) and (v != v or abs(v) == float('inf'))):
                return 0.0
            return float(v)
        
        strength_map[regime] = {
            "strength": safe_float(strength),
            "edge": safe_float(edge),
            "hit_rate": safe_float(win_rate),
            "weighted_count": safe_float(wcount),
        }
    
    # Ensure all regimes are present (even if zero)
    for regime in ["trend_down", "trend_up", "high_vol", "chop"]:
        if regime not in strength_map:
            strength_map[regime] = {
                "strength": 0.0,
                "edge": 0.0,
                "hit_rate": 0.0,
                "weighted_count": 0.0,
            }
    
    STRENGTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STRENGTH_PATH.open("w") as f:
        json.dump(strength_map, f, indent=2)
    
    print(f"✅ Strategy strength written to {STRENGTH_PATH}")


def run_gpt_tuner_for_symbol(
    symbol: str,
    stats_path: Path,
) -> Path:
    """
    Use analyzer stats to update per-symbol thresholds/confidence_map/strategy_strength.
    
    For now, we use a simple, deterministic heuristic instead of GPT:
      - If edge < -min_expectancy_edge: raise threshold, maybe disable.
      - If edge > +min_expectancy_edge: lower threshold, enable.
    """
    weights_cfg = load_weights_config()
    stats = _load_analyzer_stats(stats_path)
    
    if not stats:
        print(f"⚠️  No analyzer stats found for {symbol}, skipping tuning")
        return _regime_thresholds_path(symbol)
    
    # Load global thresholds (for backward compatibility)
    # Per-symbol thresholds will be stored under symbol dir
    cur = _load_current_thresholds()
    
    # Pick a horizon to optimize (e.g., ret_4h)
    if "ret_4h" in stats:
        horizon_key = "ret_4h"
    else:
        horizon_key = list(stats.keys())[0]
    
    horizon_stats = stats[horizon_key]["stats"]
    min_expectancy_edge = weights_cfg.min_expectancy_edge
    
    # Aggregate by regime
    regimes: Dict[str, Dict[str, Any]] = {}
    
    for key, s in horizon_stats.items():
        regime, bucket_str = key.split("|")
        edge = float(s.get("mean", 0.0))
        wN = float(s.get("weighted_count", 0.0))
        
        reg = regimes.setdefault(regime, {"edges": [], "weights": []})
        reg["edges"].append(edge)
        reg["weights"].append(wN)
    
    # Build per-symbol regime thresholds
    sym_thr: Dict[str, Dict[str, Any]] = {}
    
    for regime, agg in regimes.items():
        edges = agg["edges"]
        weights = agg["weights"]
        if not edges or sum(weights) <= 0:
            continue
        
        total_w = sum(weights)
        avg_edge = sum(e * w for e, w in zip(edges, weights)) / total_w
        
        # Get current threshold (from global or per-symbol)
        old_thr = float(cur.get(regime, 0.5))
        
        cfg: Dict[str, Any] = {
            "enabled": True,
            "entry_min_conf": old_thr,
            "notes": "",
        }
        
        # Check sample size
        total_count = sum(s.get("count", 0) for k, s in horizon_stats.items() if k.startswith(f"{regime}|"))
        
        if total_count < weights_cfg.min_trades_per_regime or total_w < weights_cfg.min_weighted_trades_per_regime:
            cfg["notes"] = f"Insufficient samples ({total_count} trades, {total_w:.1f} weighted)"
            cfg["enabled"] = False
        elif avg_edge < -min_expectancy_edge:
            # Weakening regime: tighten
            new_thr = min(0.95, old_thr + weights_cfg.max_threshold_step_per_night)
            cfg["entry_min_conf"] = new_thr
            if new_thr > 0.85:
                cfg["enabled"] = False
                cfg["notes"] = f"Disabled by tuner; negative expectancy (edge={avg_edge:.5f})"
            else:
                cfg["notes"] = f"Weakened by tuner; negative expectancy (edge={avg_edge:.5f})"
        elif avg_edge > min_expectancy_edge:
            # Strengthening regime: loosen
            new_thr = max(0.1, old_thr - weights_cfg.max_threshold_step_per_night)
            cfg["entry_min_conf"] = new_thr
            cfg["enabled"] = True
            cfg["notes"] = f"Strengthened by tuner; positive expectancy (edge={avg_edge:.5f})"
        else:
            # Near zero edge, leave it alone
            cfg["notes"] = f"Neutral expectation (edge={avg_edge:.5f})"
        
        sym_thr[regime] = cfg
    
    # Ensure all regimes are present
    for regime in ["trend_down", "trend_up", "high_vol", "chop"]:
        if regime not in sym_thr:
            sym_thr[regime] = {
                "enabled": False,
                "entry_min_conf": cur.get(regime, 0.5),
                "notes": "No data available",
            }
    
    # Write per-symbol regime thresholds
    thr_path = _regime_thresholds_path(symbol)
    thr_path.parent.mkdir(parents=True, exist_ok=True)
    with thr_path.open("w") as f:
        json.dump(sym_thr, f, indent=2)
    
    # Generate per-symbol confidence_map and strategy_strength
    _generate_confidence_map_for_symbol(symbol, stats, horizon_key)
    _generate_strategy_strength_for_symbol(symbol, stats, horizon_key, regimes)
    
    return thr_path


def _generate_confidence_map_for_symbol(symbol: str, stats: Dict[str, Any], horizon: str) -> None:
    """Generate per-symbol confidence_map.json from analyzer stats."""
    if horizon not in stats or "stats" not in stats[horizon]:
        return
    
    horizon_stats = stats[horizon]["stats"]
    
    # Aggregate by confidence bucket (0-9) across all regimes
    bucket_stats: Dict[int, Dict[str, Any]] = {}
    
    for key, s in horizon_stats.items():
        regime, bucket_str = key.split("|")
        bucket = int(bucket_str)
        
        if bucket not in bucket_stats:
            bucket_stats[bucket] = {
                "count": 0,
                "weighted_count": 0.0,
                "weighted_mean": 0.0,
                "weight_sum": 0.0,
            }
        
        count = s.get("count", 0)
        wcount = s.get("weighted_count", 0.0)
        mean = s.get("mean", 0.0)
        
        bucket_stats[bucket]["count"] += count
        bucket_stats[bucket]["weighted_count"] += wcount
        bucket_stats[bucket]["weight_sum"] += wcount
        bucket_stats[bucket]["weighted_mean"] += mean * wcount
    
    # Normalize weighted means
    for bucket in bucket_stats:
        wsum = bucket_stats[bucket]["weight_sum"]
        if wsum > 0:
            bucket_stats[bucket]["weighted_mean"] /= wsum
        else:
            bucket_stats[bucket]["weighted_mean"] = 0.0
    
    # Build confidence map (0-9 buckets)
    conf_map = {}
    for bucket in range(10):
        if bucket in bucket_stats:
            bstats = bucket_stats[bucket]
            mean_val = bstats["weighted_mean"]
            # Handle NaN/Inf
            if not isinstance(mean_val, (int, float)) or (isinstance(mean_val, float) and (mean_val != mean_val or abs(mean_val) == float('inf'))):
                mean_val = 0.0
            conf_map[str(bucket)] = {
                "expected_return": float(mean_val),
                "count": int(bstats["count"]),
            }
        else:
            conf_map[str(bucket)] = {
                "expected_return": 0.0,
                "count": 0,
            }
    
    conf_path = _confidence_map_path(symbol)
    conf_path.parent.mkdir(parents=True, exist_ok=True)
    with conf_path.open("w") as f:
        json.dump(conf_map, f, indent=2)


def _generate_strategy_strength_for_symbol(
    symbol: str,
    stats: Dict[str, Any],
    horizon: str,
    regime_stats: Dict[str, Dict[str, Any]],
) -> None:
    """Generate per-symbol strategy_strength.json from analyzer stats."""
    if horizon not in stats or "stats" not in stats[horizon]:
        return
    
    horizon_stats = stats[horizon]["stats"]
    
    # Compute strength per regime
    strength_map = {}
    
    for regime, agg in regime_stats.items():
        edges = agg["edges"]
        weights = agg["weights"]
        if not edges or sum(weights) <= 0:
            continue
        
        total_w = sum(weights)
        edge = sum(e * w for e, w in zip(edges, weights)) / total_w
        
        # Compute hit rate from horizon stats
        hits = 0
        total = 0
        for key, s in horizon_stats.items():
            if key.startswith(f"{regime}|"):
                hits += s.get("hit_rate", 0.0) * s.get("weighted_count", 0.0)
                total += s.get("weighted_count", 0.0)
        
        hit_rate = hits / total if total > 0 else 0.0
        
        # Strength is a combination of edge and hit rate
        strength = (edge * 0.7) + (hit_rate * 0.3) if total_w > 0 else 0.0
        
        # Handle NaN/Inf
        def safe_float(v):
            if not isinstance(v, (int, float)) or (isinstance(v, float) and (v != v or abs(v) == float('inf'))):
                return 0.0
            return float(v)
        
        strength_map[regime] = {
            "strength": safe_float(strength),
            "edge": safe_float(edge),
            "hit_rate": safe_float(hit_rate),
            "weighted_count": safe_float(total_w),
        }
    
    # Ensure all regimes are present (even if zero)
    for regime in ["trend_down", "trend_up", "high_vol", "chop"]:
        if regime not in strength_map:
            strength_map[regime] = {
                "strength": 0.0,
                "edge": 0.0,
                "hit_rate": 0.0,
                "weighted_count": 0.0,
            }
    
    strength_path = _strategy_strength_path(symbol)
    strength_path.parent.mkdir(parents=True, exist_ok=True)
    with strength_path.open("w") as f:
        json.dump(strength_map, f, indent=2)


if __name__ == "__main__":
    out = run_gpt_tuner()
    print(f"✅ Updated thresholds written to {out}")

