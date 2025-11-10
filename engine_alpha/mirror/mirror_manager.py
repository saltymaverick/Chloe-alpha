"""Mirror manager - Phase 34

Paper-only mirror utilities that derive sandbox candidates from existing reports.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

from engine_alpha.core.paths import REPORTS
from engine_alpha.mirror.wallet_observer import load_config as load_observer_cfg

MIRROR_SNAPSHOT = REPORTS / "mirror_snapshot.json"
CANDIDATES_PATH = REPORTS / "mirror_candidates.json"
LOG_PATH = REPORTS / "mirror_manager_log.jsonl"
PORTFOLIO_PF_PATH = REPORTS / "portfolio" / "portfolio_pf.json"
COUNCIL_PATH = REPORTS / "council_weights.json"
BEHAVIOR_PATH = REPORTS / "mirror" / "behavior.json"
HUNTER_TARGETS_PATH = REPORTS / "mirror" / "targets.json"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def build_candidates_from_observer(min_score: float = 0.65, max_candidates: int = 5) -> List[Dict[str, Any]]:
    """Build candidate list from wallet observer behaviour outputs."""
    behavior = _read_json(BEHAVIOR_PATH)
    if not isinstance(behavior, dict):
        return []

    items = []
    for address, metrics in behavior.items():
        if not isinstance(metrics, dict):
            continue
        score = metrics.get("score")
        try:
            score_val = float(score)
        except Exception:
            continue
        if score_val < min_score:
            continue
        items.append((address, score_val))

    items.sort(key=lambda pair: pair[1], reverse=True)
    selected = []
    for address, score in items[:max_candidates]:
        selected.append(
            {
                "id": address,
                "score": round(score, 4),
                "notes": "observer",
                "seed_params": {"entry_min": 0.60, "flip_min": 0.55},
            }
        )

    if selected:
        CANDIDATES_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            CANDIDATES_PATH.write_text(json.dumps(selected, indent=2))
        except Exception:
            pass
        try:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with LOG_PATH.open("a") as handle:
                handle.write(json.dumps({"ts": _now(), "candidates": len(selected), "source": "observer"}) + "\n")
        except Exception:
            pass
    return selected


def _write_candidates(candidates: List[Dict[str, Any]], source: str, ts: str) -> None:
    try:
        CANDIDATES_PATH.parent.mkdir(parents=True, exist_ok=True)
        CANDIDATES_PATH.write_text(json.dumps(candidates, indent=2))
    except Exception:
        pass
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a") as handle:
            handle.write(json.dumps({"ts": ts, "candidates": len(candidates), "source": source}) + "\n")
    except Exception:
        pass


def run_shadow(window_steps: int = 200) -> Dict[str, Any]:
    """Build a paper-only mirror snapshot from existing on-disk reports."""
    snapshot: Dict[str, Any] = {
        "ts": _now(),
        "window_steps": window_steps,
        "sources": {},
        "candidates": [],
        "notes": "mirror stub",
    }

    cfg = load_observer_cfg()
    min_score = float(cfg.get("min_score", 0.65))
    max_candidates = int(cfg.get("max_candidates", 5))

    hunter_targets = _read_json(HUNTER_TARGETS_PATH)
    hunter_candidates: List[Dict[str, Any]] = []
    if isinstance(hunter_targets, list):
        for address in hunter_targets:
            if isinstance(address, str) and address:
                hunter_candidates.append(
                    {
                        "id": address.lower(),
                        "score": 0.75,
                        "notes": "hunter",
                        "seed_params": {"entry_min": 0.62, "flip_min": 0.57},
                    }
                )
    snapshot["sources"]["hunter_targets"] = len(hunter_candidates)

    observer_candidates = build_candidates_from_observer(min_score=min_score, max_candidates=max_candidates)

    portfolio_pf = _read_json(PORTFOLIO_PF_PATH)
    council = _read_json(COUNCIL_PATH)

    pf_value = None
    if isinstance(portfolio_pf, dict):
        pf_candidate = portfolio_pf.get("portfolio_pf")
        if isinstance(pf_candidate, (int, float)):
            pf_value = float(pf_candidate)
    snapshot["sources"]["portfolio_pf"] = pf_value

    snap_score = 0.0
    if isinstance(pf_value, (int, float)):
        snap_score = max(0.0, min(1.0, pf_value - 0.9))

    candidates: List[Dict[str, Any]] = []
    if pf_value is not None:
        candidates.append(
            {
                "id": "mirror_pf_candidate",
                "score": round(snap_score, 3),
                "notes": "derived from portfolio_pf",
                "seed_params": {"entry_min": 0.60, "flip_min": 0.55},
            }
        )

    if council:
        candidates.append(
            {
                "id": "mirror_council_candidate",
                "score": 0.66,
                "notes": "derived from council deltas",
                "seed_params": {"entry_min": 0.58, "flip_min": 0.53},
            }
        )

    if hunter_candidates:
        final_candidates = hunter_candidates
        source_label = "hunter"
    elif observer_candidates:
        final_candidates = observer_candidates
        source_label = "observer"
    else:
        final_candidates = candidates
        source_label = "stub"
    snapshot["candidates"] = final_candidates

    try:
        MIRROR_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        MIRROR_SNAPSHOT.write_text(json.dumps(snapshot, indent=2))
    except Exception:
        pass

    _write_candidates(final_candidates, source_label, snapshot["ts"])

    return snapshot


def get_candidates(min_score: float = 0.65, max_candidates: int = 5) -> List[Dict[str, Any]]:
    """Return filtered candidates from the current snapshot."""
    try:
        data = json.loads(CANDIDATES_PATH.read_text())
        if not isinstance(data, list):
            raise ValueError
        candidates = data
    except Exception:
        snapshot = _read_json(MIRROR_SNAPSHOT)
        candidates = snapshot.get("candidates", []) if isinstance(snapshot, dict) else []

    filtered: List[Dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        try:
            score = float(item.get("score", 0.0))
        except Exception:
            continue
        if score >= min_score:
            filtered.append(item)
        if len(filtered) >= max_candidates:
            break
    return filtered


def run_once() -> Dict[str, Any]:
    snapshot = run_shadow()
    return {"snapshot": snapshot, "candidates": snapshot.get("candidates", []), "count": len(snapshot.get("candidates", []))}


if __name__ == "__main__":  # manual smoke test
    print(json.dumps(run_shadow(), indent=2))
