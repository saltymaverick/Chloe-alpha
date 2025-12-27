#!/usr/bin/env python3
"""
Reflection Prep Utility - Phase 44.3
Summarizes Chloe's recent trading behavior, council activity, and loop health
into a single JSON blob for GPT reflection or human analysis.
This is a read-only utility; it does NOT modify any trading logic or state.
"""

from __future__ import annotations

import json
import math
import os
from collections import deque
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import mean
from typing import Dict, Any, List, Optional, Tuple

from engine_alpha.core.paths import REPORTS

TRADES_PATH = REPORTS / "trades.jsonl"
COUNCIL_LOG_PATH = REPORTS / "council_perf.jsonl"
PF_LOCAL_PATH = REPORTS / "pf_local.json"
LOOP_HEALTH_PATH = REPORTS / "loop_health.json"
LIVE_LOOP_STATE_PATH = REPORTS / "live_loop_state.json"


def _tail_jsonl(path: Path, max_lines: int = 100) -> List[Dict[str, Any]]:
    """
    Return up to max_lines JSON-decoded records from the end of a JSONL file.
    If the file does not exist, return [].
    """
    if not path.exists():
        return []
    
    records = []
    try:
        with path.open("r") as f:
            lines = f.readlines()
        # Take the last max_lines
        for line in lines[-max_lines:]:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                records.append(record)
            except json.JSONDecodeError:
                continue
    except Exception:
        return []
    
    return records


def summarize_recent_trades(max_trades: int = 50) -> Dict[str, Any]:
    """
    Read the last max_trades entries from trades.jsonl and summarize:
    - number of closes,
    - PF (sum of positive pct / sum of abs(negative pct)),
    - average win,
    - average loss,
    - counts of winning and losing trades.
    If there are no closes, return zeros/None appropriately.
    """
    records = _tail_jsonl(TRADES_PATH, max_trades)
    
    # Filter for closes
    closes = []
    for record in records:
        event_type = str(record.get("type") or record.get("event") or "").lower()
        if event_type == "close":
            closes.append(record)
    
    if not closes:
        return {
            "count": 0,
            "pf": 0.0,
            "avg_win": None,
            "avg_loss": None,
            "wins": 0,
            "losses": 0,
        }
    
    # Extract pct values
    win_pcts = []
    loss_pcts = []
    for close_record in closes:
        pct = close_record.get("pct")
        try:
            pct_float = float(pct)
            if pct_float > 0:
                win_pcts.append(pct_float)
            elif pct_float < 0:
                loss_pcts.append(pct_float)
        except (TypeError, ValueError):
            continue
    
    # Compute PF
    pos_sum = sum(win_pcts) if win_pcts else 0.0
    neg_sum = abs(sum(loss_pcts)) if loss_pcts else 0.0
    if neg_sum > 0:
        pf = pos_sum / neg_sum
    elif pos_sum > 0:
        pf = float("inf")
    else:
        pf = 0.0
    
    # Compute averages
    avg_win = mean(win_pcts) if win_pcts else None
    avg_loss = mean(loss_pcts) if loss_pcts else None
    
    return {
        "count": len(closes),
        "pf": pf if pf != float("inf") else "inf",
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "wins": len(win_pcts),
        "losses": len(loss_pcts),
    }


