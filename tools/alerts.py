#!/usr/bin/env python3
"""
Alerts scanner — Phase 29 (paper-safe).

Scans runtime artifacts under /reports and emits lightweight alerts without
affecting trading logic.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine_alpha.core.paths import REPORTS

TEN_MINUTES = timedelta(minutes=10)
TWENTY_FOUR_HOURS = timedelta(hours=24)

ALERTS_PATH = REPORTS / "alerts.jsonl"
STATE_PATH = REPORTS / "alerts_state.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _jsonl_tail(path: Path, n: int = 1) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text().splitlines()
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for line in lines[-n:]:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _load_state() -> Dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_state(state: Dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def _append_alert(level: str, code: str, details: Dict[str, Any]) -> None:
    payload = {
        "ts": _now().isoformat(),
        "level": level,
        "code": code,
        "details": details,
    }
    ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ALERTS_PATH.open("a") as f:
        f.write(json.dumps(payload) + "\n")


def _staleness_checks() -> List[Dict[str, Any]]:
    alerts: List[Dict[str, Any]] = []
    now = _now()

    orch = _load_json(REPORTS / "orchestrator_snapshot.json")
    orch_ts = _parse_ts(orch.get("ts"))
    if orch_ts is not None:
        age = now - orch_ts
        if age > TEN_MINUTES:
            alerts.append(
                {
                    "level": "warn",
                    "code": "orchestrator_stale",
                    "details": {"age_seconds": int(age.total_seconds())},
                }
            )

    live_loop = _load_json(REPORTS / "live_loop_state.json")
    live_ts = _parse_ts(live_loop.get("ts"))
    if live_ts is not None:
        age = now - live_ts
        if age > TEN_MINUTES:
            alerts.append(
                {
                    "level": "warn",
                    "code": "live_loop_stale",
                    "details": {"age_seconds": int(age.total_seconds())},
                }
            )

    return alerts


def _risk_checks(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    alerts: List[Dict[str, Any]] = []
    now = _now()

    risk = _load_json(REPORTS / "risk_adapter.json")
    band = risk.get("band")
    drawdown = risk.get("drawdown")
    risk_ts = _parse_ts(risk.get("ts"))

    band_state = state.get("band_c") if isinstance(state.get("band_c"), dict) else {}
    band_since_raw = band_state.get("since")
    band_since = _parse_ts(band_since_raw) if band_since_raw else None

    prolonged_active = False

    if band == "C" and isinstance(drawdown, (int, float)) and float(drawdown) > 0.20:
        if band_since is None:
            band_since = risk_ts or now
        duration = now - band_since
        if duration >= TWENTY_FOUR_HOURS:
            prolonged_active = True
            alerts.append(
                {
                    "level": "warn",
                    "code": "prolonged_band_C",
                    "details": {
                        "duration_hours": round(duration.total_seconds() / 3600, 2),
                        "drawdown": float(drawdown),
                    },
                }
            )
        band_state = {
            "since": (band_since or now).isoformat(),
            "last_alert_ts": now.isoformat(),
        }
        state["band_c"] = band_state
    else:
        state.pop("band_c", None)
    state["prolonged_band_c_active"] = prolonged_active

    return alerts


def _trades_checks() -> List[Dict[str, Any]]:
    alerts: List[Dict[str, Any]] = []
    now = _now()

    trades_tail = _jsonl_tail(REPORTS / "trades.jsonl", 1)
    last_trade_ts = None
    if trades_tail:
        last_trade_ts = _parse_ts(trades_tail[0].get("ts"))

    if not last_trade_ts:
        return alerts

    if now - last_trade_ts <= TWENTY_FOUR_HOURS:
        return alerts

    orch = _load_json(REPORTS / "orchestrator_snapshot.json")
    policy = orch.get("policy", {}) if isinstance(orch, dict) else {}
    allow_opens = policy.get("allow_opens")

    portfolio = _load_json(REPORTS / "portfolio" / "portfolio_health.json")
    open_positions = portfolio.get("open_positions") if isinstance(portfolio, dict) else None
    open_total: Optional[float] = None
    if isinstance(open_positions, dict):
        try:
            open_total = sum(abs(float(v)) for v in open_positions.values())
        except Exception:
            open_total = None

    if allow_opens is False and open_total == 0.0:
        alerts.append(
            {
                "level": "info",
                "code": "policy_pause_no_trades",
                "details": {
                    "last_trade_ts": trades_tail[0].get("ts"),
                    "policy_allow_opens": allow_opens,
                },
            }
        )

    return alerts


def main() -> None:
    alerts: List[Dict[str, Any]] = []
    state = _load_state()

    alerts.extend(_staleness_checks())
    alerts.extend(_risk_checks(state))
    alerts.extend(_trades_checks())

    for alert in alerts:
        _append_alert(alert["level"], alert["code"], alert.get("details", {}))

    _write_state(state)

    if alerts:
        codes = ", ".join(alert["code"] for alert in alerts)
        print(f"alerts: {codes}")
    else:
        print("alerts: none")


if __name__ == "__main__":
    main()

