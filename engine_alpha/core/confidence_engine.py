"""
Confidence engine - Phase 2
Computes bucket scores and council-aggregated confidence.
"""

import json
import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional

from engine_alpha.core.regime import RegimeClassifier, get_regime


# Signal to bucket mapping
# Each signal contributes to one or more buckets
SIGNAL_BUCKETS = {
    "Ret_G5": ["momentum"],
    "RSI_14": ["momentum", "meanrev"],
    "MACD_Hist": ["momentum"],
    "VWAP_Dist": ["meanrev"],
    "ATRp": ["flow"],
    "BB_Width": ["flow"],
    "Vol_Delta": ["flow"],
    "Funding_Bias": ["positioning"],
    "OI_Beta": ["positioning"],
    "Session_Heat": ["flow"],
    "Event_Cooldown": ["timing"],
    "Spread_Normalized": ["timing"],
}

# Phase 55: Regime-specific bucket masking (PAPER only)
# Defines which buckets are allowed to vote in each regime
# Buckets not in the mask are excluded from council aggregation
# Weights are renormalized over only the active buckets
# None = use all buckets (no masking)
REGIME_BUCKET_MASK = {
    # Trend up/down: emphasize momentum, positioning, flow (exclude meanrev counter-trend, timing less critical)
    "trend_up": ["momentum", "positioning", "flow"],
    "trend_down": ["momentum", "positioning", "flow"],  # Exclude meanrev (counter-trend)
    # Panic down: very strict - only trend-followers (momentum + positioning)
    # Flow can be contradictory in panic moves (unpredictable)
    "panic_down": ["momentum", "positioning"],
    # High vol: allow broad voting (None = use all buckets)
    "high_vol": None,
    # Chop: mean-reversion, timing, some flow (exclude momentum trend-chasing, positioning less relevant)
    "chop": ["meanrev", "timing", "flow"],
    # Fallback for legacy "trend" regime
    "trend": ["momentum", "positioning", "flow"],
}
# Note: sentiment and onchain_flow are not included in masks yet (they have 0 weight anyway)

# Council weights by regime
# Loaded from engine_alpha/config/council_weights.yaml if available, otherwise use hardcoded defaults
# 
# LEARNING EXPERIMENTS (Phase 50):
# - Supports COUNCIL_WEIGHTS_FILE env var for backtest experiments
# - When set, loads weights from the specified file (used by council_weight_learner.py)
# - Live trading always uses engine_alpha/config/council_weights.yaml (or defaults)
# - This allows offline learning experiments without affecting live trading
_COUNCIL_WEIGHTS_DEFAULT = {
    "trend": {
        "momentum": 0.40,
        "meanrev": 0.10,
        "flow": 0.25,
        "positioning": 0.15,
        "timing": 0.10,
    },
    "chop": {
        "momentum": 0.15,
        "meanrev": 0.30,
        "flow": 0.30,
        "positioning": 0.10,
        "timing": 0.15,
    },
    "high_vol": {
        "momentum": 0.25,
        "meanrev": 0.10,
        "flow": 0.40,
        "positioning": 0.10,
        "timing": 0.15,
    },
}


