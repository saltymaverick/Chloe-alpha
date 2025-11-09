"""
Policy orchestrator - Phase 22 (paper only)
Derives per-cycle policy flags from governance, risk, and PF state.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from engine_alpha.core.paths import REPORTS

GOV_PATH = REPORTS / "governance_vote.json"
RISK_PATH = REPORTS / "risk_adapter.json"
PF_PATH = REPORTS / "pf_local.json"
PA_PATH = REPORTS / "pa_status.json"
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


def _eval_policy() -> Dict[str, Any]:
    gov = _read_json(GOV_PATH)
    risk = _read_json(RISK_PATH)
    pf_local = _read_json(PF_PATH)
    pa_status = _read_json(PA_PATH)

    recommendation = gov.get("recommendation", "REVIEW")
    sci = gov.get("sci", 0.5)
    risk_band = risk.get("band", "A")
    risk_mult = risk.get("mult", 1.0)
    pf = pf_local.get("pf", 0.0)
    count = pf_local.get("count", 0)
    pa_armed = bool(pa_status.get("armed", False))

    sci = _clamp(float(sci) if isinstance(sci, (int, float)) else 0.5, 0.0, 1.0)
    risk_mult = _clamp(float(risk_mult) if isinstance(risk_mult, (int, float)) else 1.0, 0.5, 1.25)
    pf = max(0.0, float(pf) if isinstance(pf, (int, float)) else 0.0)
    count = max(0, int(count) if isinstance(count, (int, float)) else 0)

    allow_opens = recommendation != "PAUSE" and risk_band in {"A", "B"}
    allow_pa = (pf >= 1.05 and count >= 20 and risk_band in {"A", "B"} and sci >= 0.60)

    payload = {
        "ts": _now(),
        "inputs": {
            "sci": sci,
            "rec": recommendation,
            "risk_band": risk_band,
            "risk_mult": risk_mult,
            "pf_local": pf,
            "count": count,
            "pa_armed": pa_armed,
        },
        "policy": {
            "allow_opens": bool(allow_opens),
            "allow_pa": bool(allow_pa),
        },
        "notes": "paper-only",
    }
    return payload


def cycle() -> Dict[str, Any]:
    payload = _eval_policy()
    SNAPSHOT_PATH.write_text(json.dumps(payload, indent=2))
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(payload) + "\n")
    return payload
