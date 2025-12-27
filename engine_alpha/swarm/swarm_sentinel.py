"""
SWARM Sentinel - Health + Invariants

Monitors Chloe's health metrics and flags critical issues.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Any
import json
from datetime import datetime, timezone

ROOT_DIR = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT_DIR / "reports"
RESEARCH_DIR = REPORTS_DIR / "research"

PF_LOCAL_PATH = REPORTS_DIR / "pf_local.json"
LOOP_HEALTH_PATH = REPORTS_DIR / "loop_health.json"
COUNCIL_SNAPSHOT_PATH = REPORTS_DIR / "council_snapshot.json"
ANALYZER_OUT_PATH = RESEARCH_DIR / "multi_horizon_stats.json"
STRENGTH_PATH = RESEARCH_DIR / "strategy_strength.json"
BLIND_SPOT_LOG = RESEARCH_DIR / "blind_spots.jsonl"

SENTINEL_REPORT_PATH = RESEARCH_DIR / "swarm_sentinel_report.json"


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r") as f:
        return json.load(f)


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with path.open("r") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


@dataclass
class SentinelCheckResult:
    ts: str
    pf_local: float
    drawdown: float
    avg_edge: float
    blind_spots: int
    critical: bool
    warnings: Dict[str, str]


def run_sentinel_checks() -> SentinelCheckResult:
    """
    Run SWARM sentinel health checks.
    
    Monitors:
    - PF_local (critical if < 0.90, watch if < 0.95)
    - Drawdown (critical if > 25%, watch if > 15%)
    - Blind spots (count)
    - Average edge (warn if negative)
    
    Returns:
        SentinelCheckResult with health status and warnings
    """
    pf = _load_json(PF_LOCAL_PATH)
    loop_health = _load_json(LOOP_HEALTH_PATH)
    strengths = _load_json(STRENGTH_PATH)

    # Try multiple paths for PF
    pf_val = float(pf.get("pf", pf.get("pf_local", loop_health.get("pf_local", 1.0))))
    dd = float(pf.get("drawdown", loop_health.get("drawdown", 0.0)))
    blind_n = _count_lines(BLIND_SPOT_LOG)

    # Average edge from strengths
    edges = [info.get("edge", 0.0) for info in strengths.values()] or [0.0]
    avg_edge = sum(edges) / len(edges) if edges else 0.0

    warnings: Dict[str, str] = {}
    critical = False

    # PF guards
    if pf_val < 0.9:
        critical = True
        warnings["pf_local"] = f"PF_local={pf_val:.3f} < 0.90 (critical)."
    elif pf_val < 0.95:
        warnings["pf_local"] = f"PF_local={pf_val:.3f} < 0.95 (watch)."

    # Drawdown guards
    if dd > 0.25:
        critical = True
        warnings["drawdown"] = f"Drawdown={dd:.2%} > 25% (critical)."
    elif dd > 0.15:
        warnings["drawdown"] = f"Drawdown={dd:.2%} > 15% (watch)."

    # Blind spots
    if blind_n > 0:
        warnings["blind_spots"] = f"{blind_n} blind-spot alerts logged."

    # Edge
    if avg_edge < -0.001:
        warnings["avg_edge"] = f"Avg edge={avg_edge:.5f} negative (model may be misaligned)."

    result = SentinelCheckResult(
        ts=datetime.now(timezone.utc).isoformat(),
        pf_local=pf_val,
        drawdown=dd,
        avg_edge=avg_edge,
        blind_spots=blind_n,
        critical=critical,
        warnings=warnings,
    )

    SENTINEL_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SENTINEL_REPORT_PATH.open("w") as f:
        json.dump(asdict(result), f, indent=2)

    return result


if __name__ == "__main__":
    r = run_sentinel_checks()
    print(json.dumps(asdict(r), indent=2))


