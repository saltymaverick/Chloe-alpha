"""Promotion manager - evaluates mirror/evolver outputs for promotion proposals."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from engine_alpha.core.paths import REPORTS

CANDIDATES_PATH = REPORTS / "mirror_candidates.json"
SANDBOX_RUNS = REPORTS / "sandbox" / "sandbox_runs.jsonl"
EVOLVER_SNAPSHOT = REPORTS / "evolver_snapshot.json"
PROPOSALS_OUT = REPORTS / "promotion_proposals.jsonl"

WINDOW = timedelta(hours=48)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        for raw in path.read_text().splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    except Exception:
        return []
    return rows


def _cutoff() -> datetime:
    return datetime.now(timezone.utc) - WINDOW


def _recent_ids() -> set[str]:
    existing = _load_jsonl(PROPOSALS_OUT)
    cutoff = _cutoff()
    ids: set[str] = set()
    for entry in existing:
        ts = entry.get("ts")
        try:
            ts_dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except Exception:
            ts_dt = None
        if ts_dt and ts_dt >= cutoff:
            cand_id = entry.get("id")
            if isinstance(cand_id, str):
                ids.add(cand_id)
    return ids


def _sandbox_metrics(candidate_id: str) -> Optional[Dict[str, Any]]:
    runs = _load_jsonl(SANDBOX_RUNS)
    matched: Optional[Dict[str, Any]] = None
    for entry in runs[::-1]:  # reversed to prioritise latest
        if not isinstance(entry, dict):
            continue
        if entry.get("id") == candidate_id or entry.get("child") == candidate_id or entry.get("source_id") == candidate_id:
            matched = entry
            break
    return matched


def _evolver_metrics(candidate_id: str) -> Optional[Dict[str, Any]]:
    snapshot = _load_json(EVOLVER_SNAPSHOT)
    if not snapshot:
        return None
    best = snapshot.get("best")
    if isinstance(best, dict) and best.get("id") == candidate_id:
        return best
    tested = snapshot.get("tested_items")
    if isinstance(tested, list):
        for entry in tested[::-1]:
            if isinstance(entry, dict) and entry.get("id") == candidate_id:
                return entry
    return None


def _evaluate_candidate(candidate: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    cand_id = candidate.get("id")
    sandbox = _sandbox_metrics(cand_id)
    evolver = _evolver_metrics(cand_id)
    evidence = sandbox or evolver or {}

    pf_cf = evidence.get("pf_cf") or evidence.get("pf") or candidate.get("score")
    trades = evidence.get("trades") or evidence.get("trade_count")
    uplift = evidence.get("uplift") or evidence.get("delta")

    try:
        pf_val = float(pf_cf)
    except Exception:
        pf_val = None
    try:
        trades_val = int(trades)
    except Exception:
        trades_val = None
    try:
        uplift_val = float(uplift)
    except Exception:
        uplift_val = None

    promotable = (
        pf_val is not None and pf_val >= 1.05
        and trades_val is not None and trades_val >= 100
        and (uplift_val is None or uplift_val >= 0.03)
    )

    recommendation = "PROMOTE" if promotable else "HOLD"
    reason = "meets_threshold" if promotable else "insufficient_metrics"
    return (
        {
            "pf_cf": pf_val,
            "trades": trades_val,
            "uplift": uplift_val,
            "source": "sandbox" if sandbox else ("evolver" if evolver else "mirror"),
        },
        {
            "recommendation": recommendation,
            "reason": reason,
        },
    )


def run_once() -> Dict[str, Any]:
    candidates = []
    try:
        data = json.loads(CANDIDATES_PATH.read_text()) if CANDIDATES_PATH.exists() else []
        if isinstance(data, list):
            candidates = [c for c in data if isinstance(c, dict)]
    except Exception:
        candidates = []

    recent_ids = _recent_ids()
    proposals: List[Dict[str, Any]] = []
    promote_count = 0

    for candidate in candidates:
        cand_id = candidate.get("id")
        if not isinstance(cand_id, str):
            continue
        if cand_id in recent_ids:
            continue
        evidence, decision = _evaluate_candidate(candidate)
        payload = {
            "ts": _now(),
            "id": cand_id,
            "source": evidence.get("source", "mirror"),
            "pf_cf": evidence.get("pf_cf"),
            "uplift": evidence.get("uplift"),
            "trades": evidence.get("trades"),
            "recommendation": decision["recommendation"],
            "reason": decision["reason"],
        }
        proposals.append(payload)
        if decision["recommendation"] == "PROMOTE":
            promote_count += 1

    if proposals:
        PROPOSALS_OUT.parent.mkdir(parents=True, exist_ok=True)
        try:
            with PROPOSALS_OUT.open("a") as handle:
                for proposal in proposals:
                    handle.write(json.dumps(proposal) + "\n")
        except Exception:
            pass

    return {
        "generated": len(proposals),
        "promote": promote_count,
        "hold": len(proposals) - promote_count,
    }


if __name__ == "__main__":  # manual smoke test
    print(json.dumps(run_once(), indent=2))