def summarize_council_perf(max_events: int = 200) -> Dict[str, Any]:
    """
    Summarize recent council_perf events, if any.
    Reads up to max_events from council_perf.jsonl and returns:
    - total_events: number of council log rows
    - regime_counts: number of events per regime
    - bucket_counts: counts per "regime:bucket_name"
    - bucket_avg_conf: average |conf| per bucket/regime combination
    - event_type_counts: counts per event type (bar, open, close)
    If no events, return an empty summary.
    """
    events = _tail_jsonl(COUNCIL_LOG_PATH, max_events)
    
    if not events:
        return {
            "total_events": 0,
            "regime_counts": {},
            "bucket_counts": {},
            "bucket_avg_conf": {},
            "event_type_counts": {},
        }
    
    regime_counts: Dict[str, int] = {}
    bucket_counts: Dict[str, int] = {}
    bucket_conf_sums: Dict[str, float] = {}  # regime:bucket_name -> sum of |conf|
    bucket_conf_counts: Dict[str, int] = {}  # regime:bucket_name -> count of events
    event_type_counts: Dict[str, int] = {}
    
    for event in events:
        # Count event types
        event_type = event.get("event", "unknown")
        event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1
        
        regime = event.get("regime", "unknown")
        regime_counts[regime] = regime_counts.get(regime, 0) + 1
        
        buckets = event.get("buckets", [])
        for bucket in buckets:
            bucket_name = bucket.get("name", "unknown")
            bucket_conf = abs(float(bucket.get("conf", 0.0)))
            key = f"{regime}:{bucket_name}"
            bucket_counts[key] = bucket_counts.get(key, 0) + 1
            # Accumulate confidences for average calculation
            bucket_conf_sums[key] = bucket_conf_sums.get(key, 0.0) + bucket_conf
            bucket_conf_counts[key] = bucket_conf_counts.get(key, 0) + 1
    
    # Compute average confidences
    bucket_avg_conf: Dict[str, float] = {}
    for key in bucket_conf_sums:
        count = bucket_conf_counts.get(key, 1)
        if count > 0:
            bucket_avg_conf[key] = bucket_conf_sums[key] / count
    
    return {
        "total_events": len(events),
        "regime_counts": regime_counts,
        "bucket_counts": bucket_counts,
        "bucket_avg_conf": bucket_avg_conf,
        "event_type_counts": event_type_counts,
    }


def load_loop_health() -> Optional[Dict[str, Any]]:
    """
    Load loop_health.json if it exists; else return None.
    """
    if not LOOP_HEALTH_PATH.exists():
        return None
    
    try:
        with LOOP_HEALTH_PATH.open("r") as f:
            return json.load(f)
    except Exception:
        return None


def _pf_over_last_closes(max_trades: int = 50) -> tuple[Optional[float], int]:
    """
    Compute PF over last close trades from reports/trades.jsonl.
    Returns (pf, count). Returns (None, 0) if no usable data.
    """
    path = REPORTS / "trades.jsonl"
    if not path.exists():
        return (None, 0)
    try:
        lines = path.read_text().splitlines()
    except Exception:
        return (None, 0)

    closes = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("type") != "close":
            continue
        closes.append(rec)
        if len(closes) >= max_trades:
            break

    if not closes:
        return (None, 0)

    win_sum = 0.0
    loss_sum = 0.0
    for c in closes:
        pct = c.get("pct")
        if pct is None:
            continue
        try:
            pct = float(pct)
        except Exception:
            continue
        if pct > 0:
            win_sum += pct
        elif pct < 0:
            loss_sum += abs(pct)

    if loss_sum > 0:
        pf = win_sum / loss_sum
    elif win_sum > 0:
        pf = float("inf")
    else:
        pf = None
    return (pf, len(closes))


def _get_last_trade_ts() -> Optional[str]:
    """
    Return ISO timestamp string of the last trade (close or open) from reports/trades.jsonl,
    or None if no trades exist.
    """
    if not TRADES_PATH.exists():
        return None
    try:
        lines = TRADES_PATH.read_text().splitlines()
    except Exception:
        return None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        ts = rec.get("ts")
        if ts:
            return ts
    return None


def _compute_hours_since(ts_str: Optional[str]) -> Optional[float]:
    """
    Compute hours since timestamp string.
    Returns float hours or None if ts_str is None or invalid.
    """
    if not ts_str:
        return None
    try:
        # Normalize: support "Z" suffix
        ts_clean = ts_str.replace("Z", "+00:00")
        last_dt = datetime.fromisoformat(ts_clean)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - last_dt
        return delta.total_seconds() / 3600.0
    except Exception:
        return None


def _load_ops_health() -> Dict[str, Any]:
    """
    Load ops health info if available.
    Expected structure:
    {
      "pf_ok": bool,
      "trades_ok": bool,
      "dream_ok": bool,
      "notes": "..."
    }
    """
    # Try reading from ops_health.json first
    path = REPORTS / "ops_health.json"
    if path.exists():
        try:
            content = path.read_text().strip()
            if not content:
                return {}
            return json.loads(content)
        except Exception:
            pass
    
    # Fallback: try calling tools.ops_health.evaluate() if available
    try:
        from tools.ops_health import evaluate
        status = evaluate()
        return {
            "pf_ok": status.get("pf_ok", False),
            "trades_ok": status.get("trades_ok", False),
            "dream_ok": status.get("dream_ok", False),
            "notes": status.get("notes", ""),
        }
    except Exception:
        return {}


