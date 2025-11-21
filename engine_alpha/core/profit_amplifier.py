"""
Profit Amplifier - Phase 5 (Paper only)
Controls arming based on PF gates; provides risk multiplier (placeholder).
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

import yaml

from engine_alpha.core.paths import REPORTS, CONFIG


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def _read_latest_incident_safe_mode() -> bool:
    incidents = REPORTS / "incidents.jsonl"
    if not incidents.exists():
        return False
    try:
        with open(incidents, "r") as f:
            lines = f.readlines()
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("safe_mode") is True:
                return True
        return False
    except Exception:
        return False


def _pf_from_last_n_trades(trades_path: Path, n: int) -> float:
    if not trades_path.exists():
        return 1.0
    try:
        closes: List[Dict[str, Any]] = []
        with open(trades_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except Exception:
                    continue
                if evt.get("event") == "CLOSE":
                    closes.append(evt)
        if not closes:
            return 1.0
        closes = closes[-n:]
        pos = sum(float(t.get("pnl_pct", 0.0)) for t in closes if float(t.get("pnl_pct", 0.0)) > 0)
        neg = -sum(float(t.get("pnl_pct", 0.0)) for t in closes if float(t.get("pnl_pct", 0.0)) < 0)
        if neg <= 0:
            return 999.0 if pos > 0 else 1.0
        return pos / neg
    except Exception:
        return 1.0


def _load_gates() -> Dict[str, Any]:
    gates_path = CONFIG / "gates.yaml"
    if gates_path.exists():
        try:
            with open(gates_path, "r") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            pass
    # Defaults
    return {
        "entry_exit": {
            "entry_min_conf": {"trend": 0.70, "chop": 0.72, "high_vol": 0.71},
            "exit_min_conf": 0.30,
            "reverse_min_conf": 0.60,
        },
        "profit_amplifier": {
            "arm_gate": {"pf_local": 1.05, "trades": 20},
            "disarm_gate": {"pf_local": 1.00, "trades": 10},
            "gates_triplet": [0.08, 0.05, 180],
        },
    }


def evaluate(pa_path: Path = REPORTS / "pa_status.json") -> Dict[str, Any]:
    """
    Evaluate PA arming/disarming and persist status.
    - Reads pf_local.json and pf_live.json
    - Reads incidents for safe_mode
    - Applies gates: arm/disarm per spec
    - Writes pa_status.json
    """
    gates = _load_gates()
    pa_gates = gates.get("profit_amplifier", {})
    arm_gate = pa_gates.get("arm_gate", {"pf_local": 1.05, "trades": 20})
    disarm_gate = pa_gates.get("disarm_gate", {"pf_local": 1.00, "trades": 10})
    gates_triplet = pa_gates.get("gates_triplet", [0.08, 0.05, 180])

    pf_local_data = _read_json(REPORTS / "pf_local.json") or {"pf": 1.0, "count": 0}
    pf_live_data = _read_json(REPORTS / "pf_live.json") or {"pf": 1.0, "count": 0}

    pf_local = float(pf_local_data.get("pf", 1.0))
    pf_live = float(pf_live_data.get("pf", 1.0))
    count = int(pf_local_data.get("count", pf_local_data.get("total_trades", 0)))

    safe_mode = _read_latest_incident_safe_mode()

    # Load previous state if exists
    prev = _read_json(pa_path) or {}
    armed = bool(prev.get("armed", False))
    last_change_ts = prev.get("last_change_ts")
    reason = prev.get("reason", "init")

    now_ts = datetime.now(timezone.utc).isoformat()

    # Disarm conditions first (highest priority)
    disarm_due_to_safe = safe_mode is True
    pf_last10 = _pf_from_last_n_trades(REPORTS / "trades.jsonl", disarm_gate.get("trades", 10))
    disarm_due_to_pf10 = pf_last10 < float(disarm_gate.get("pf_local", 1.00))

    if disarm_due_to_safe or disarm_due_to_pf10:
        if armed:
            armed = False
            last_change_ts = now_ts
            reason = "SAFE_MODE" if disarm_due_to_safe else "PF_LOCAL_10_BELOW_1.00"
    else:
        # Arm condition
        if (pf_local >= float(arm_gate.get("pf_local", 1.05))) and (count >= int(arm_gate.get("trades", 20))):
            if not armed:
                armed = True
                last_change_ts = now_ts
                reason = "ARM_GATE_MET"

    state = {
        "armed": armed,
        "last_change_ts": last_change_ts or now_ts,
        "reason": reason,
        "pf_local": pf_local,
        "pf_live": pf_live,
        "count": count,
        "gates_triplet": gates_triplet,
        "safe_mode": safe_mode,
    }

    pa_path.parent.mkdir(parents=True, exist_ok=True)
    with open(pa_path, "w") as f:
        json.dump(state, f, indent=2)

    return state


def risk_multiplier(pa_status_path: Path = REPORTS / "pa_status.json") -> float:
    """Return current risk multiplier (1.0 when disarmed; 1.0 when armed for paper)."""
    state = _read_json(pa_status_path) or {}
    return 1.0 if not state.get("armed") else 1.0  # Placeholder for future scaling