def _load_council_weights(use_mutated_weights: Optional[str] = None) -> Dict[str, Dict[str, float]]:
    """
    Load council weights from YAML config file.
    Falls back to hardcoded defaults if file doesn't exist or is invalid.
    
    Safety: This is read-only. No live trading logic changes.
    
    Supports:
    - use_mutated_weights parameter (backtest only): path to mutated weights YAML
    - COUNCIL_WEIGHTS_FILE env var for learning experiments (backtest only)
    - Default: config/council_weights.yaml (or engine_alpha/config/council_weights.yaml)
    
    IMPORTANT: use_mutated_weights is ONLY used in backtests. Live trading ALWAYS uses defaults.
    """
    import os
    
    # Priority 1: use_mutated_weights parameter (backtest only)
    if use_mutated_weights:
        mutated_path = Path(use_mutated_weights)
        if mutated_path.exists():
            weights_path = mutated_path
        else:
            # Fall back to default if mutated file doesn't exist
            weights_path = Path(__file__).parent.parent.parent / "config" / "council_weights.yaml"
    # Priority 2: COUNCIL_WEIGHTS_FILE env var (backtest only)
    elif os.getenv("COUNCIL_WEIGHTS_FILE"):
        learning_weights_file = os.getenv("COUNCIL_WEIGHTS_FILE")
        learning_path = Path(learning_weights_file)
        if learning_path.exists():
            weights_path = learning_path
        else:
            weights_path = Path(__file__).parent.parent.parent / "config" / "council_weights.yaml"
    # Priority 3: Default config file
    else:
        # Try root config/ first, then engine_alpha/config/
        root_config = Path(__file__).parent.parent.parent / "config" / "council_weights.yaml"
        engine_config = Path(__file__).parent.parent / "config" / "council_weights.yaml"
        if root_config.exists():
            weights_path = root_config
        elif engine_config.exists():
            weights_path = engine_config
        else:
            return _COUNCIL_WEIGHTS_DEFAULT.copy()
    
    if not weights_path.exists():
        return _COUNCIL_WEIGHTS_DEFAULT.copy()
    
    try:
        with open(weights_path, "r") as f:
            data = yaml.safe_load(f) or {}
        weights = data.get("council_weights", {})
        if not weights:
            return _COUNCIL_WEIGHTS_DEFAULT.copy()
        
        # Validate structure and normalize
        result = {}
        for regime in ["trend", "chop", "high_vol"]:
            regime_weights = weights.get(regime, {})
            if regime_weights:
                result[regime] = {
                    "momentum": float(regime_weights.get("momentum", 0.0)),
                    "meanrev": float(regime_weights.get("meanrev", 0.0)),
                    "flow": float(regime_weights.get("flow", 0.0)),
                    "positioning": float(regime_weights.get("positioning", 0.0)),
                    "timing": float(regime_weights.get("timing", 0.0)),
                }
            else:
                result[regime] = _COUNCIL_WEIGHTS_DEFAULT[regime].copy()
        
        return result
    except Exception:
        # On any error, fall back to defaults
        return _COUNCIL_WEIGHTS_DEFAULT.copy()


# Load council weights (with fallback to defaults)
# Note: This is loaded at module import time. For backtest experiments,
# use COUNCIL_WEIGHTS_FILE env var or reload via _load_council_weights()
COUNCIL_WEIGHTS = _load_council_weights()

# Direction threshold
DIR_THRESHOLD = 0.05


def _load_signal_registry() -> Dict[str, Any]:
    """Load signal registry to get signal weights."""
    registry_path = Path(__file__).parent.parent / "signals" / "signal_registry.json"
    if not registry_path.exists():
        raise FileNotFoundError(f"Signal registry not found: {registry_path}")
    
    with open(registry_path, "r") as f:
        return json.load(f)


def _load_gates_config() -> Dict[str, Any]:
    """Load gates configuration."""
    gates_path = Path(__file__).parent.parent / "config" / "gates.yaml"
    if not gates_path.exists():
        # Return defaults if file doesn't exist
        return {
            "entry_exit": {
                "entry_min_conf": {
                    "trend": 0.70,
                    "chop": 0.72,
                    "high_vol": 0.71,
                },
                "exit_min_conf": 0.30,
                "reverse_min_conf": 0.60,
            }
        }
    
    with open(gates_path, "r") as f:
        return yaml.safe_load(f)


def _compute_bucket_scores(signal_vector: List[float], raw_registry: Dict[str, Any],
                           signal_registry: Dict[str, Any]) -> Dict[str, float]:
    """
    Compute bucket scores: score_i = Σ w_ij * s_j
    
    Args:
        signal_vector: Normalized signal vector
        raw_registry: Raw signal registry
        signal_registry: Signal registry configuration
    
    Returns:
        Dictionary mapping bucket names to scores
    """
    # Create signal name to index mapping
    signals_list = signal_registry.get("signals", [])
    signal_name_to_index = {sig["name"]: i for i, sig in enumerate(signals_list)}
    
    # Initialize bucket scores
    # Phase 54: Reserve slots for sentiment and on-chain buckets (disabled by default, no live data yet)
    bucket_scores = {
        "momentum": 0.0,
        "meanrev": 0.0,
        "flow": 0.0,
        "positioning": 0.0,
        "timing": 0.0,
        "sentiment": 0.0,      # Reserved for future: NLP-derived sentiment score from Twitter/News/Reddit
        "onchain_flow": 0.0,   # Reserved for future: On-chain whale / L2 / staking flow anomalies
    }
    
    # Compute scores for each bucket
    for signal_name, buckets in SIGNAL_BUCKETS.items():
        # Get signal index
        signal_idx = signal_name_to_index.get(signal_name)
        if signal_idx is None or signal_idx >= len(signal_vector):
            continue
        
        # Get signal value (normalized)
        signal_value = signal_vector[signal_idx]
        
        # Get signal weight from registry
        signal_config = next((s for s in signals_list if s["name"] == signal_name), None)
        if signal_config is None:
            continue
        
        weight = signal_config.get("weight", 1.0)
        
        # Add weighted signal to each bucket it belongs to
        for bucket in buckets:
            bucket_scores[bucket] += weight * signal_value
    
    return bucket_scores


