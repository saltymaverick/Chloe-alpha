"""
Unified Feature Flag Framework for Chloe

Provides consistent off|observe|enforce modes for all systems.
All "observe-only" features use this to ensure they don't accidentally enforce.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Literal

FeatureMode = Literal["off", "observe", "enforce"]

# Default feature flags - preserve current automatic behavior
DEFAULT_FLAGS: Dict[str, FeatureMode] = {
    # Trading/Policy - ENFORCE: currently automatic systems
    "exit_confidence_exits": "enforce",      # Exit logic already fires automatically
    "promotion_bridge": "enforce",           # Promotion system works automatically
    "auto_promotions": "enforce",            # Follows promotion_bridge

    # Trading/Policy - OBSERVE: experimental/aggressive features
    "sample_building_pnl_stops": "observe",  # Might be too aggressive
    "exploration_micro_exits": "observe",    # Might be too aggressive
    "chop_meanrev_override": "observe",      # Experimental bucket adjustments
    "rehab_rules": "observe",                # Might freeze system too early
    "quarantine_rules": "observe",           # Might freeze system too early

    # GPT/Learning - OFF: not ready for automation
    "mini_reflection": "off",                # Too experimental
    "full_reflection": "off",                # Too experimental
    "tuner_apply": "off",                    # Needs validation
    "dream_mode": "off",                     # Needs PF validation

    # Meta-intelligence - ENFORCE: currently automatic logging systems
    "counterfactual_ledger": "enforce",      # Already logging automatically
    "inaction_scoring": "enforce",           # Already logging automatically
    "fvg_detector": "enforce",               # Already logging automatically

    # Meta-intelligence - OBSERVE: experimental features
    "edge_half_life": "observe",             # Experimental
    "meta_orchestrator": "observe",          # Not implemented yet

    # Telemetry
    "feature_audit": "enforce",              # Always on, just reporting
}

# Feature documentation for audit output
FEATURE_DOCS: Dict[str, str] = {
    # Trading/Policy
    "exit_confidence_exits": "Exit positions based on confidence thresholds",
    "sample_building_pnl_stops": "Stop sample-building positions at target P&L levels",
    "exploration_micro_exits": "Micro-management exits for exploration positions",
    "chop_meanrev_override": "Override mean-reversion signals in chop regime",
    "promotion_bridge": "Bridge GPT advice to promotion decisions",
    "auto_promotions": "Automatically apply promotion decisions to config",
    "rehab_rules": "Rehabilitation rules for failed positions",
    "quarantine_rules": "Quarantine rules for problematic symbols",

    # GPT/Learning
    "mini_reflection": "Generate mini-reflection summaries",
    "full_reflection": "Generate full comprehensive reflections",
    "tuner_apply": "Apply tuner recommendations to live trading",
    "dream_mode": "Run dream mode simulations",

    # Meta-intelligence
    "counterfactual_ledger": "Track counterfactual trading scenarios",
    "inaction_scoring": "Score performance of no-trade decisions",
    "edge_half_life": "Model trading edge decay over time",
    "fvg_detector": "Detect fair value gaps",
    "meta_orchestrator": "Orchestrate meta-intelligence decisions",

    # Telemetry
    "feature_audit": "Feature flag audit and reporting",
}


def load_feature_flags(config_path: str = "config/engine_config.json") -> Dict[str, FeatureMode]:
    """Load feature flags from config file, merged with defaults."""
    flags = DEFAULT_FLAGS.copy()

    config_file = Path(config_path)
    if config_file.exists():
        try:
            with config_file.open("r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception:
            # If config can't be read, use defaults
            return flags

        config_flags = config.get("feature_flags", {})
        if isinstance(config_flags, dict):
            # Merge config flags with defaults
            for key, value in config_flags.items():
                if key in flags and isinstance(value, str):
                    normalized = value.lower().strip()
                    if normalized in ("off", "observe", "enforce"):
                        flags[key] = normalized

    return flags


class FeatureRegistry:
    """Registry for feature flags with convenience methods."""

    def __init__(self, flags: Dict[str, FeatureMode]):
        self._flags = flags.copy()

    def mode(self, name: str) -> FeatureMode:
        """Get the mode for a feature."""
        return self._flags.get(name, "off")

    def is_off(self, name: str) -> bool:
        """Check if feature is off."""
        return self.mode(name) == "off"

    def is_observe(self, name: str) -> bool:
        """Check if feature is observe."""
        return self.mode(name) == "observe"

    def is_enforce(self, name: str) -> bool:
        """Check if feature is enforce."""
        return self.mode(name) == "enforce"

    def require_enforce(self, name: str) -> None:
        """Require that feature is in enforce mode, raise if not."""
        if not self.is_enforce(name):
            raise ValueError(f"Feature '{name}' must be in 'enforce' mode, currently '{self.mode(name)}'")


# Global registry cache
_REGISTRY_CACHE: FeatureRegistry | None = None


def get_feature_registry() -> FeatureRegistry:
    """Get the global feature registry (cached)."""
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is None:
        flags = load_feature_flags()
        _REGISTRY_CACHE = FeatureRegistry(flags)
    return _REGISTRY_CACHE


def refresh_feature_registry() -> FeatureRegistry:
    """Force reload the feature registry."""
    global _REGISTRY_CACHE
    flags = load_feature_flags()
    _REGISTRY_CACHE = FeatureRegistry(flags)
    return _REGISTRY_CACHE
