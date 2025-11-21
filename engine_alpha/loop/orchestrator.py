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
import os
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
        content = path.read_text().strip()
        if not content:
            return {}
        return json.loads(content)
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


def _count_closed_trades() -> int:
    """Count total number of closed trades in trades.jsonl."""
    if not TRADES_PATH.exists():
        return 0
    count = 0
    try:
        raw_lines = TRADES_PATH.read_text().splitlines()
    except Exception:
        return 0
    for raw in raw_lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            trade = json.loads(raw)
        except Exception:
            continue
        event = str(trade.get("type") or trade.get("event") or "").lower()
        if event == "close":
            count += 1
    return count


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
    
    # PAPER-mode override: allow opens when there are no closed trades yet
    # (unless in a hard-block mode; risk_ok is respected but None risk_band is acceptable for fresh reset)
    closed_trades = _count_closed_trades()
    hard_block_modes = {"PAUSE", "BLOCK", "HALT"}
    is_paper_mode = True  # This orchestrator is paper-only per module comment
    risk_ok_or_unset = risk_ok or risk_band is None  # Allow if risk_ok OR risk_band not yet set (fresh reset)
    if is_paper_mode and closed_trades == 0 and recommendation not in hard_block_modes and risk_ok_or_unset:
        allow_opens = True
        print("POLICY-DEBUG: forcing allow_opens=True for fresh PAPER reset (0 closes).")
    
    # PAPER-mode override: allow cautious trading even when risk_band=C or PF<1.0
    # (unless in a hard-block mode; keep risk_band and mult as computed, keep allow_pa unchanged)
    risk_drawdown = risk.get("drawdown")
    risk_drawdown_value = float(risk_drawdown) if isinstance(risk_drawdown, (int, float)) else None
    pf_value = weighted_pf if weighted_pf is not None else pf_local_value
    dd_value = risk_drawdown_value if risk_drawdown_value is not None else 0.0
    if is_paper_mode and recommendation not in hard_block_modes:
        allow_opens = True
        print("POLICY-DEBUG: PAPER override: allow_opens=True despite band=%s PF=%s dd=%s" % (risk_band, pf_value, dd_value))
    
    # PAPER-mode manual override: FORCE_PAPER_OPENS
    try:
        force_opens = os.getenv("FORCE_PAPER_OPENS", "0") == "1"
    except Exception:
        force_opens = False
    
    # Only apply in PAPER mode, and only if REC is not a hard-block state
    if is_paper_mode and force_opens:
        if recommendation not in hard_block_modes:
            allow_opens = True
            print(f"POLICY-DEBUG: FORCE_PAPER_OPENS=1 -> allow_opens=True in PAPER mode (rec={recommendation}, band={risk_band})")

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
