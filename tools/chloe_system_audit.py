#!/usr/bin/env python3
"""
Chloe System Audit (read-only)

Lightweight, operator-facing self-check:
- Verifies loop + recovery lane freshness
- Confirms recovery_v2 closes are flowing into trades.jsonl
- Checks ramp snapshot freshness
- Surfaces PF local scratch status
- Shows active provider cooldowns
"""

from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Tuple

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def _age_minutes(path: Path) -> float:
    try:
        mtime = path.stat().st_mtime
        return max(0.0, (datetime.now(timezone.utc) - datetime.fromtimestamp(mtime, tz=timezone.utc)).total_seconds() / 60.0)
    except Exception:
        return float("inf")


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _parse_ts(ts: Any) -> datetime | None:
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except Exception:
            return None
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            return None
    return None


def _latest_log_ts(path: Path) -> datetime | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            last_line = None
            for line in f:
                if line.strip():
                    last_line = line
        if not last_line:
            return None
        rec = json.loads(last_line)
        return _parse_ts(rec.get("ts"))
    except Exception:
        return None


def _recent_recovery_closes(path: Path, lookback_hours: int = 24) -> Tuple[int, int]:
    """
    Returns (closes_in_window, nonzero_closes_in_window).
    """
    if not path.exists():
        return 0, 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    closes = 0
    nonzero = 0
    try:
        dq = deque(maxlen=5000)
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                dq.append(line)
        for line in dq:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("strategy") != "recovery_v2":
                continue
            if str(rec.get("type") or rec.get("event") or "").lower() != "close":
                continue
            ts = _parse_ts(rec.get("ts") or rec.get("timestamp"))
            if ts is None or ts < cutoff:
                continue
            closes += 1
            try:
                pct = float(rec.get("pct", 0.0))
                if abs(pct) > 1e-6:
                    nonzero += 1
            except Exception:
                continue
    except Exception:
        return 0, 0
    return closes, nonzero


def _recent_closes(path: Path, lane: str, lookback_hours: int = 24) -> int:
    """Count close events for the requested lane within the window."""
    if not path.exists():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    count = 0
    try:
        dq = deque(maxlen=5000)
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                dq.append(line)
        for line in dq:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            evt_type = str(rec.get("type") or rec.get("event") or "").lower()
            if evt_type != "close":
                continue
            tk = (rec.get("trade_kind") or rec.get("strategy") or "").lower()
            rec_lane = "recovery_v2" if tk == "recovery_v2" else ("exploration" if tk == "exploration" else "core")
            if rec_lane != lane:
                continue
            ts = _parse_ts(rec.get("ts") or rec.get("timestamp"))
            if ts is None or ts < cutoff:
                continue
            count += 1
    except Exception:
        return 0
    return count


def _count_recovery_opens(path: Path, lookback_hours: int = 24) -> int:
    """Count recovery_v2 open events in global trades log."""
    if not path.exists():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    count = 0
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                evt_type = str(rec.get("type") or rec.get("event") or "").lower()
                if evt_type != "open":
                    continue
                tk = (rec.get("trade_kind") or rec.get("strategy") or "").lower()
                if tk != "recovery_v2":
                    continue
                ts = _parse_ts(rec.get("ts") or rec.get("timestamp"))
                if ts is None or ts < cutoff:
                    continue
                count += 1
    except Exception:
        return 0
    return count


def _ready_for_normal_v1() -> bool:
    ramp_path = REPORTS / "risk" / "recovery_ramp.json"
    try:
        data = json.loads(ramp_path.read_text())
    except Exception:
        return False
    hysteresis_v1 = data.get("hysteresis") or {}
    needed_ok_ticks = hysteresis_v1.get("needed_ok_ticks") or data.get("needed_ok_ticks") or 0
    ok_ticks = hysteresis_v1.get("ok_ticks") or 0
    allow_recovery_trading = (data.get("allowances") or {}).get("allow_recovery_trading", True)
    return (allow_recovery_trading is False) and needed_ok_ticks and ok_ticks >= needed_ok_ticks


