"""
SWARM Research Verifier - Nightly Consistency Checks

Verifies research outputs are present, valid, and consistent.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Any
import json
from datetime import datetime, timezone

ROOT_DIR = Path(__file__).resolve().parents[2]  # Go up to repo root
REPORTS_DIR = ROOT_DIR / "reports"
RESEARCH_DIR = REPORTS_DIR / "research"
CONFIG_DIR = ROOT_DIR / "config"

ANALYZER_OUT_PATH = RESEARCH_DIR / "multi_horizon_stats.json"
STRENGTH_PATH = RESEARCH_DIR / "strategy_strength.json"
CONF_MAP_PATH = CONFIG_DIR / "confidence_map.json"
THRESHOLDS_PATH = CONFIG_DIR / "entry_thresholds.json"  # Updated path

SWARM_RESEARCH_LOG = RESEARCH_DIR / "swarm_research_verifier.jsonl"


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r") as f:
        return json.load(f)


@dataclass
class ResearchVerificationResult:
    ts: str
    analyzer_ok: bool
    strengths_ok: bool
    thresholds_ok: bool
    confidence_map_ok: bool
    notes: Dict[str, str]


def verify_research_outputs() -> ResearchVerificationResult:
    """
    Verify research outputs are present, valid, and consistent.
    
    Checks:
    - Analyzer output exists and has horizons/stats
    - Strengths file exists
    - Thresholds file exists
    - Confidence map exists
    - Cross-check regime names between analyzer and strengths
    
    Returns:
        ResearchVerificationResult with verification status
    """
    analyzer = _load_json(ANALYZER_OUT_PATH)
    strengths = _load_json(STRENGTH_PATH)
    conf_map = _load_json(CONF_MAP_PATH)
    thresholds = _load_json(THRESHOLDS_PATH)

    notes: Dict[str, str] = {}

    analyzer_ok = bool(analyzer)
    strengths_ok = bool(strengths)
    conf_ok = bool(conf_map)
    thr_ok = bool(thresholds)

    if analyzer_ok:
        # Sanity: ensure at least one horizon and some stats
        horizons = list(analyzer.keys())
        if not horizons:
            analyzer_ok = False
            notes["analyzer"] = "No horizons in analyzer output."
        else:
            any_stats = any(analyzer[h].get("stats") for h in horizons)
            if not any_stats:
                analyzer_ok = False
                notes["analyzer"] = "Analyzer stats empty."

    if strengths_ok and analyzer_ok:
        # Cross-check: regime names overlap
        any_h = next(iter(analyzer.keys()))
        stat_keys = analyzer[any_h].get("stats", {}).keys()
        regimes_from_analyzer = {k.split("|")[0] for k in stat_keys}
        regimes_from_strength = set(strengths.keys())
        missing_in_strength = regimes_from_analyzer - regimes_from_strength
        if missing_in_strength:
            notes["strengths"] = f"Missing strengths for regimes: {sorted(missing_in_strength)}"

    if not conf_ok:
        notes["confidence_map"] = "Confidence map missing or empty."

    if not thr_ok:
        notes["thresholds"] = "Regime thresholds missing or empty."

    res = ResearchVerificationResult(
        ts=datetime.now(timezone.utc).isoformat(),
        analyzer_ok=analyzer_ok,
        strengths_ok=strengths_ok,
        thresholds_ok=thr_ok,
        confidence_map_ok=conf_ok,
        notes=notes,
    )

    SWARM_RESEARCH_LOG.parent.mkdir(parents=True, exist_ok=True)
    with SWARM_RESEARCH_LOG.open("a") as f:
        f.write(json.dumps(asdict(res)) + "\n")

    return res


if __name__ == "__main__":
    r = verify_research_outputs()
    print(json.dumps(asdict(r), indent=2))

