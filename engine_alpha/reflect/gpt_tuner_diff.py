"""
GPT Tuner Diff - Generate dry-run config diff from GPT proposed changes.

Never auto-applies changes; only produces diff reports.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine_alpha.core.atomic_io import atomic_write_json, atomic_append_jsonl
from engine_alpha.core.paths import CONFIG, REPORTS
from engine_alpha.reflect.tuner_dryrun import load_tuner_config


GPT_TUNER_DIFF_PATH = REPORTS / "gpt_tuner_diff.json"
GPT_TUNER_DIFF_JSONL_PATH = REPORTS / "gpt_tuner_diff.jsonl"

# Allowed parameter keys (security: reject unknown keys)
ALLOWED_PARAM_KEYS = {
    "decay.confidence_half_life_s",
    "decay.pci_half_life_s",
    "compression.threshold_score",
    "opportunity.min_confidence",
    "opportunity.max_soft_invalidation",
}

# Type validation rules per key
PARAM_VALIDATORS = {
    "decay.confidence_half_life_s": {
        "type": int,
        "min": 300,  # 5 minutes
        "max": 14400,  # 4 hours
    },
    "decay.pci_half_life_s": {
        "type": int,
        "min": 300,
        "max": 14400,
    },
    "compression.threshold_score": {
        "type": float,
        "min": 0.0,
        "max": 1.0,
    },
    "opportunity.min_confidence": {
        "type": float,
        "min": 0.0,
        "max": 1.0,
    },
    "opportunity.max_soft_invalidation": {
        "type": float,
        "min": 0.0,
        "max": 1.0,
    },
}


def get_nested_value(cfg: Dict[str, Any], key_path: str) -> Optional[Any]:
    """
    Get nested config value by dot-separated path.
    
    Args:
        cfg: Config dict
        key_path: Dot-separated path (e.g., "decay.confidence_half_life_s")
        
    Returns:
        Value if found, None otherwise
    """
    if "." not in key_path:
        return cfg.get(key_path)
    
    parts = key_path.split(".")
    current = cfg
    
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    
    return current


def validate_proposed_value(key: str, proposed: Any) -> tuple[bool, Optional[str]]:
    """
    Validate proposed value against type and bounds.
    
    Args:
        key: Parameter key
        proposed: Proposed value
        
    Returns:
        (is_valid, error_message)
    """
    if key not in PARAM_VALIDATORS:
        return False, f"Unknown key: {key}"
    
    validator = PARAM_VALIDATORS[key]
    expected_type = validator["type"]
    
    # Type check
    if not isinstance(proposed, expected_type):
        # Try conversion
        try:
            if expected_type == int:
                proposed = int(float(proposed))  # Handle float->int conversion
            elif expected_type == float:
                proposed = float(proposed)
            else:
                return False, f"Invalid type: expected {expected_type.__name__}, got {type(proposed).__name__}"
        except (ValueError, TypeError):
            return False, f"Cannot convert to {expected_type.__name__}: {proposed}"
    
    # Bounds check
    min_val = validator.get("min")
    max_val = validator.get("max")
    
    if min_val is not None and proposed < min_val:
        return False, f"Value {proposed} below minimum {min_val}"
    
    if max_val is not None and proposed > max_val:
        return False, f"Value {proposed} above maximum {max_val}"
    
    return True, None


def compute_diff(
    current_cfg: Dict[str, Any],
    proposed_changes: List[Dict[str, Any]],
    ts: str,
    self_trust_score: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Compute dry-run config diff from proposed changes.
    
    Args:
        current_cfg: Current tuner config dict
        proposed_changes: List of proposed change dicts from GPT
        ts: Timestamp string
        self_trust_score: Optional self-trust score for risk tagging
        
    Returns:
        Diff dict with status and changes
    """
    changes = []
    rejected_keys = []
    noop_count = 0
    invalid_values = []
    
    for prop in proposed_changes:
        if not isinstance(prop, dict):
            continue
        
        key = prop.get("key")
        if not key or not isinstance(key, str):
            continue
        
        # Security: Only allow whitelisted parameter keys
        if key not in ALLOWED_PARAM_KEYS:
            rejected_keys.append(key)
            continue
        
        proposed = prop.get("proposed")
        reason = prop.get("reason", "")
        confidence = prop.get("confidence", 0.0)
        
        # Extract current value from config (override GPT's current if wrong)
        current = get_nested_value(current_cfg, key)
        
        # Skip if proposed is None
        if proposed is None:
            continue
        
        # Validate proposed value (type and bounds)
        is_valid, validation_error = validate_proposed_value(key, proposed)
        if not is_valid:
            invalid_values.append({
                "key": key,
                "proposed": proposed,
                "error": validation_error,
            })
            continue
        
        # Convert to correct type if needed
        validator = PARAM_VALIDATORS[key]
        if validator["type"] == int and isinstance(proposed, float):
            proposed = int(proposed)
        elif validator["type"] == float and isinstance(proposed, int):
            proposed = float(proposed)
        
        # Filter no-ops: skip if proposed == current
        if proposed == current:
            noop_count += 1
            continue
        
        # Include valid, non-no-op changes
        changes.append({
            "key": key,
            "current": current,
            "proposed": proposed,
            "reason": reason,
            "confidence": float(confidence) if isinstance(confidence, (int, float)) else 0.0,
        })
    
    # Build result
    result = {
        "ts": ts,
        "status": "DRY_RUN",
        "changes": changes,
        "n_changes": len(changes),
    }
    
    # Add risk tag if self-trust is low
    if self_trust_score is not None and self_trust_score < 0.45:
        result["risk"] = "LOW_SELF_TRUST — REVIEW CAREFULLY"
        result["self_trust_score"] = self_trust_score
    
    # Add rejection stats
    if rejected_keys:
        result["rejected_keys"] = rejected_keys
        result["rejected_count"] = len(rejected_keys)
    
    if invalid_values:
        result["invalid_values"] = invalid_values
        result["invalid_count"] = len(invalid_values)
    
    if noop_count > 0:
        result["noop_count"] = noop_count
    
    return result


def write_diff(diff: Dict[str, Any]) -> None:
    """
    Write diff to files (latest + append to JSONL).
    
    Args:
        diff: Diff dict
    """
    try:
        atomic_write_json(GPT_TUNER_DIFF_PATH, diff)
        atomic_append_jsonl(GPT_TUNER_DIFF_JSONL_PATH, diff)
    except Exception:
        pass  # Don't fail on file writes

