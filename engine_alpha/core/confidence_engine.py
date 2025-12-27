"""
Confidence engine - Phase 2
Computes bucket scores and council-aggregated confidence.

Module 5 Refactor: New Flow/Vol/Micro/Cross aggregation with regime + drift penalties.
"""

import json
import yaml
import math
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

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

# Order of buckets we expect from the signal engine
BUCKET_ORDER = ["momentum", "meanrev", "flow", "positioning", "timing", "sentiment", "onchain_flow"]

# Per-regime bucket weights for aggregation.
# These are *relative* weights; they will be normalized in aggregation.
REGIME_BUCKET_WEIGHTS = {
    "trend_up": {
        "momentum": 0.45,
        "positioning": 0.30,
        "flow": 0.15,
        "timing": 0.10,
        "meanrev": 0.0,
        "sentiment": 0.0,
        "onchain_flow": 0.0,
    },
    "trend_down": {
        "momentum": 0.45,
        "positioning": 0.30,
        "flow": 0.15,
        "timing": 0.10,
        "meanrev": 0.0,
        "sentiment": 0.0,
        "onchain_flow": 0.0,
    },
    "high_vol": {
        "momentum": 0.40,
        "flow": 0.30,
        "positioning": 0.15,
        "timing": 0.10,
        "meanrev": 0.05,
        "sentiment": 0.0,
        "onchain_flow": 0.0,
    },
    "chop": {
        "meanrev": 0.50,
        "timing": 0.25,
        "flow": 0.20,
        "momentum": 0.05,
        "positioning": 0.0,
        "sentiment": 0.0,
        "onchain_flow": 0.0,
    },
}

# Phase 55.3: Regime-Purified Averaging (PAPER only)
# Hard mask: ONLY these buckets vote in each regime
# This prevents confidence dilution from buckets that don't apply to the regime
# None = use all buckets (no masking)
REGIME_BUCKET_MASK = {
    # Trend up/down: ONLY momentum + positioning (flow removed - it dilutes in clear trends)
    "trend_up": ["momentum", "positioning"],
    "trend_down": ["momentum", "positioning"],
    # Panic down: ONLY momentum (pure trend-following, no positioning noise)
    "panic_down": ["momentum"],
    # Chop: ONLY meanrev + timing + flow (momentum excluded - trend-chasing doesn't work in chop)
    "chop": ["meanrev", "timing", "flow"],
    # High vol: ONLY momentum + flow (volatility-driven, not mean-reversion)
    "high_vol": ["momentum", "flow"],
    # Fallback for legacy "trend" regime
    "trend": ["momentum", "positioning"],
}
# Note: sentiment and onchain_flow are not included in masks (they have 0 weight anyway)

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

