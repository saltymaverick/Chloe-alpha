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

# Council weights by regime
COUNCIL_WEIGHTS = {
    "trend": {
        "momentum": 0.45,
        "meanrev": 0.10,
        "flow": 0.25,
        "positioning": 0.15,
        "timing": 0.05,
    },
    "chop": {
        "momentum": 0.15,
        "meanrev": 0.45,
        "flow": 0.20,
        "positioning": 0.15,
        "timing": 0.05,
    },
    "high_vol": {
        "momentum": 0.30,
        "meanrev": 0.10,
        "flow": 0.35,
        "positioning": 0.20,
        "timing": 0.05,
    },
}

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
                    "trend": 0.66,
                    "chop": 0.68,
                    "high_vol": 0.67,
                },
                "exit_min_conf": 0.32,
                "reverse_min_conf": 0.55,
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
    bucket_scores = {
        "momentum": 0.0,
        "meanrev": 0.0,
        "flow": 0.0,
        "positioning": 0.0,
        "timing": 0.0,
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


def _compute_council_aggregation(bucket_dirs: Dict[str, int], bucket_confs: Dict[str, float],
                                 regime: str) -> Dict[str, Any]:
    """
    Compute council-aggregated final score.
    
    Args:
        bucket_dirs: Bucket directions
        bucket_confs: Bucket confidences
        regime: Market regime
    
    Returns:
        Dictionary with "dir", "conf", and "final_score"
    """
    # Get council weights for regime
    weights = COUNCIL_WEIGHTS.get(regime, COUNCIL_WEIGHTS["chop"])
    
    # Compute final score: Σ (council_weight_i * dir_i * conf_i)
    final_score = 0.0
    for bucket in ["momentum", "meanrev", "flow", "positioning", "timing"]:
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
    buckets = {}
    for bucket in ["momentum", "meanrev", "flow", "positioning", "timing"]:
        buckets[bucket] = {
            "dir": bucket_dirs.get(bucket, 0),
            "conf": bucket_confs.get(bucket, 0.0),
            "score": bucket_scores.get(bucket, 0.0),
        }
    
    # Compute council aggregation
    final_result = _compute_council_aggregation(bucket_dirs, bucket_confs, regime)
    
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

