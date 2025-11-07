#!/usr/bin/env python3
"""
Acceptance check - Phase 13
Runs high-level health gating across reports and ops probes.
"""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List

import yaml

from engine_alpha.core.paths import REPORTS, CONFIG

MIN_GATE = 0.40
MAX_GATE = 0.80

SUMMARY_NAME = "acceptance_summary.json"
MAX_CLOCK_SKEW_MS = 500
MAX_MEDIAN_LATENCY_MS = 300
DREAM_MAX_AGE = timedelta(hours=36)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r") as f:
            return json.load(f)
    except Exception:
        return {}


def _read_jsonl_tail(path: Path, lines: int = 1) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r") as f:
            rows = f.readlines()[-lines:]
        out: List[Dict[str, Any]] = []
        for row in rows:
            row = row.strip()
            if not row:
                continue
            try:
                out.append(json.loads(row))
            except Exception:
                continue
        return out
    except Exception:
        return []


def _within_hours(ts: str, max_age: timedelta) -> bool:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - dt <= max_age
    except Exception:
        return False


def _section_feeds() -> Dict[str, Any]:
    feeds_path = REPORTS / "feeds_health.json"
    data = _read_json(feeds_path)
    ok_exchanges = []
    details: Dict[str, Any] = {}

    for exchange in ("binance", "bybit", "okx"):
        section = data.get(exchange, {})
        enabled = section.get("enabled", False)
        info = {"enabled": enabled, "ok": False}
        if enabled:
            time_info = section.get("time", {})
            symbols_info = section.get("symbols", {}).get("symbols", {})
            latencies = [entry.get("latency_ms") for entry in symbols_info.values() if entry.get("ok")]
            latency_median = None
            if latencies:
                latency_median = statistics.median(latencies)
            clock_skew = time_info.get("clock_skew_ms")
            time_ok = bool(time_info.get("ok")) and clock_skew is not None and clock_skew < MAX_CLOCK_SKEW_MS
            latency_ok = latency_median is not None and latency_median < MAX_MEDIAN_LATENCY_MS
            exchange_ok = time_ok and latency_ok
            info.update(
                {
                    "clock_skew_ms": clock_skew,
                    "median_latency_ms": latency_median,
                    "time_ok": time_ok,
                    "latency_ok": latency_ok,
                    "ok": exchange_ok,
                }
            )
            if exchange_ok:
                ok_exchanges.append(exchange)
        details[exchange] = info

    overall_ok = bool(ok_exchanges)
    return {"ok": overall_ok, "details": details}


def _section_pf_pa() -> Dict[str, Any]:
    pf_local = _read_json(REPORTS / "pf_local.json")
    pf_live = _read_json(REPORTS / "pf_live.json")
    pa_status = _read_json(REPORTS / "pa_status.json")

    pf_local_value = pf_local.get("pf")
    pf_live_value = pf_live.get("pf")
    pf_numeric = isinstance(pf_local_value, (int, float)) and isinstance(pf_live_value, (int, float))

    count = pa_status.get("count") or pf_local.get("count") or pf_local.get("total_trades") or 0
    armed = pa_status.get("armed")
    pf_gate = pf_local_value is not None and pf_local_value >= 1.05 and count >= 20
    gate_consistent = (armed is True) if pf_gate else True

    ok = bool(pf_numeric and gate_consistent)
    return {
        "ok": ok,
        "details": {
            "pf_local": pf_local_value,
            "pf_live": pf_live_value,
            "armed": armed,
            "count": count,
            "gate_consistent": gate_consistent,
        },
    }


def _load_guard_cap() -> int:
    cfg = CONFIG / "asset_list.yaml"
    try:
        with cfg.open("r") as f:
            data = yaml.safe_load(f) or {}
        guard = data.get("guard", {})
        return int(guard.get("net_exposure_cap", 2))
    except Exception:
        return 2


def _section_portfolio() -> Dict[str, Any]:
    pf_portfolio = _read_json(REPORTS / "portfolio" / "portfolio_pf.json")
    health = _read_json(REPORTS / "portfolio" / "portfolio_health.json")

    pf_value = pf_portfolio.get("portfolio_pf")
    pf_numeric = isinstance(pf_value, (int, float))

    corr_blocks = int(health.get("corr_blocks", 0))
    exposure_blocks = int(health.get("exposure_blocks", 0))
    open_positions = health.get("open_positions", {})
    net_cap = _load_guard_cap()
    net_exposure = sum(open_positions.values()) if open_positions else 0
    exposure_ok = abs(net_exposure) <= net_cap
    blocks_ok = (corr_blocks + exposure_blocks) >= 1

    ok = bool(pf_numeric and exposure_ok and blocks_ok)
    return {
        "ok": ok,
        "details": {
            "portfolio_pf": pf_value,
            "corr_blocks": corr_blocks,
            "exposure_blocks": exposure_blocks,
            "net_exposure": net_exposure,
            "cap": net_cap,
            "exposure_ok": exposure_ok,
            "blocks_ok": blocks_ok,
        },
    }


def _section_dream() -> Dict[str, Any]:
    log_tail = _read_jsonl_tail(REPORTS / "dream_log.jsonl", lines=1)
    proposals = _read_json(REPORTS / "dream_proposals.json")
    if not log_tail:
        return {"ok": False, "details": {"error": "no_dream_entries"}}
    ts = log_tail[0].get("ts")
    fresh = _within_hours(ts, DREAM_MAX_AGE)
    ok = bool(fresh and proposals)
    return {"ok": ok, "details": {"ts": ts, "fresh": fresh, "proposal_present": bool(proposals)}}


