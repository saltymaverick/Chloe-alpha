"""
Policy orchestrator - Phase 22 (paper only)
Derives per-cycle policy flags from governance, risk, and PF state.
"""

from __future__ import annotations

import json

def _load_json_rel(name: str):
    try:
        p = REPORTS / name
        if p.exists():
            t = p.read_text().strip()
            if t:
                return json.loads(t)
    except Exception:
        pass
    return None

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

from engine_alpha.core import pa_policy
from engine_alpha.core.paths import REPORTS
from engine_alpha.core.pa_policy import evaluate_policy

GOV_PATH = REPORTS / "governance_vote.json"
GOV_SNAPSHOT_PATH = REPORTS / "governance_snapshot.json"
RISK_PATH = REPORTS / "risk_adapter.json"
PF_LEGACY_PATH = REPORTS / "pf_local.json"
PF_LIVE_PATH = REPORTS / "pf_local_live.json"
PF_NORM_PATH = REPORTS / "pf_local_norm.json"
PA_PATH = REPORTS / "pa_status.json"
TRADES_PATH = REPORTS / "trades.jsonl"
SNAPSHOT_PATH = REPORTS / "orchestrator_snapshot.json"
LOG_PATH = REPORTS / "orchestrator_log.jsonl"

TEN_MINUTES = 600


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _load_weighted_pf() -> Tuple[float | None, int, str]:
    for path in (PF_LIVE_PATH, PF_NORM_PATH):
        data = _read_json(path)
        if not data:
            continue
        pf_value = data.get("pf")
        count_value = data.get("count")
        pf_float: float | None = None
        try:
            pf_candidate = float(pf_value)
            if math.isfinite(pf_candidate):
                pf_float = pf_candidate
        except Exception:
            pf_float = None
        try:
            count_int = int(count_value)
        except Exception:
            count_int = 0
        if pf_float is not None:
            return pf_float, max(0, count_int), path.name
    legacy = _read_json(PF_LEGACY_PATH)
    if not legacy:
        return None, 0, ""
    try:
        pf_candidate = float(legacy.get("pf", float("nan")))
        pf_value = pf_candidate if math.isfinite(pf_candidate) else None
    except Exception:
        pf_value = None
    try:
        count_int = int(legacy.get("count", 0))
    except Exception:
        count_int = 0
    return pf_value, max(0, count_int), PF_LEGACY_PATH.name if pf_value is not None else ""


def _loss_streak() -> int:
    if not TRADES_PATH.exists():
        return 0
    streak = 0
    try:
        raw_lines = TRADES_PATH.read_text().splitlines()
    except Exception:
        return 0
    tail = raw_lines[-200:]
    for raw in reversed(tail):
        raw = raw.strip()
        if not raw:
            continue
        try:
            trade = json.loads(raw)
        except Exception:
            continue
        event = str(trade.get("type") or trade.get("event") or "").lower()
        if event != "close":
            continue
        pct_value = trade.get("pct", trade.get("pnl_pct"))
        try:
            pct_float = float(pct_value)
        except Exception:
            pct_float = 0.0
        if pct_float < 0:
            streak += 1
            continue
        break
    return streak


def _eval_policy() -> Dict[str, Any]:
    gov_snapshot = _read_json(GOV_SNAPSHOT_PATH)
    gov = gov_snapshot or _read_json(GOV_PATH)
    risk = _read_json(RISK_PATH)
    pf = _read_json(PF_LEGACY_PATH)
    pa_status = _read_json(PA_PATH)

    recommendation = gov.get("rec") or gov.get("recommendation") or "REVIEW"
    sci = gov.get("sci", 0.5)
    risk_band = risk.get("band", "A")
    risk_mult = risk.get("mult", 1.0)
    pa_armed = bool(pa_status.get("armed", False))

    weighted_pf, weighted_count, pf_source = _load_weighted_pf()
    loss_streak = _loss_streak()

    sci = _clamp(float(sci) if isinstance(sci, (int, float)) else 0.5, 0.0, 1.0)
    risk_mult = _clamp(float(risk_mult) if isinstance(risk_mult, (int, float)) else 1.0, 0.5, 1.25)
    pf_local_value = pf.get("pf", 0.0)
    pf_local_value = float(pf_local_value) if isinstance(pf_local_value, (int, float)) else 0.0

    policy_eval = pa_policy.evaluate_policy(
        recommendation,
        weighted_pf,
        weighted_count,
        loss_streak,
        sci,
    )
    risk_ok = risk_band in {"A", "B"}
    allow_opens = bool(policy_eval.get("allow_opens", True)) and risk_ok
    allow_pa = bool(policy_eval.get("allow_pa", False)) and risk_ok
    reason = policy_eval.get("reason", "paper-only")
    inputs_override = policy_eval.get("inputs", {})

    payload = {
        "ts": _now(),
        "inputs": {
            "sci": sci,
            "rec": recommendation,
            "risk_band": risk_band,
            "risk_mult": risk_mult,
            "pf_local": pf_local_value,
            "pf_weighted": weighted_pf,
            "pf_weighted_source": pf_source,
            "count": weighted_count,
            "loss_streak": loss_streak,
            "pa_armed": pa_armed,
        },
        "policy": {
            "allow_opens": bool(allow_opens),
            "allow_pa": bool(allow_pa),
        },
        "notes": f"paper-only; {reason}",
    }
    if isinstance(inputs_override, dict):
        payload["inputs"].update(
            {
                "rec": inputs_override.get("rec", payload["inputs"].get("rec")),
                "pf_weighted": inputs_override.get("pf_weighted", payload["inputs"].get("pf_weighted")),
                "count": inputs_override.get("count", payload["inputs"].get("count")),
                "loss_streak": inputs_override.get(
                    "loss_streak", payload["inputs"].get("loss_streak")
                ),
                "sci": inputs_override.get("sci", payload["inputs"].get("sci")),
            }
        )
    return payload


def cycle() -> Dict[str, Any]:
    payload = _eval_policy()
    SNAPSHOT_PATH.write_text(json.dumps(payload, indent=2))
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(payload) + "\n")
    return payload
