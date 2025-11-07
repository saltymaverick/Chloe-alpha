"""
Governance manager - Phase 21
Computes Strategic Confidence Index (SCI) from subsystem outcomes.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from engine_alpha.core.paths import REPORTS

# Optional dotenv support without hard dependency
try:  # pragma: no cover
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # pragma: no cover
    pass

DREAM_LOG = REPORTS / "dream_log.jsonl"
EVOLVER_SNAPSHOT = REPORTS / "evolver_snapshot.json"
PROMOTION_LOG = REPORTS / "promotion_proposals.jsonl"
SANDBOX_RUNS = REPORTS / "sandbox" / "sandbox_runs.jsonl"
PF_LOCAL_ADJ = REPORTS / "pf_local_adj.json"
CONFIDENCE_TUNE = REPORTS / "confidence_tune.jsonl"
MIRROR_SNAPSHOT = REPORTS / "mirror_snapshot.json"
PORTFOLIO_PF = REPORTS / "portfolio" / "portfolio_pf.json"

VOTE_JSON = REPORTS / "governance_vote.json"
VOTE_LOG = REPORTS / "governance_log.jsonl"
SNAPSHOT = REPORTS / "governance_snapshot.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _read_jsonl_tail(path: Path, lines: int = 3) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        rows = path.read_text().splitlines()
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for line in rows[-lines:]:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _clamp(value: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
    return max(min_val, min(max_val, value))


def _dream_score(pf_adj_baseline: float) -> float:
    entries = _read_jsonl_tail(DREAM_LOG, lines=1)
    if not entries:
        return 0.5
    best = entries[-1]
    pf_cf = best.get("best_pf_cf") or best.get("pf_cf")
    if not isinstance(pf_cf, (int, float)):
        return 0.5
    polarity = 0.0
    if pf_adj_baseline:
        delta = pf_cf - pf_adj_baseline
        if delta > 0:
            polarity = 1.0
        elif delta < 0:
            polarity = -1.0
    return _clamp(0.5 + 0.5 * polarity)


def _evolver_score(pf_adj_baseline: float) -> float:
    snapshot = _read_json(EVOLVER_SNAPSHOT)
    best = snapshot.get("best", {})
    tested = snapshot.get("tested", 0)
    pf_cf = best.get("pf_cf")
    if not isinstance(pf_cf, (int, float)):
        return 0.5
    if tested < 50:
        return 0.3
    baseline = pf_adj_baseline or 1.0
    ratio = pf_cf / max(baseline, 1e-6)
    return _clamp(ratio / 2.0)


def _sandbox_score() -> float:
    runs = _read_jsonl_tail(SANDBOX_RUNS, lines=1)
    if not runs:
        return 0.5
    pf_adj = runs[-1].get("pf_adj")
    if not isinstance(pf_adj, (int, float)):
        return 0.5
    return _clamp(pf_adj / 2.0)


def _mirror_score() -> float:
    snapshot = _read_json(PORTFOLIO_PF)
    if snapshot:
        pf = snapshot.get("portfolio_pf")
        if isinstance(pf, (int, float)):
            return _clamp(pf / 1.5)
    return 0.5


def _confidence_bias() -> Dict[str, Any]:
    entries = _read_jsonl_tail(CONFIDENCE_TUNE, lines=1)
    return entries[-1] if entries else {}


def _enabled_env(var: str, default: bool = True) -> bool:
    value = os.getenv(var)
    if value is None:
        return default
    return value.lower() == "true"


def run_once() -> Dict[str, Any]:
    pf_adj_baseline = _read_json(PF_LOCAL_ADJ).get("pf")
    pf_baseline_val = float(pf_adj_baseline) if isinstance(pf_adj_baseline, (int, float)) else 1.0

    modules = {}
    enabled_modules = []

    def add_module(name: str, score: float, note: str) -> None:
        modules[name] = {"enabled": True, "score": _clamp(score), "note": note}
        enabled_modules.append(modules[name]["score"])

    if _enabled_env("GOV_USE_DREAM", True):
        add_module("dream", _dream_score(pf_baseline_val), "dream bias vs baseline")
    if _enabled_env("GOV_USE_EVOLVER", True):
        add_module("evolver", _evolver_score(pf_baseline_val), "evolver pf_cf vs baseline")
    if _enabled_env("GOV_USE_SANDBOX", True):
        add_module("sandbox", _sandbox_score(), "sandbox PF_adj/2")
    if _enabled_env("GOV_USE_MIRROR", True):
        add_module("mirror", _mirror_score(), "portfolio PF/1.5")

    if not enabled_modules:
        modules = {"default": {"enabled": True, "score": 0.5, "note": "fallback"}}
        enabled_modules = [0.5]

    sci = sum(enabled_modules) / len(enabled_modules)
    if sci >= 0.60:
        recommendation = "GO"
    elif sci <= 0.45:
        recommendation = "PAUSE"
    else:
        recommendation = "REVIEW"

    payload = {
        "ts": _now(),
        "modules": modules,
        "sci": _clamp(sci),
        "recommendation": recommendation,
    }

    VOTE_JSON.write_text(json.dumps(payload, indent=2))
    with VOTE_LOG.open("a") as f:
        f.write(json.dumps(payload) + "\n")
    SNAPSHOT.write_text(json.dumps(payload, indent=2))
    return payload