# Number of decimal places to keep for final confidence values.
# This reduces floating-point noise so tiny differences (e.g. 0.449999 vs 0.450001)
# don't cause different entry/exit decisions in live vs backtest.
CONFIDENCE_DECIMALS = 2


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
    
    # Phase 55.3: Hard mask - flow is already excluded from trend_up/trend_down in REGIME_BUCKET_MASK
    # Phase 55.2 direction filtering is no longer needed since we use hard masks
    # (Keeping this comment for reference, but direction filtering removed)
    
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
    
    # Phase 55.3: Apply hard regime mask (PAPER only)
    # Get the mask for this regime - this is the authoritative list of buckets that should vote
    mask = REGIME_BUCKET_MASK.get(regime, None) if is_paper_mode else None
    
    # Phase 55.3: Filter bucket_dirs and bucket_confs to ONLY include masked buckets
    # This ensures masked buckets don't exist at all during aggregation
    if mask is not None and is_paper_mode:
        # Create filtered versions that only contain masked buckets
        filtered_bucket_dirs = {name: bucket_dirs.get(name, 0) for name in mask if name in bucket_dirs}
        filtered_bucket_confs = {name: bucket_confs.get(name, 0.0) for name in mask if name in bucket_confs}
        bucket_dirs = filtered_bucket_dirs
        bucket_confs = filtered_bucket_confs
        
        # Debug logging: show which buckets were removed
        if os.getenv("DEBUG_SIGNALS", "0") == "1":
            all_buckets = ["momentum", "meanrev", "flow", "positioning", "timing", "sentiment", "onchain_flow"]
            active_buckets = list(mask)
            removed_buckets = [name for name in all_buckets if name not in active_buckets]
            print(f"SIGNAL-PURIFY: regime={regime} active={active_buckets} removed={removed_buckets}")
    
    # Use regime-specific weights from base_weights (which already has correct regime mapping applied)
    # base_weights contains the correct weights for the mapped regime (e.g., trend_down for panic_down)
    # and may contain mutated weights from backtest experiments if COUNCIL_WEIGHTS_FILE is set
    regime_weights = base_weights
    
    # Compute weighted aggregation using regime-specific weights
    weighted_score = 0.0
    weight_sum = 0.0
    debug_buckets: List[str] = []
    
    for bucket in BUCKET_ORDER:
        dir_val = bucket_dirs.get(bucket, 0)
        conf_val = bucket_confs.get(bucket, 0.0)
        w = float(regime_weights.get(bucket, 0.0))
        
        # If bucket has no direction or no weight, skip
        if dir_val == 0 or w <= 0.0 or conf_val <= 0.0:
            debug_buckets.append(f"{bucket}:dir={dir_val},conf={conf_val:.2f},w={w:.2f}")
            continue
        
        score = dir_val * conf_val
        weighted_score += w * score
        weight_sum += w
        debug_buckets.append(f"{bucket}:dir={dir_val},conf={conf_val:.2f},w={w:.2f}")
    
    if weight_sum <= 0.0:
        final_score = 0.0
    else:
        final_score = weighted_score / weight_sum
    
    if final_score > 0:
        final_dir = 1
    elif final_score < 0:
        final_dir = -1
    else:
        final_dir = 0
    
    final_conf = abs(final_score)
    # Round to configured decimals
    final_conf = round(final_conf, CONFIDENCE_DECIMALS)
    
    # Debug logging for bucket breakdown
    if is_paper_mode and os.getenv("DEBUG_SIGNALS", "0") == "1":
        print(
            f"BUCKET-AGG: regime={regime} score={final_score:.4f} weight_sum={weight_sum:.4f} "
            f"final_dir={final_dir} final_conf={final_conf:.2f}"
        )
    
    return {
        "dir": final_dir,
        "conf": final_conf,
        "final_score": final_score,
    }


def decide(signal_vector: List[float], raw_registry: Dict[str, Any],
           classifier: Optional[RegimeClassifier] = None,
           regime_override: Optional[str] = None) -> Dict[str, Any]:
    """
    Pure function to compute regime, bucket outputs, and final decision.
    
    Args:
        signal_vector: Normalized signal vector
        raw_registry: Raw signal registry
        classifier: Optional RegimeClassifier instance
        regime_override: Optional regime string to use instead of computing from signals
    
    Returns:
        Dictionary with "regime", "buckets", and "final" keys
    """
    # Load signal registry and gates config
    signal_registry_data = _load_signal_registry()
    gates_config = _load_gates_config()
    
    # Get regime (use override if provided, otherwise compute from signals)
    if regime_override:
        regime = regime_override
    else:
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
    
    # Map regime to gates key (same logic as weights mapping)
    # gates.yaml uses "trend" for both trend_up and trend_down
    regime_for_gates = regime
    if regime in ("trend_up", "trend_down", "panic_down"):
        regime_for_gates = "trend"
    
    entry_min_conf_dict = gates_config["entry_exit"]["entry_min_conf"]
    entry_min_conf = entry_min_conf_dict.get(regime_for_gates, entry_min_conf_dict.get("chop", 0.72))
    
    return {
        "regime": regime,
        "buckets": buckets,
        "final": {
            "dir": final_result["dir"],
            "conf": final_result["conf"],
            "score": final_result["final_score"],  # Expose final_score for Phase 54 adjustments
        },
        "gates": {
            "entry_min_conf": entry_min_conf,
            "exit_min_conf": gates_config["entry_exit"]["exit_min_conf"],
            "reverse_min_conf": gates_config["entry_exit"]["reverse_min_conf"],
        },
    }


# ============================================================================
# Module 5: New Confidence Engine (Flow/Vol/Micro/Cross + Regime + Drift)
# ============================================================================

