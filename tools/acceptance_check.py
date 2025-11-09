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

from engine_alpha.core.paths import REPORTS, CONFIG, DATA

MIN_GATE = 0.40
MAX_GATE = 0.80

SUMMARY_NAME = "acceptance_summary.json"
MAX_CLOCK_SKEW_MS = 500
MAX_MEDIAN_LATENCY_MS = 300
DREAM_MAX_AGE = timedelta(hours=36)
LIVE_MAX_AGE = timedelta(hours=24)


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
        trades_ok = data.get("trades_ok")
        # Grace rule: if orchestrator blocks opens and no positions, treat trades as ok
        try:
            orch_path = REPORTS / "orchestrator_snapshot.json"
            if orch_path.exists():
                orch = json.loads(orch_path.read_text())
                policy = orch.get("policy", {})
                if policy.get("allow_opens") is False:
                    port_health = REPORTS / "portfolio" / "portfolio_health.json"
                    no_open = True
                    if port_health.exists():
                        health = json.loads(port_health.read_text())
                        positions = health.get("open_positions", {})
                        no_open = sum(abs(v) for v in positions.values()) == 0
                    if no_open:
                        trades_ok = True
        except Exception:
            pass
        ok = bool(data.get("pf_ok") and trades_ok and data.get("dream_ok"))
        data["trades_ok"] = trades_ok
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

    try:
        orch_path = REPORTS / "orchestrator_snapshot.json"
        if orch_path.exists():
            orch = json.loads(orch_path.read_text())
            policy = orch.get("policy", {})
            port_health = REPORTS / "portfolio" / "portfolio_health.json"
            no_open = True
            if port_health.exists():
                health = json.loads(port_health.read_text())
                positions = health.get("open_positions", {})
                no_open = sum(abs(v) for v in positions.values()) == 0
            if policy.get("allow_opens") is False and no_open:
                fresh = True
    except Exception:
        pass

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


def _section_risk() -> Dict[str, Any]:
    data = _read_json(REPORTS / "risk_adapter.json")
    if not data:
        return {"ok": False, "details": {"error": "missing"}}
    mult = data.get("mult")
    band = data.get("band")
    reason = data.get("reason")
    if reason == "no_equity_curve":
        ok = float(mult or 1.0) == 1.0
    else:
        ok = (
            isinstance(mult, (int, float))
            and 0.5 <= float(mult) <= 1.25
            and band in {"A", "B", "C"}
        )
    return {"ok": ok, "details": data}


def _section_governance() -> Dict[str, Any]:
    data = _read_json(REPORTS / "governance_vote.json")
    if not data:
        return {"ok": False, "details": {"error": "missing"}}
    sci = data.get("sci")
    rec = data.get("recommendation")
    modules = data.get("modules", {})
    ok = isinstance(sci, (int, float)) and 0.0 <= sci <= 1.0 and rec in {"GO", "REVIEW", "PAUSE"}
    for info in modules.values():
        score = info.get("score")
        if not isinstance(score, (int, float)) or not 0.0 <= score <= 1.0:
            ok = False
    return {"ok": ok, "details": data}


def _section_orchestrator() -> Dict[str, Any]:
    snapshot = _read_json(REPORTS / "orchestrator_snapshot.json")
    if not snapshot:
        return {"ok": False, "details": {"error": "missing"}}
    ts = snapshot.get("ts")
    try:
        ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
    except Exception:
        ts_dt = None
    fresh = ts_dt and (datetime.now(timezone.utc) - ts_dt).total_seconds() <= 600 # TEN_MINUTES is not defined, using 600 for now
    inputs = snapshot.get("inputs", {})
    policy = snapshot.get("policy", {})
    sci = inputs.get("sci")
    risk_mult = inputs.get("risk_mult")
    count = inputs.get("count")
    rec = inputs.get("rec")
    band = inputs.get("risk_band")
    allow_opens = policy.get("allow_opens")
    ok = bool(fresh) and isinstance(sci, (int, float)) and 0.0 <= sci <= 1.0 and isinstance(risk_mult, (int, float)) and 0.5 <= risk_mult <= 1.25 and isinstance(count, (int, float)) and count >= 0
    if rec == "PAUSE" or band == "C":
        ok = ok and (allow_opens is False)
    return {"ok": ok, "details": snapshot}


