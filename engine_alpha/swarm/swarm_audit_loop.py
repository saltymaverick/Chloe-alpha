"""
SWARM Audit Loop - Periodic Full Audit

Runs comprehensive audits of Chloe's state and research outputs.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Any
import json
from datetime import datetime, timezone

from engine_alpha.swarm.swarm_sentinel import run_sentinel_checks

ROOT_DIR = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT_DIR / "reports"
RESEARCH_DIR = REPORTS_DIR / "research"
CONFIG_DIR = ROOT_DIR / "config"

ANALYZER_OUT_PATH = RESEARCH_DIR / "multi_horizon_stats.json"  # Created by weighted_analyzer
STRENGTH_PATH = RESEARCH_DIR / "strategy_strength.json"
CONF_MAP_PATH = CONFIG_DIR / "confidence_map.json"
THRESHOLDS_PATH = CONFIG_DIR / "entry_thresholds.json"  # Updated path

SWARM_AUDIT_LOG = RESEARCH_DIR / "swarm_audit_log.jsonl"


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r") as f:
        return json.load(f)


@dataclass
class AuditSnapshot:
    ts: str
    sentinel: Dict[str, Any]
    analyzer_present: bool
    strengths_present: bool
    confidence_map_present: bool
    thresholds_present: bool
    issues: Dict[str, str]


def run_swarm_audit() -> AuditSnapshot:
    """
    Run comprehensive SWARM audit.
    
    Checks:
    - Sentinel health status
    - Research outputs present (analyzer, strengths, confidence_map, thresholds)
    - Flags missing or invalid files
    
    Returns:
        AuditSnapshot with audit results
    """
    sentinel = run_sentinel_checks()
    issues: Dict[str, str] = {}

    analyzer = _load_json(ANALYZER_OUT_PATH)
    strengths = _load_json(STRENGTH_PATH)
    conf_map = _load_json(CONF_MAP_PATH)
    thresholds = _load_json(THRESHOLDS_PATH)

    analyzer_present = bool(analyzer)
    strengths_present = bool(strengths)
    conf_present = bool(conf_map)
    thr_present = bool(thresholds)

    if not analyzer_present:
        issues["analyzer"] = "Analyzer output missing."
    if not strengths_present:
        issues["strengths"] = "Strategy strength file missing."
    if not conf_present:
        issues["confidence_map"] = "Confidence map missing."
    if not thr_present:
        issues["thresholds"] = "Regime thresholds missing."

    snap = AuditSnapshot(
        ts=datetime.now(timezone.utc).isoformat(),
        sentinel=asdict(sentinel),
        analyzer_present=analyzer_present,
        strengths_present=strengths_present,
        confidence_map_present=conf_present,
        thresholds_present=thr_present,
        issues=issues,
    )

    SWARM_AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with SWARM_AUDIT_LOG.open("a") as f:
        f.write(json.dumps(asdict(snap)) + "\n")

    return snap


if __name__ == "__main__":
    s = run_swarm_audit()
    print(json.dumps(asdict(s), indent=2))

