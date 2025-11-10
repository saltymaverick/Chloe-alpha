#!/usr/bin/env python3
"""
Live loop runner - Phase 25
Pulls paper-live signals and advances the orchestrator-gated loop.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict

import yaml

from engine_alpha.core.paths import CONFIG, REPORTS
from engine_alpha.data.live_prices import get_live_ohlcv
from engine_alpha.loop.autonomous_trader import run_step_live
from engine_alpha.reflect.trade_analysis import update_pf_reports

STATE_PATH = REPORTS / "live_loop_state.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_cfg() -> Dict[str, Any]:
    path = CONFIG / "live.yaml"
    defaults = {"symbols": ["ETHUSDT"], "timeframe": "1h", "interval_sec": 60, "limit": 200}
    if not path.exists():
        return defaults
    try:
        with path.open("r") as f:
            data = yaml.safe_load(f) or {}
        live_cfg = data.get("live", {})
        return {
            "symbols": live_cfg.get("symbols", defaults["symbols"]) or defaults["symbols"],
            "timeframe": live_cfg.get("timeframe", defaults["timeframe"]),
            "interval_sec": live_cfg.get("interval_sec", defaults["interval_sec"]),
            "limit": int(live_cfg.get("limit", defaults["limit"])),
        }
    except Exception:
        return defaults


def _read_state() -> Dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        with STATE_PATH.open("r") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_state(payload: Dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(payload, indent=2))


def _within_seconds(ts: str, max_seconds: int) -> bool:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - dt
        return delta.total_seconds() <= max_seconds
    except Exception:
        return False


def main() -> int:
    cfg = _load_cfg()
    symbol = cfg["symbols"][0] if cfg.get("symbols") else "ETHUSDT"
    timeframe = cfg.get("timeframe", "1h")
    limit = int(cfg.get("limit", 200))

    try:
        rows = get_live_ohlcv(symbol, timeframe, limit=limit)
    except Exception as exc:  # pragma: no cover - network errors
        print(f"LIVE-SOAK: fetch_failed error={exc}")
        return 0

    if not rows:
        print("LIVE-SOAK: no data")
        return 0

    bar_ts = rows[-1].get("ts")
    if not isinstance(bar_ts, str):
        print("LIVE-SOAK: invalid bar timestamp")
        return 0

    state = _read_state()
    last_ts = state.get("ts")

    if last_ts and bar_ts == last_ts:
        state["heartbeat_ts"] = _now()
        _write_state(state)
        print(f"LIVE-SOAK: heartbeat ts={bar_ts}")
        return 0

    try:
        result = run_step_live(symbol=symbol, timeframe=timeframe, limit=limit, bar_ts=bar_ts)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"LIVE-SOAK: step_failed error={exc}")
        return 0

    update_pf_reports(
        REPORTS / "trades.jsonl",
        REPORTS / "pf_local.json",
        REPORTS / "pf_live.json",
    )

    policy = result.get("policy", {})
    final = result.get("final", {})
    risk_adapter = result.get("risk_adapter", {})

    payload = {
        "ts": bar_ts,
        "symbol": symbol,
        "timeframe": timeframe,
        "policy": {
            "allow_opens": bool(policy.get("allow_opens", True)),
            "allow_pa": bool(policy.get("allow_pa", True)),
        },
        "final": {
            "dir": int(final.get("dir", 0)) if isinstance(final.get("dir"), (int, float)) else 0,
            "conf": float(final.get("conf", 0.0)) if isinstance(final.get("conf"), (int, float)) else 0.0,
        },
        "risk_band": risk_adapter.get("band"),
        "heartbeat_ts": _now(),
    }

    _write_state(payload)
    print(
        "LIVE-SOAK: ts={ts} dir={dir} conf={conf:.4f} allow_opens={opens}".format(
            ts=bar_ts,
            dir=payload["final"]["dir"],
            conf=payload["final"]["conf"],
            opens=payload["policy"]["allow_opens"],
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