def _section_mirror() -> Dict[str, Any]:
    snapshot = _read_json(REPORTS / "mirror_snapshot.json")
    ok = bool(snapshot.get("ts"))
    return {"ok": ok, "details": {"ts": snapshot.get("ts")}}


def _section_ops() -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "tools.ops_health"],
            capture_output=True,
            text=True,
            check=False,
        )
        data = json.loads(proc.stdout.strip()) if proc.stdout else {}
        ok = bool(data.get("pf_ok") and data.get("trades_ok") and data.get("dream_ok"))
        return {"ok": ok, "details": data}
    except Exception as exc:
        return {"ok": False, "details": {"error": str(exc)}}


def _section_accounting() -> Dict[str, Any]:
    pf_live_adj = _read_json(REPORTS / "pf_live_adj.json")
    pf_local_adj = _read_json(REPORTS / "pf_local_adj.json")
    equity_path = REPORTS / "equity_curve.jsonl"
    tail = _read_jsonl_tail(equity_path, lines=1)

    pf_live_val = pf_live_adj.get("pf")
    pf_local_val = pf_local_adj.get("pf")
    pf_ok = isinstance(pf_live_val, (int, float)) and isinstance(pf_local_val, (int, float))

    lines = 0
    if equity_path.exists():
        try:
            with equity_path.open("r") as f:
                lines = sum(1 for _ in f)
        except Exception:
            lines = 0
    curve_ok = lines >= 10

    ts = tail[0].get("ts") if tail else None
    fresh = _within_hours(ts, DREAM_MAX_AGE) if ts else False

    ok = all([pf_ok, curve_ok, fresh])
    details = {
        "pf_adj_live": pf_live_val,
        "pf_adj_local": pf_local_val,
        "points": lines,
        "fresh_hours": None,
        "curve_ok": curve_ok,
        "pf_ok": pf_ok,
        "fresh": fresh,
    }
    if ts:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            delta = datetime.now(timezone.utc) - dt
            details["fresh_hours"] = round(delta.total_seconds() / 3600, 2)
        except Exception:
            details["fresh_hours"] = None
    return {"ok": ok, "details": details}


def _section_confidence() -> Dict[str, Any]:
    path = REPORTS / "confidence_tune.jsonl"
    entries = _read_jsonl_tail(path, lines=3)
    if not entries:
        return {"ok": False, "details": {"error": "no_confidence_entries"}}
    ok = True
    detail_list = []
    for entry in entries:
        regime = entry.get("regime")
        delta = entry.get("delta")
        new_gate = entry.get("new_gate")
        baseline = entry.get("baseline")
        valid = (
            isinstance(delta, (int, float))
            and isinstance(new_gate, (int, float))
            and abs(delta) <= 0.10
            and MIN_GATE <= new_gate <= MAX_GATE
        )
        ok = ok and valid
        detail_list.append({
            "regime": regime,
            "baseline": baseline,
            "delta": delta,
            "new_gate": new_gate,
            "valid": valid,
        })
    return {"ok": ok, "details": detail_list}


def _section_promotion() -> Dict[str, Any]:
    path = REPORTS / "promotion_proposals.jsonl"
    tail = _read_jsonl_tail(path, 1)
    if not tail:
        return {"ok": False, "details": {"error": "no_proposals"}}
    entry = tail[0]
    recommendation = entry.get("recommendation")
    ok = recommendation in {"PROMOTE", "HOLD"}
    return {"ok": ok, "details": entry}


def _section_sandbox() -> Dict[str, Any]:
    status_path = REPORTS / "sandbox" / "sandbox_status.json"
    runs_path = REPORTS / "sandbox" / "sandbox_runs.jsonl"
    if not status_path.exists():
        proposals = REPORTS / "promotion_proposals.jsonl"
        if runs_path.exists():
            return {"ok": False, "details": {"error": "status_missing"}}
        if not proposals.exists():
            return {"ok": True, "details": {"note": "no sandbox activity"}}
        return {"ok": True, "details": {"note": "no sandbox activity"}}
    try:
        status = json.loads(status_path.read_text())
    except Exception:
        return {"ok": False, "details": {"error": "status_unreadable"}}
    allowed = {"queued", "running", "complete"}
    invalid = {sid: st for sid, st in status.items() if st not in allowed}
    ok = not invalid
    details = {"states": status, "invalid": invalid}
    if runs_path.exists():
        details["last_run"] = _read_jsonl_tail(runs_path, 1)
    return {"ok": ok, "details": details}


def main() -> int:
    sections = {
        "feeds": _section_feeds(),
        "pf_pa": _section_pf_pa(),
        "portfolio": _section_portfolio(),
        "dream": _section_dream(),
        "mirror": _section_mirror(),
        "ops": _section_ops(),
        "accounting": _section_accounting(),
        "confidence": _section_confidence(),
        "promotion": _section_promotion(),
        "sandbox": _section_sandbox(),
    }
    overall = all(section.get("ok") for section in sections.values())
    summary = {"ts": _iso_now(), "PASS": overall, "sections": sections}
    summary_path = REPORTS / SUMMARY_NAME
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