def _compute_bucket_directions(bucket_scores: Dict[str, float]) -> Dict[str, int]:
    """
    Compute bucket directions: dir_i = sign(score_i) with threshold ε=0.05
    
    Args:
        bucket_scores: Dictionary mapping bucket names to scores
    
    Returns:
        Dictionary mapping bucket names to directions (-1, 0, or +1)
    """
    bucket_dirs = {}
    for bucket, score in bucket_scores.items():
        if abs(score) < DIR_THRESHOLD:
            bucket_dirs[bucket] = 0
        else:
            bucket_dirs[bucket] = 1 if score > 0 else -1
    
    return bucket_dirs


def _compute_bucket_confidences(bucket_scores: Dict[str, float]) -> Dict[str, float]:
    """
    Compute bucket confidences: conf_i = clip(|score_i|, 0, 1)
    
    Args:
        bucket_scores: Dictionary mapping bucket names to scores
    
    Returns:
        Dictionary mapping bucket names to confidences [0, 1]
    """
    bucket_confs = {}
    for bucket, score in bucket_scores.items():
        bucket_confs[bucket] = max(0.0, min(1.0, abs(score)))
    
    return bucket_confs


def apply_bucket_mask(weights: Dict[str, float], regime: str, is_paper_mode: bool = False,
                      bucket_dirs: Optional[Dict[str, int]] = None) -> Dict[str, float]:
    """
    Phase 55: Apply regime-specific bucket mask and renormalize weights.
    Phase 55.2: In trend regimes, filter flow bucket by direction (only include if flow agrees with trend).
    
    Args:
        weights: Base weights dictionary
        regime: Market regime
        is_paper_mode: Whether running in PAPER mode (mask only applied in PAPER)
        bucket_dirs: Optional bucket directions dict for Phase 55.2 direction filtering
    
    Returns:
        Masked and renormalized weights dictionary
    """
    if not is_paper_mode:
        # LIVE mode: return weights unchanged
        return weights.copy()
    
    # Get mask for regime (None = use all buckets, no masking)
    mask = REGIME_BUCKET_MASK.get(regime, None)
    if mask is None:
        # Regime not in mask OR mask is None → allow all buckets (no masking)
        return weights.copy()
    
    # Determine active bucket set (only buckets in mask)
    active_buckets = [name for name in weights.keys() if name in mask]
    
    # Phase 55.2: Direction-filtered flow bucket in trends (PAPER only)
    # In trend regimes, only include flow if its direction agrees with the trend
    import os
    if bucket_dirs is not None and regime in ("trend_up", "trend_down"):
        flow_dir = bucket_dirs.get("flow", 0)
        trend_dir = 1 if regime == "trend_up" else -1
        
        if "flow" in active_buckets:
            if flow_dir != trend_dir:
                # Exclude counter-trend or neutral flow in trend regimes
                active_buckets = [name for name in active_buckets if name != "flow"]
                if os.getenv("DEBUG_SIGNALS", "0") == "1":
                    print(f"SIGNAL-MASK: excluded flow in regime={regime} due to counter-trend dir={flow_dir}")
            else:
                if os.getenv("DEBUG_SIGNALS", "0") == "1":
                    print(f"SIGNAL-MASK: kept flow in regime={regime} with agreeing dir={flow_dir}")
    
    # Edge case: if after masking we end up with no buckets, fall back to all buckets
    if not active_buckets:
        return weights.copy()
    
    # Compute total weight over active buckets, then renormalize
    total_weight = sum(weights.get(name, 0.0) for name in active_buckets)
    normalized_weights = {}
    
    if total_weight > 0:
        # Renormalize weights to sum to 1.0 over active buckets
        for name in active_buckets:
            normalized_weights[name] = weights.get(name, 0.0) / total_weight
    else:
        # If no usable weights, just copy original (won't matter much in this edge case)
        for name in active_buckets:
            normalized_weights[name] = weights.get(name, 0.0)
    
    return normalized_weights