def _section_council() -> Dict[str, Any]:
    weights = _read_json(REPORTS / "council_weights.json")
    if not weights:
        return {"ok": False, "details": {"error": "weights_missing"}}
    proposed = weights.get("proposed", {})
    delta = weights.get("delta", {})
    ok = True
    details = {}
    for regime, buckets in proposed.items():
        regime_ok = True
        total = sum(buckets.values()) if isinstance(buckets, dict) else None
        if total is None or abs(total - 1.0) > 1e-6:
            regime_ok = False
        bucket_details = {}
        for bucket, value in buckets.items():
            if not isinstance(value, (int, float)) or not 0.0 <= value <= 1.0:
                regime_ok = False
            delta_val = delta.get(regime, {}).get(bucket, 0.0)
            if abs(delta_val) > 0.10:
                regime_ok = False
            bucket_details[bucket] = {"weight": value, "delta": delta_val}
        details[regime] = {"sum": total, "buckets": bucket_details, "valid": regime_ok}
        ok = ok and regime_ok
    return {"ok": ok, "details": details}


def _section_backtest() -> Dict[str, Any]:
    summary_path = REPORTS / "backtest" / "summary.json"
    if not summary_path.exists():
        return {"ok": True, "optional": True, "details": {"note": "backtest_not_run"}}
    try:
        data = json.loads(summary_path.read_text())
    except Exception as exc:
        return {"ok": False, "optional": True, "details": {"error": str(exc)}}
    pf = data.get("pf")
    pf_adj = data.get("pf_adj")
    trades = data.get("trades", 0)
    ok = (
        isinstance(pf, (int, float))
        and isinstance(pf_adj, (int, float))
        and isinstance(trades, (int, float))
        and trades >= 1
    )
    return {"ok": ok, "optional": True, "details": data}


def _section_live_feeds() -> Dict[str, Any]:
    feeds_health_path = REPORTS / "feeds_health.json"
    feeds_exists = feeds_health_path.exists()

    try:
        with (CONFIG / "backtest.yaml").open("r") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        cfg = {}
    live_cfg = cfg.get("live", {})
    symbols = live_cfg.get("symbols", ["ETHUSDT"])
    timeframe = live_cfg.get("timeframe", "1h")

    records = []
    any_fresh = False
    for symbol in symbols:
        meta_path = DATA / "ohlcv" / f"live_{symbol}_{timeframe}_meta.json"
        meta = _read_json(meta_path)
        last_ts = meta.get("last_ts")
        rows = meta.get("rows", 0)
        fresh = _within_hours(last_ts, LIVE_MAX_AGE) if last_ts else False
        any_fresh = any_fresh or (fresh and rows >= 1)
        records.append(
            {
                "symbol": symbol,
                "rows": rows,
                "fresh": fresh,
                "last_ts": last_ts,
                "host": meta.get("host"),
            }
        )

    ok = feeds_exists and any_fresh
    details = {
        "feeds_health": feeds_exists,
        "symbols": records,
    }
    if not feeds_exists:
        details["reason"] = "feeds_health_missing"
    elif not any_fresh:
        details["reason"] = "no_recent_live_rows"

    return {"ok": ok, "optional": True, "details": details}


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
        "council": _section_council(),
        "risk": _section_risk(),
        "governance": _section_governance(),
        "orchestrator": _section_orchestrator(),
        "backtest": _section_backtest(),
        "live_feeds": _section_live_feeds(),
    }
    blocking_sections = {
        name: section for name, section in sections.items() if not section.get("optional")
    }
    overall = all(section.get("ok") for section in blocking_sections.values())
    summary = {"ts": _iso_now(), "PASS": overall, "sections": sections}
    summary_path = REPORTS / SUMMARY_NAME
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
