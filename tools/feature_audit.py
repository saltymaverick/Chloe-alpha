#!/usr/bin/env python3
"""
Feature Flag Audit Command

Shows which features are in which mode and whether they are producing artifacts.

Usage:
    python3 -m tools.feature_audit
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Tuple, Optional

from engine_alpha.config.feature_flags import get_feature_registry, FEATURE_DOCS


def get_file_info(path: str) -> Optional[Tuple[str, str]]:
    """Get file modification time and size if exists."""
    p = Path(path)
    if p.exists():
        try:
            stat = p.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            size = stat.st_size
            return f"{mtime.strftime('%Y-%m-%d %H:%M:%S UTC')}", f"{size:,} bytes"
        except Exception:
            return "error", "error"
    return None


def check_readiness(feature: str, mode: str) -> str:
    """Check if feature is ready for enforcement."""
    if mode != "enforce":
        return "N/A (not enforcing)"

    try:
        if feature == "tuner_apply":
            # Check if tuner validation exists
            try:
                from tools.validate_tuner_apply import validate_tuner_apply
                result = validate_tuner_apply(dry_run=True)
                return "READY" if result else "BLOCKED (validation failed)"
            except ImportError:
                return "UNKNOWN (no validator)"

        elif feature == "dream_mode":
            # Check if PF data exists and is profitable
            pf_path = Path("reports/pf_local.json")
            if pf_path.exists():
                try:
                    pf_data = json.loads(pf_path.read_text())
                    pf_7d = pf_data.get("pf_7d", 0)
                    if pf_7d >= 1.00:
                        return "READY"
                    else:
                        return f"BLOCKED (pf_7d={pf_7d:.3f} < 1.00)"
                except Exception:
                    return "BLOCKED (pf data unreadable)"
            else:
                return "BLOCKED (no pf data)"

        elif feature in ("promotion_bridge", "auto_promotions"):
            # Check if promotion advice exists
            advice_path = Path("reports/gpt/promotion_advice.json")
            if advice_path.exists():
                return "READY"
            else:
                return "BLOCKED (no promotion advice)"

    except Exception as e:
        return f"ERROR ({e})"

    return "READY"


def main() -> int:
    """Run feature audit."""
    print("=== FEATURE FLAG AUDIT ===")
    print(f"Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print()

    registry = get_feature_registry()

    # Artifact paths to check
    ARTIFACTS = {
        "counterfactual_ledger": "reports/counterfactual_ledger.jsonl",
        "inaction_scoring": "reports/inaction_performance_log.jsonl",
        "fvg_detector": "reports/fair_value_gaps.jsonl",
        "edge_half_life": ["reports/edge_half_life.json", "reports/edge_half_life_snapshot.json"],
        "mini_reflection": "reports/gpt/mini_reflection_log.jsonl",
        "promotion_bridge": ["reports/gpt/promotion_advice.json", "reports/gpt/shadow_promotion_queue.json"],
        "auto_promotions": "reports/risk/auto_promotions.json",
        "tuner_apply": ["reports/gpt/tuner_output.json", "reports/gpt/tuner_apply_log.jsonl"],
        "dream_mode": ["reports/dream_log.jsonl", "reports/reflect/dream_log.jsonl"],
        "feature_audit": "reports/loop/loop_health.json",
    }

    # Sort features by category
    categories = {
        "Trading/Policy": ["exit_confidence_exits", "sample_building_pnl_stops", "exploration_micro_exits",
                          "chop_meanrev_override", "promotion_bridge", "auto_promotions", "rehab_rules", "quarantine_rules"],
        "GPT/Learning": ["mini_reflection", "full_reflection", "tuner_apply", "dream_mode"],
        "Meta-intelligence": ["counterfactual_ledger", "inaction_scoring", "edge_half_life", "fvg_detector", "meta_orchestrator"],
        "Telemetry": ["feature_audit"],
    }

    for category, features in categories.items():
        print(f"=== {category} ===")
        for feature in features:
            mode = registry.mode(feature)
            doc = FEATURE_DOCS.get(feature, "No description")

            # Check artifacts
            artifact_info = []
            artifact_paths = ARTIFACTS.get(feature, [])
            if isinstance(artifact_paths, str):
                artifact_paths = [artifact_paths]

            for path in artifact_paths:
                info = get_file_info(path)
                if info:
                    artifact_info.append(f"{Path(path).name}: {info[0]}, {info[1]}")
                elif path == artifact_paths[0]:  # Only show missing for first path
                    artifact_info.append("No artifacts")

            artifacts_str = "; ".join(artifact_info) if artifact_info else "No artifacts"

            # Check readiness
            readiness = check_readiness(feature, mode)

            print(f"  {feature}")
            print(f"    Mode: {mode.upper()}")
            print(f"    Desc: {doc}")
            print(f"    Activity: {artifacts_str}")
            print(f"    Ready: {readiness}")
            print()

    return 0


if __name__ == "__main__":
    exit(main())