def main() -> int:
    checks = []

    def add(name: str, ok: bool, detail: str) -> None:
        status = "PASS" if ok else "FAIL"
        checks.append(f"[{status}] {name}: {detail}")

    # Loop health freshness (prefer canonical loop/ path, fall back to legacy)
    lh_candidates = [REPORTS / "loop" / "loop_health.json", REPORTS / "loop_health.json"]
    loop_health = next((p for p in lh_candidates if p.exists()), lh_candidates[-1])
    age_lh = _age_minutes(loop_health)
    add("loop_health freshness", age_lh <= 5, f"path={loop_health} age_minutes={age_lh:.1f}")

    # Position state freshness
    pos_path = REPORTS / "position_state.json"
    age_pos = _age_minutes(pos_path)
    add("position_state freshness", age_pos <= 10, f"age_minutes={age_pos:.1f}")

    # Recovery lane log freshness
    lane_log = REPORTS / "loop" / "recovery_lane_v2_log.jsonl"
    ts_lane = _latest_log_ts(lane_log)
    if ts_lane:
        age_lane = (datetime.now(timezone.utc) - ts_lane).total_seconds() / 60.0
        add("recovery_lane_v2 log activity", age_lane <= 15, f"last_ts={ts_lane.isoformat()} age_minutes={age_lane:.1f}")
    else:
        add("recovery_lane_v2 log activity", False, "no recent entries")

    # Recovery closes mirrored to trades
    trades_path = REPORTS / "trades.jsonl"
    closes, nonzero = _recent_recovery_closes(trades_path, lookback_hours=24)
    add(
        "recovery_v2 closes in trades.jsonl (24h)",
        closes > 0,
        f"closes_24h={closes}, nonzero_pct_24h={nonzero}",
    )

    # Core/Exploration close visibility (24h)
    core_closes = _recent_closes(trades_path, lane="core", lookback_hours=24)
    expl_closes = _recent_closes(trades_path, lane="exploration", lookback_hours=24)
    add("core closes in trades.jsonl (24h)", core_closes > 0, f"count={core_closes}")
    add("exploration closes in trades.jsonl (24h)", expl_closes > 0, f"count={expl_closes}")

    # Duplicate recovery opens (should be suppressed)
    recovery_opens = _count_recovery_opens(trades_path, lookback_hours=24)
    add("duplicate recovery opens blocked", recovery_opens <= 1, f"recovery_open_events_24h={recovery_opens}")

    # Recovery exit-only when ready_for_normal
    ready_for_normal = _ready_for_normal_v1()
    try:
        recovery_state = json.loads((REPORTS / "loop" / "recovery_lane_v2_state.json").read_text()) if (REPORTS / "loop" / "recovery_lane_v2_state.json").exists() else {}
    except Exception:
        recovery_state = {}
    open_positions = {
        sym: pos for sym, pos in (recovery_state.get("open_positions") or {}).items()
        if isinstance(pos, dict) and pos.get("direction", 0) != 0
    }
    add(
        "recovery exit-only respected when ready",
        (not ready_for_normal) or len(open_positions) == 0,
        f"ready_for_normal_v1={ready_for_normal}, open_positions={list(open_positions.keys())}",
    )

    # Recovery ramp freshness
    ramp_path = REPORTS / "risk" / "recovery_ramp.json"
    ramp_age = _age_minutes(ramp_path)
    ramp_data = _read_json(ramp_path)
    gates = ramp_data.get("gates", {})
    failing_gates = [k for k, v in gates.items() if v is False]
    add(
        "recovery_ramp.json freshness",
        ramp_age <= 15,
        f"age_minutes={ramp_age:.1f}, failing_gates={failing_gates}",
    )

    # PF local status
    pf_local = _read_json(REPORTS / "pf_local.json")
    pf24 = pf_local.get("pf_24h")
    scratch24 = pf_local.get("scratch_only_24h")
    lossless24 = pf_local.get("lossless_24h")
    def _pf_ok(val: Any) -> bool:
        try:
            if val == "inf":
                return True
            return float(val) is not None
        except Exception:
            return False
    add(
        "pf_local 24h",
        _pf_ok(pf24),
        f"pf_24h={pf24}, scratch_only_24h={scratch24}, lossless_24h={lossless24}",
    )

    # Provider cooldowns
    cooldown = _read_json(REPORTS / "provider_cooldown.json")
    now = datetime.now(timezone.utc)
    active = []
    for prov, entry in (cooldown or {}).items():
        ts = entry.get("cooldown_until_ts")
        parsed = _parse_ts(ts)
        if parsed and parsed > now:
            active.append(f"{prov}@{ts}")
    # Cooldowns are WARN if any active (fallbacks may still work); FAIL only if all providers are stale would be higher level.
    if len(active) == 0:
        add("provider cooldowns", True, "active=[]")
    else:
        checks.append(f"[WARN] provider cooldowns active: {active}")

    print("Chloe System Audit Summary")
    print("==========================")
    for line in checks:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

