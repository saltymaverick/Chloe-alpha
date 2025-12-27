"""
Dry-run parameter tuner.

Proposes parameter adjustments based on primitives without applying them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from engine_alpha.core.atomic_io import atomic_write_json, atomic_append_jsonl
from engine_alpha.core.paths import CONFIG, REPORTS


TUNER_CONFIG_PATH = CONFIG / "tuner_config.json"
TUNER_DRYRUN_PATH = REPORTS / "tuner_dryrun.json"
TUNER_DRYRUN_JSONL_PATH = REPORTS / "tuner_dryrun.jsonl"


def _default_tuner_config() -> Dict[str, Any]:
    """Return default tuner configuration."""
    return {
        "decay": {
            "confidence_half_life_s": 1800,
            "pci_half_life_s": 900,
        },
        "compression": {
            "threshold_score": 0.6,
        },
        "opportunity": {
            "min_confidence": 0.45,
            "max_soft_invalidation": 0.60,
        },
        "self_trust": {
            "min_score_for_looser": 0.65,
            "max_overconfidence": 0.25,
        },
    }


def load_tuner_config(path: Path = TUNER_CONFIG_PATH) -> Dict[str, Any]:
    """
    Load tuner configuration from JSON file.
    Creates default config if missing.
    """
    if not path.exists():
        config = _default_tuner_config()
        # Save default config
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(path, config)
        except Exception:
            pass  # Don't fail if we can't write default
        return config
    
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            # Merge with defaults to ensure all keys exist
            default = _default_tuner_config()
            for key in default:
                if key not in data:
                    data[key] = default[key]
            return data
    except Exception:
        pass
    
    return _default_tuner_config()


def run_tuner_dryrun(packet: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run dry-run tuner analysis on reflection packet.
    
    Args:
        packet: Reflection packet dict
        
    Returns:
        Dict with recommendations list and metadata
    """
    config = load_tuner_config()
    recommendations: List[Dict[str, Any]] = []
    
    primitives = packet.get("primitives", {})
    self_trust = primitives.get("self_trust", {})
    invalidation = primitives.get("invalidation", {})
    opportunity = primitives.get("opportunity", {})
    compression = primitives.get("compression", {})
    decay = primitives.get("decay", {})
    
    self_trust_score = self_trust.get("self_trust_score")
    overconfidence_ewma = self_trust.get("overconfidence_ewma")
    n_samples = self_trust.get("n_samples", 0)
    
    # Only make recommendations if we have enough data
    if n_samples < 5:
        return {
            "ts": packet.get("ts"),
            "status": "NOOP",
            "recommendations": [],
            "blocked_by": ["NO_SELF_TRUST_SAMPLES"],
            "needed": {"min_closed_trades": 5},
            "n_samples": n_samples,
        }
    
    # Rule 1: Low self-trust + high overconfidence → tighten min_confidence
    if (
        self_trust_score is not None
        and self_trust_score < 0.45
        and overconfidence_ewma is not None
        and overconfidence_ewma > config["self_trust"]["max_overconfidence"]
    ):
        current = config["opportunity"]["min_confidence"]
        proposed = min(1.0, current + 0.03)  # Tighten by +0.03
        recommendations.append({
            "key": "opportunity.min_confidence",
            "current": current,
            "proposed": proposed,
            "reason": "self_trust low and overconfidence high → tighten eligibility",
            "confidence": 0.65,
        })
    
    # Rule 2: Low opportunity density + good self-trust → consider loosening (conservative)
    density_ewma = opportunity.get("density_ewma")
    soft_inv = invalidation.get("soft_invalidation_score")
    
    if (
        self_trust_score is not None
        and self_trust_score >= config["self_trust"]["min_score_for_looser"]
        and density_ewma is not None
        and density_ewma < 0.1
        and (soft_inv is None or soft_inv < 0.3)
    ):
        current = config["opportunity"]["min_confidence"]
        proposed = max(0.30, current - 0.02)  # Loosen slightly by -0.02
        recommendations.append({
            "key": "opportunity.min_confidence",
            "current": current,
            "proposed": proposed,
            "reason": "low opportunity density but good self-trust → slight loosening",
            "confidence": 0.50,  # Lower confidence for loosening
        })
    
    # Rule 3: High compression + invalidation spikes → raise compression threshold
    compression_score = compression.get("compression_score")
    invalidation_flags = invalidation.get("invalidation_flags", [])
    
    if (
        compression_score is not None
        and compression_score > 0.7
        and len(invalidation_flags) > 0
    ):
        current = config["compression"]["threshold_score"]
        proposed = min(1.0, current + 0.05)  # Raise threshold by +0.05
        recommendations.append({
            "key": "compression.threshold_score",
            "current": current,
            "proposed": proposed,
            "reason": "high compression with invalidation flags → raise threshold",
            "confidence": 0.60,
        })
    
    # Rule 4: Confidence rarely refreshed + decayed too low → increase half-life
    confidence_refreshed = decay.get("confidence_refreshed", False)
    confidence_decayed = decay.get("confidence_decayed")
    
    if (
        not confidence_refreshed
        and confidence_decayed is not None
        and confidence_decayed < 0.3
    ):
        current = config["decay"]["confidence_half_life_s"]
        proposed = int(current * 1.15)  # Increase by 15%
        recommendations.append({
            "key": "decay.confidence_half_life_s",
            "current": current,
            "proposed": proposed,
            "reason": "confidence rarely refreshed and decayed too low → increase half-life",
            "confidence": 0.55,
        })
    
    output = {
        "ts": packet.get("ts"),
        "status": "ACTIVE" if recommendations else "NOOP",
        "recommendations": recommendations,
        "n_samples": n_samples,
        "self_trust_score": self_trust_score,
    }
    
    # Add blocked_by if no recommendations but have samples
    if not recommendations and n_samples >= 5:
        output["blocked_by"] = ["NO_PATTERNS_DETECTED"]
        output["reason"] = "sufficient_samples_but_no_tuning_patterns_detected"
    
    # Write to files
    try:
        atomic_write_json(TUNER_DRYRUN_PATH, output)
        atomic_append_jsonl(TUNER_DRYRUN_JSONL_PATH, output)
    except Exception:
        pass  # Don't fail on file writes
    
    return output