@dataclass
class ConfidenceState:
    """
    Confidence state with component breakdown and penalties.
    
    Attributes:
        confidence: Final confidence score [0, 1]
        components: Component scores for each signal family
        penalties: Applied penalties (regime, drift)
    """
    confidence: float
    components: Dict[str, float]
    penalties: Dict[str, float]


# Base weights for signal families (Module 5 spec)
FLOW_WEIGHT = 0.40        # Highest weight (flow is most predictive)
VOL_WEIGHT = 0.25         # Medium weight
MICRO_WEIGHT = 0.20       # Medium/low weight
CROSS_WEIGHT = 0.15       # Medium/low weight

# Drift penalty coefficient
DRIFT_PENALTY_ALPHA = 0.5  # Multiplier for drift_score in penalty calculation (softened from 1.0)


def _load_signal_registry_for_categories() -> Dict[str, str]:
    """
    Load signal registry and return mapping: signal_name -> category.
    
    Returns:
        Dict mapping signal names to their categories
    """
    registry_path = Path(__file__).parent.parent / "signals" / "signal_registry.json"
    if not registry_path.exists():
        return {}
    
    try:
        with open(registry_path, "r") as f:
            registry = json.load(f)
            signals = registry.get("signals", [])
            return {sig["name"]: sig.get("category", "unknown") for sig in signals}
    except Exception:
        return {}