def _probe_live_signal() -> Dict[str, Any]:
    """
    Try to get a snapshot of the current live signal:
    - final_dir, final_conf
    - regime
    - opens_allowed
    - risk_band, risk_mult

    Uses run_step_live with the most recent bar if possible.
    This MUST be defensive and never raise.
    """
    try:
        from engine_alpha.data.live_prices import get_live_ohlcv
        from engine_alpha.loop.autonomous_trader import run_step_live
    except Exception:
        return {}

    try:
        symbol = os.getenv("REFLECT_SYMBOL", "ETHUSDT")
        timeframe = os.getenv("REFLECT_TIMEFRAME", "1h")
        rows = get_live_ohlcv(symbol, timeframe, limit=200, no_cache=True)
        if not rows:
            return {}

        last = rows[-1]
        bar_ts = last.get("ts")
        if not isinstance(bar_ts, str):
            return {}

        result = run_step_live(symbol=symbol, timeframe=timeframe, limit=200, bar_ts=bar_ts)
    except Exception:
        return {}

    snap = {}

    try:
        final = result.get("final") or {}
        snap["final_live_dir"] = int(final.get("dir")) if final.get("dir") is not None else None
        snap["final_live_conf"] = float(final.get("conf")) if final.get("conf") is not None else None
    except Exception:
        snap["final_live_dir"] = None
        snap["final_live_conf"] = None

    try:
        snap["regime"] = result.get("regime")
    except Exception:
        snap["regime"] = None

    try:
        policy = result.get("policy") or {}
        snap["opens_allowed"] = bool(policy.get("allow_opens", True))
    except Exception:
        snap["opens_allowed"] = None

    try:
        ra = result.get("risk_adapter") or {}
        snap["risk_band"] = ra.get("band")
        snap["risk_mult"] = float(ra.get("mult")) if ra.get("mult") is not None else None
    except Exception:
        snap["risk_band"] = None
        snap["risk_mult"] = None

    return snap


def _iter_trades(path: Optional[Path] = None, limit: Optional[int] = None):
    """
    Yield parsed trade events (dicts) from a JSONL trades file.
    
    If limit is provided, only the last `limit` lines are read.
    If path is None, uses TRADES_PATH.
    """
    if path is None:
        path = TRADES_PATH
    
    if not path.exists():
        return
    
    # If limit is None, just stream
    if limit is None:
        try:
            with path.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except Exception:
                        continue
        except Exception:
            return
    else:
        # Read only last `limit` lines
        dq = deque(maxlen=limit)
        try:
            with path.open() as f:
                for line in f:
                    dq.append(line)
            for line in dq:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except Exception:
                    continue
        except Exception:
            return


def summarize_exit_quality(max_trades: int = 200) -> Dict[str, Any]:
    """
    Summarize exit behavior from close trades:
    - counts per exit_reason
    - average exit_conf
    """
    reasons = {}
    confs = []
    
    for rec in _iter_trades(limit=max_trades):
        if rec.get("type") != "close":
            continue
        
        reason = rec.get("exit_reason") or "unknown"
        reasons[reason] = reasons.get(reason, 0) + 1
        
        if rec.get("exit_conf") is not None:
            try:
                confs.append(float(rec["exit_conf"]))
            except Exception:
                pass
    
    avg_conf = sum(confs) / len(confs) if confs else None
    
    return {
        "exit_reason_counts": reasons,
        "avg_exit_conf": avg_conf,
    }