def _compute_council_aggregation(bucket_dirs: Dict[str, int], bucket_confs: Dict[str, float],
                                 regime: str, is_paper_mode: bool = False) -> Dict[str, Any]:
    """
    Compute council-aggregated final score.
    
    Args:
        bucket_dirs: Bucket directions
        bucket_confs: Bucket confidences
        regime: Market regime
        is_paper_mode: Whether running in PAPER mode (Phase 55: mask only applied in PAPER)
    
    Returns:
        Dictionary with "dir", "conf", and "final_score"
    """
    # Get council weights for regime
    # Reload weights if COUNCIL_WEIGHTS_FILE env var is set (for backtest experiments)
    import os
    if os.getenv("COUNCIL_WEIGHTS_FILE"):
        # Reload weights from env var file (backtest only)
        current_weights = _load_council_weights()
    else:
        current_weights = COUNCIL_WEIGHTS
    
    # Map regime to weights key (panic_down → trend_down, trend_up/trend_down → trend if needed)
    regime_for_weights = regime
    if regime == "panic_down":
        regime_for_weights = "trend_down"
    if regime_for_weights not in current_weights:
        if regime_for_weights in ("trend_up", "trend_down"):
            regime_for_weights = "trend"
        else:
            regime_for_weights = "chop"
    
    base_weights = current_weights.get(regime_for_weights, current_weights["chop"])
    
    # Phase 55: Apply bucket mask and renormalize (PAPER only)
    # Phase 55.2: Pass bucket_dirs for direction-filtered flow in trends
    weights = apply_bucket_mask(base_weights, regime, is_paper_mode, bucket_dirs=bucket_dirs)
    
    # Phase 55: Debug logging for bucket masking
    if is_paper_mode and os.getenv("DEBUG_SIGNALS", "0") == "1":
        mask = REGIME_BUCKET_MASK.get(regime, None)
        if mask is not None:
            active_buckets = [name for name in weights.keys() if weights.get(name, 0.0) > 0]
            print(f"SIGNAL-MASK: regime={regime} active_buckets={active_buckets}")
    
    # Compute final score: Σ (council_weight_i * dir_i * conf_i)
    # Phase 54: Include sentiment and onchain_flow buckets (they'll have 0 weight until enabled)
    final_score = 0.0
    for bucket in ["momentum", "meanrev", "flow", "positioning", "timing", "sentiment", "onchain_flow"]:
        weight = weights.get(bucket, 0.0)
        dir_val = bucket_dirs.get(bucket, 0)
        conf_val = bucket_confs.get(bucket, 0.0)
        final_score += weight * dir_val * conf_val
    
    # Compute final direction and confidence
    final_dir = 1 if final_score > 0 else (-1 if final_score < 0 else 0)
    final_conf = max(0.0, min(1.0, abs(final_score)))
    
    return {
        "dir": final_dir,
        "conf": final_conf,
        "final_score": final_score,
    }


def decide(signal_vector: List[float], raw_registry: Dict[str, Any],
           classifier: Optional[RegimeClassifier] = None) -> Dict[str, Any]:
    """
    Pure function to compute regime, bucket outputs, and final decision.
    
    Args:
        signal_vector: Normalized signal vector
        raw_registry: Raw signal registry
        classifier: Optional RegimeClassifier instance
    
    Returns:
        Dictionary with "regime", "buckets", and "final" keys
    """
    # Load signal registry and gates config
    signal_registry_data = _load_signal_registry()
    gates_config = _load_gates_config()
    
    # Get regime
    regime_result = get_regime(signal_vector, raw_registry, classifier)
    regime = regime_result["regime"]
    
    # Compute bucket scores
    bucket_scores = _compute_bucket_scores(signal_vector, raw_registry, signal_registry_data)
    
    # Compute bucket directions and confidences
    bucket_dirs = _compute_bucket_directions(bucket_scores)
    bucket_confs = _compute_bucket_confidences(bucket_scores)
    
    # Build bucket outputs
    # Phase 54: Include sentiment and onchain_flow buckets in output (disabled by default)
    buckets = {}
    for bucket in ["momentum", "meanrev", "flow", "positioning", "timing", "sentiment", "onchain_flow"]:
        buckets[bucket] = {
            "dir": bucket_dirs.get(bucket, 0),
            "conf": bucket_confs.get(bucket, 0.0),
            "score": bucket_scores.get(bucket, 0.0),
        }
    
    # Compute council aggregation
    # Phase 55: Detect PAPER mode for bucket masking
    import os
    is_paper_mode = os.getenv("MODE", "PAPER").upper() == "PAPER"
    final_result = _compute_council_aggregation(bucket_dirs, bucket_confs, regime, is_paper_mode)
    
    return {
        "regime": regime,
        "buckets": buckets,
        "final": {
            "dir": final_result["dir"],
            "conf": final_result["conf"],
        },
        "gates": {
            "entry_min_conf": gates_config["entry_exit"]["entry_min_conf"].get(regime, 0.58),
            "exit_min_conf": gates_config["entry_exit"]["exit_min_conf"],
            "reverse_min_conf": gates_config["entry_exit"]["reverse_min_conf"],
        },
    }

