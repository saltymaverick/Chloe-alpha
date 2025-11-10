#!/usr/bin/env python3
"""Auto-apply staged updates for vetted Dream proposals (paper-only)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from engine_alpha.core.paths import CONFIG, REPORTS

DREAM_SCORED = REPORTS / "dream_proposals_scored.jsonl"
GOVERNANCE_VOTE = REPORTS / "governance_vote.json"
RISK_ADAPTER = REPORTS / "risk_adapter.json"
AUTO_APPLY_AUDIT = REPORTS / "auto_apply_audit.jsonl"
GATES_CALIBRATED = CONFIG / "gates_calibrated.yaml"
COUNCIL_CALIBRATED = CONFIG / "council_calibrated.yaml"


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    items: List[Dict[str, Any]] = []
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
                items.append(obj)
    except Exception:
        return []
    return items


def _write_yaml(path: Path, payload: Dict[str, Any]) -> None:
    try:
        import yaml
    except Exception:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as handle:
            yaml.safe_dump(payload, handle, sort_keys=False)
    except Exception:
        pass


def _append_audit(entry: Dict[str, Any]) -> None:
    AUTO_APPLY_AUDIT.parent.mkdir(parents=True, exist_ok=True)
    try:
        with AUTO_APPLY_AUDIT.open("a") as handle:
            handle.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _parse_ts(ts: Any) -> datetime | None:
    if not isinstance(ts, str):
        return None
    candidate = ts.strip()
    try:
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        return datetime.fromisoformat(candidate)
    except Exception:
        return None


def find_candidates(window_hours: int = 48) -> List[Dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    scored = _read_jsonl(DREAM_SCORED)
    candidates: List[Dict[str, Any]] = []
    for item in scored:
        ts = _parse_ts(item.get("ts"))
        if ts is None or ts < cutoff:
            continue
        uplift = item.get("uplift")
        if not isinstance(uplift, (int, float)) or uplift < 0.03:
            continue
        trades_tested = item.get("trades_tested")
        if trades_tested is not None and (not isinstance(trades_tested, (int, float)) or trades_tested < 100):
            continue
        variance_ok = item.get("variance_ok")
        if variance_ok is False:
            continue
        kind = item.get("kind")
        payload = item.get("payload")
        if kind not in {"gates", "weights"} or not isinstance(payload, dict):
            continue
        candidates.append(item)
    return candidates


def stage_candidate(item: Dict[str, Any]) -> Dict[str, Any]:
    ts_now = datetime.now(timezone.utc).isoformat()
    kind = item.get("kind")
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    evidence = {
        "pf_cf": item.get("pf_cf"),
        "uplift": item.get("uplift"),
        "trades_tested": item.get("trades_tested"),
        "variance_ok": item.get("variance_ok"),
    }

    result = "staged"
    reason = "ok"
    try:
        if kind == "gates":
            existing = {}
            if GATES_CALIBRATED.exists():
                try:
                    import yaml
                    existing = yaml.safe_load(GATES_CALIBRATED.read_text()) or {}
                except Exception:
                    existing = {}
            merged = existing.copy()
            merged.update(payload)
            _write_yaml(GATES_CALIBRATED, merged)
        elif kind == "weights":
            existing = {}
            if COUNCIL_CALIBRATED.exists():
                try:
                    import yaml
                    existing = yaml.safe_load(COUNCIL_CALIBRATED.read_text()) or {}
                except Exception:
                    existing = {}
            merged = existing.copy()
            merged.update(payload)
            _write_yaml(COUNCIL_CALIBRATED, merged)
        else:
            result = "skipped"
            reason = "unsupported_kind"
    except Exception as exc:  # pragma: no cover - defensive
        result = "skipped"
        reason = f"error:{exc}"

    audit_entry = {
        "ts": ts_now,
        "kind": kind,
        "payload": payload,
        "evidence": evidence,
        "result": result,
        "reason": reason,
    }
    _append_audit(audit_entry)
    return audit_entry


def run_once(window_hours: int = 48) -> Dict[str, Any]:
    governance = _read_json(GOVERNANCE_VOTE)
    risk = _read_json(RISK_ADAPTER)

    rec = governance.get("recommendation")
    sci = governance.get("sci")
    risk_band = risk.get("band")

    governance_ok = rec == "GO"
    risk_ok = risk_band in {"A", "B"}

    candidates = find_candidates(window_hours=window_hours)
    checked = len(candidates)
    staged = 0
    skipped = 0
    last_ts: str | None = None

    if not governance_ok or not risk_ok:
        for item in candidates:
            audit_entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "kind": item.get("kind"),
                "payload": item.get("payload"),
                "evidence": {
                    "pf_cf": item.get("pf_cf"),
                    "uplift": item.get("uplift"),
                    "trades_tested": item.get("trades_tested"),
                },
                "governance": {"rec": rec, "sci": sci},
                "risk": {"band": risk_band},
                "result": "skipped",
                "reason": "gate_failed",
            }
            _append_audit(audit_entry)
        return {
            "checked": checked,
            "staged": 0,
            "skipped": checked,
            "governance_ok": governance_ok,
            "risk_ok": risk_ok,
            "last_ts": last_ts,
        }

    for item in candidates:
        audit_entry = stage_candidate(item)
        audit_entry.setdefault("governance", {"rec": rec, "sci": sci})
        audit_entry.setdefault("risk", {"band": risk_band})
        _append_audit(audit_entry)
        if audit_entry.get("result") == "staged":
            staged += 1
        else:
            skipped += 1
        item_ts = item.get("ts")
        if isinstance(item_ts, str) and (last_ts is None or item_ts > last_ts):
            last_ts = item_ts

    return {
        "checked": checked,
        "staged": staged,
        "skipped": skipped,
        "governance_ok": governance_ok,
        "risk_ok": risk_ok,
        "last_ts": last_ts,
    }