def summarize_confidence(max_trades: int = 200) -> Dict[str, Any]:
    """
    Summarize confidence distribution and rough calibration:
    - simple buckets of exit_conf
    - correlation hints between conf and pct
    """
    buckets = {
        "conf_leq_0.3": 0,
        "conf_0.3_0.6": 0,
        "conf_geq_0.6": 0,
    }
    conf_pf = {
        "conf_leq_0.3": {"pos": 0.0, "neg": 0.0},
        "conf_0.3_0.6": {"pos": 0.0, "neg": 0.0},
        "conf_geq_0.6": {"pos": 0.0, "neg": 0.0},
    }
    
    for rec in _iter_trades(limit=max_trades):
        if rec.get("type") != "close":
            continue
        
        pct = rec.get("pct")
        conf = rec.get("exit_conf")
        if pct is None or conf is None:
            continue
        
        try:
            pct = float(pct)
            conf = float(conf)
        except Exception:
            continue
        
        if conf <= 0.3:
            bucket = "conf_leq_0.3"
        elif conf >= 0.6:
            bucket = "conf_geq_0.6"
        else:
            bucket = "conf_0.3_0.6"
        
        buckets[bucket] += 1
        if pct > 0:
            conf_pf[bucket]["pos"] += pct
        elif pct < 0:
            conf_pf[bucket]["neg"] += abs(pct)
    
    def pf_from(p):
        if p["neg"] > 0:
            return p["pos"] / p["neg"]
        elif p["pos"] > 0:
            return float("inf")
        else:
            return None
    
    pf_buckets = {k: pf_from(v) for k, v in conf_pf.items()}
    
    return {
        "conf_buckets": buckets,
        "conf_pf_estimate": pf_buckets,
    }


def summarize_risk_behavior(max_trades: int = 200) -> Dict[str, Any]:
    """
    Summarize behavior by risk band.
    - counts per risk_band on closes
    """
    bands = {}
    
    for rec in _iter_trades(limit=max_trades):
        if rec.get("type") != "close":
            continue
        
        band = rec.get("risk_band") or "unknown"
        bands[band] = bands.get(band, 0) + 1
    
    return {"risk_band_counts": bands}