def _group_signals_by_category(raw_registry: Dict[str, Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Group signals from raw_registry by category (flow, volatility, microstructure, cross_asset).
    
    Args:
        raw_registry: Dict with signal_id -> signal_dict (with raw, z_score, direction_prob, confidence, drift)
    
    Returns:
        Dict: {category: [signal_dicts]}
    """
    signal_to_category = _load_signal_registry_for_categories()
    
    grouped = {
        "flow": [],
        "volatility": [],
        "microstructure": [],
        "cross_asset": [],
    }
    
    for signal_id, signal_data in raw_registry.items():
        if not isinstance(signal_data, dict):
            continue
        
        # Skip special keys
        if signal_id.startswith("_"):
            continue
        
        # Check if this is a flow_dict type signal
        if signal_data.get("type") == "flow_dict":
            # Get category from registry or from signal_data itself
            category = signal_data.get("category") or signal_to_category.get(signal_id, "unknown")
            
            # Normalize category name
            category_lower = str(category).lower()
            if category_lower == "flow":
                grouped["flow"].append(signal_data)
            elif category_lower == "volatility":
                grouped["volatility"].append(signal_data)
            elif category_lower == "microstructure":
                grouped["microstructure"].append(signal_data)
            elif category_lower == "cross_asset":
                grouped["cross_asset"].append(signal_data)
    
    return grouped


def _compute_group_score(signals: List[Dict[str, Any]]) -> float:
    """
    Compute a normalized group score from a list of signals.
    
    Uses average of confidence fields, normalized to [0, 1].
    
    Args:
        signals: List of signal dicts with confidence field
    
    Returns:
        Group score in [0, 1]
    """
    if not signals:
        return 0.0
    
    confidences = []
    for sig in signals:
        conf = sig.get("confidence", 0.0)
        if isinstance(conf, (int, float)):
            confidences.append(float(conf))
    
    if not confidences:
        return 0.0
    
    # Average confidence
    avg_conf = sum(confidences) / len(confidences)
    
    # Also consider z_score magnitude as a confidence boost
    z_scores = []
    for sig in signals:
        z = sig.get("z_score", 0.0)
        if isinstance(z, (int, float)):
            z_scores.append(abs(float(z)))
    
    if z_scores:
        avg_z_mag = sum(z_scores) / len(z_scores)
        # Boost confidence if z-scores are high (strong signals)
        z_boost = min(0.2, avg_z_mag / 3.0)  # Max 0.2 boost
        avg_conf = min(1.0, avg_conf + z_boost)
    
    return max(0.0, min(1.0, avg_conf))


def _compute_regime_penalty(regime_state: Dict[str, Any], signal_direction_hint: float) -> float:
    """
    Compute regime penalty based on regime state and signal direction.
    
    Simple rule:
    - CHOP regime: mildly penalize trend-following confidence
    - Supportive regimes: minimal penalty
    
    Args:
        regime_state: Dict with "primary" key (regime name)
        signal_direction_hint: Aggregate direction hint from signals (-1 to +1)
    
    Returns:
        Penalty multiplier in [0, 1]
    """
    primary = regime_state.get("primary", "chop")
    
    # Map regime names (handle variations)
    primary_lower = str(primary).lower()
    
    if primary_lower in ["chop"]:
        # CHOP: penalize trend-following confidence
        # If signals are strongly directional (high abs(signal_direction_hint)), reduce confidence
        direction_penalty = 1.0 - min(0.3, abs(signal_direction_hint) * 0.3)
        return max(0.7, direction_penalty)  # At least 0.7 penalty in CHOP
    
    elif primary_lower in ["trend_up", "trend_down", "high_vol"]:
        # Supportive regimes: minimal penalty
        return 1.0
    
    else:
        # Unknown/neutral: slight penalty
        return 0.9


def compute_confidence(
    raw_registry: Dict[str, Dict[str, Any]],
    regime_state: Dict[str, Any],
    drift_state: Dict[str, Any],
) -> ConfidenceState:
    """
    Combine flow, volatility, microstructure, and cross-asset signals
    into a single confidence score (0..1) plus component breakdown.
    
    Module 5: New aggregation using Flow/Vol/Micro/Cross families.
    
    Args:
        raw_registry: Dict with signal_id -> signal_dict (with raw, z_score, direction_prob, confidence, drift)
        regime_state: Dict with "primary" key (regime name) and optionally "scores"
        drift_state: Dict with "drift_score" key (0-1, higher = worse)
    
    Returns:
        ConfidenceState with confidence, components, and penalties
    """
    # Group signals by category
    grouped = _group_signals_by_category(raw_registry)
    
    # Compute group scores
    flow_score = _compute_group_score(grouped["flow"])
    vol_score = _compute_group_score(grouped["volatility"])
    micro_score = _compute_group_score(grouped["microstructure"])
    cross_score = _compute_group_score(grouped["cross_asset"])
    
    # Compute base confidence as weighted average
    base_confidence = (
        FLOW_WEIGHT * flow_score +
        VOL_WEIGHT * vol_score +
        MICRO_WEIGHT * micro_score +
        CROSS_WEIGHT * cross_score
    )
    
    # Normalize weights (in case they don't sum to 1.0)
    total_weight = FLOW_WEIGHT + VOL_WEIGHT + MICRO_WEIGHT + CROSS_WEIGHT
    if total_weight > 0:
        base_confidence = base_confidence / total_weight
    
    base_confidence = max(0.0, min(1.0, base_confidence))
    
    # Compute aggregate direction hint from signals (for regime penalty)
    signal_direction_hint = 0.0
    all_signals = grouped["flow"] + grouped["volatility"] + grouped["microstructure"] + grouped["cross_asset"]
    if all_signals:
        direction_hints = []
        for sig in all_signals:
            dir_prob = sig.get("direction_prob", {})
            if isinstance(dir_prob, dict):
                up_prob = dir_prob.get("up", 0.5)
                down_prob = dir_prob.get("down", 0.5)
                # Map to [-1, 1]: up_prob=1 -> +1, down_prob=1 -> -1
                hint = up_prob - down_prob
                direction_hints.append(hint)
        
        if direction_hints:
            signal_direction_hint = sum(direction_hints) / len(direction_hints)
    
    # Apply regime penalty
    penalty_regime = _compute_regime_penalty(regime_state, signal_direction_hint)
    
    # Apply drift penalty
    drift_score = float(drift_state.get("drift_score", 0.0))
    penalty_drift = max(0.0, 1.0 - DRIFT_PENALTY_ALPHA * drift_score)
    penalty_drift = max(0.0, min(1.0, penalty_drift))
    
    # Final confidence
    final_confidence = base_confidence * penalty_regime * penalty_drift
    final_confidence = max(0.0, min(1.0, final_confidence))
    
    return ConfidenceState(
        confidence=final_confidence,
        components={
            "flow": flow_score,
            "volatility": vol_score,
            "microstructure": micro_score,
            "cross_asset": cross_score,
        },
        penalties={
            "regime": penalty_regime,
            "drift": penalty_drift,
        },
    )