def summarize_filtered_pf(
    trades_path: Path,
    threshold: float = 0.0005,
    exit_reasons: Tuple[str, ...] = ("tp", "sl"),
    max_trades: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Compute filtered PF over meaningful trades only:
    
    - Only closes with abs(pct) >= threshold
    - Only closes with exit_reason in exit_reasons
    - Grouped overall and by regime
    """
    overall = {
        "count": 0,
        "wins": 0,
        "losses": 0,
        "pos_sum": 0.0,
        "neg_sum": 0.0,
        "pf": None,
    }
    by_regime: Dict[str, Dict[str, Any]] = {}
    
    def _ensure_regime(reg):
        if reg not in by_regime:
            by_regime[reg] = {
                "count": 0,
                "wins": 0,
                "losses": 0,
                "pos_sum": 0.0,
                "neg_sum": 0.0,
                "pf": None,
            }
        return by_regime[reg]
    
    for ev in _iter_trades(path=trades_path, limit=max_trades):
        if ev.get("type") != "close":
            continue
        
        # Phase 1: Filter out scratch trades
        if ev.get("is_scratch", False):
            continue
        
        pct = ev.get("pct")
        if pct is None:
            continue
        try:
            p = float(pct)
        except Exception:
            continue
        if abs(p) < threshold:
            continue
        
        reason = ev.get("exit_reason", "")
        if exit_reasons and reason not in exit_reasons:
            continue
        
        regime = ev.get("regime") or "unknown"
        
        # Update overall
        overall["count"] += 1
        regime_bucket = _ensure_regime(regime)
        regime_bucket["count"] += 1
        
        if p > 0:
            overall["wins"] += 1
            overall["pos_sum"] += p
            regime_bucket["wins"] += 1
            regime_bucket["pos_sum"] += p
        else:
            overall["losses"] += 1
            overall["neg_sum"] += abs(p)
            regime_bucket["losses"] += 1
            regime_bucket["neg_sum"] += abs(p)
    
    # Compute PFs
    def _compute_pf(bucket: Dict[str, Any]) -> None:
        pos = bucket["pos_sum"]
        neg = bucket["neg_sum"]
        if bucket["losses"] == 0:
            if bucket["wins"] == 0:
                bucket["pf"] = None
            else:
                bucket["pf"] = "inf"
        else:
            if neg == 0:
                bucket["pf"] = "inf"
            else:
                bucket["pf"] = pos / neg
    
    _compute_pf(overall)
    for reg in by_regime.values():
        _compute_pf(reg)
    
    return {
        "threshold": threshold,
        "exit_reasons": list(exit_reasons),
        "overall": overall,
        "by_regime": by_regime,
    }


def build_activity_block() -> Dict[str, Any]:
    """
    Build an 'activity' block describing recent activity and current live state.
    
    Includes:
    - last_trade_ts: ISO timestamp of last trade (close or open)
    - hours_since_last_trade: hours since last trade
    - trades_ok: ops health status for trades
    - opens_allowed: current policy allow_opens flag
    - final_live_dir: current live signal direction (-1, 0, +1)
    - final_live_conf: current live signal confidence [0.0, 1.0]
    - risk_band: current risk band (A/B/C)
    - risk_mult: current risk multiplier
    - regime: current market regime (trend/chop/high_vol)
    - pf_last_50: PF over last 50 closes
    - pf_last_20: PF over last 20 closes
    - trades_last_50: count of closes in last 50
    - trades_last_20: count of closes in last 20
    - inactivity_flag: heuristic flag for potential inactivity concern
    - notes: ops health notes/status messages
    """
    last_trade_ts = _get_last_trade_ts()
    hours_since = _compute_hours_since(last_trade_ts)
    ops = _load_ops_health()
    snap = _probe_live_signal()

    trades_ok = ops.get("trades_ok")
    notes = ops.get("notes") or ""

    pf_last_50, count_50 = _pf_over_last_closes(50)
    pf_last_20, count_20 = _pf_over_last_closes(20)

    # Heuristic for inactivity concerns
    inactivity_flag = False
    if hours_since is not None and hours_since > 24 and snap.get("opens_allowed") and (snap.get("final_live_conf") or 0) >= 0.5:
        inactivity_flag = True

    return {
        "last_trade_ts": last_trade_ts,
        "hours_since_last_trade": hours_since,
        "trades_ok": trades_ok,
        "opens_allowed": snap.get("opens_allowed"),
        "final_live_dir": snap.get("final_live_dir"),
        "final_live_conf": snap.get("final_live_conf"),
        "risk_band": snap.get("risk_band"),
        "risk_mult": snap.get("risk_mult"),
        "regime": snap.get("regime"),
        "pf_last_50": pf_last_50 if pf_last_50 != float("inf") else "inf",
        "pf_last_20": pf_last_20 if pf_last_20 != float("inf") else "inf",
        "trades_last_50": count_50,
        "trades_last_20": count_20,
        "inactivity_flag": inactivity_flag,
        "notes": notes,
    }


def main() -> None:
    """Assemble reflection input blob from recent trading data."""
    now = datetime.now(timezone.utc).isoformat()
    
    trades_summary = summarize_recent_trades(max_trades=50)
    council_summary = summarize_council_perf(max_events=200)
    exit_quality = summarize_exit_quality(max_trades=200)
    confidence_summary = summarize_confidence(max_trades=200)
    risk_behavior = summarize_risk_behavior(max_trades=200)
    loop_health = load_loop_health()
    activity_block = build_activity_block()
    
    # Compute filtered PF (meaningful trades only)
    # Use more generous threshold (0.0002) and read all trades to capture meaningful signals
    # Note: We read all trades (limit=None) to ensure we don't miss older meaningful closes
    filtered_pf = summarize_filtered_pf(
        trades_path=TRADES_PATH,
        threshold=0.0002,  # 0.02% cutoff, more generous than pf_doctor_filtered default
        exit_reasons=("tp", "sl"),  # only meaningful exits
        max_trades=None,  # read all trades to ensure we capture all meaningful closes
    )
    
    reflection_input = {
        "timestamp": now,
        "recent_trades": trades_summary,
        "council_summary": council_summary,
        "exit_quality": exit_quality,
        "confidence_summary": confidence_summary,
        "risk_behavior": risk_behavior,
        "loop_health": loop_health,
        "activity": activity_block,
        "filtered_pf": filtered_pf,
    }
    
    print(json.dumps(reflection_input, indent=2))


if __name__ == "__main__":
    main()


