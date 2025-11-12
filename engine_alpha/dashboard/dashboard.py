"""
Alpha Chloe dashboard - hardened for canonical paths and safe refresh.
"""

from __future__ import annotations

import json
import os
import time
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import altair as alt
import pandas as pd
import streamlit as st
# @cursor-guard:pf-tile:v1
# region pf-tile
import os

try:
    import streamlit as st
except Exception:
    st = None  # streamlit might not be available during headless runs

PF_LIVE = "reports/pf_local_live.json"
PF_NORM = "reports/pf_local_norm.json"


def _read_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _normalize(obj):
    if not obj:
        return None
    pf_value = obj.get("pf_value") or obj.get("pf") or obj.get("value")
    pf_window = obj.get("pf_window") or obj.get("window") or "local"
    trades = int(obj.get("trades_count") or obj.get("trades") or obj.get("count") or 0)
    updated = obj.get("updated_at") or obj.get("updated") or obj.get("timestamp")
    delta = obj.get("delta_pf")
    return {
        "pf_value": float(pf_value) if pf_value is not None else None,
        "pf_window": pf_window or "local",
        "trades_count": trades,
        "updated_at": str(updated) if updated else None,
        "delta_pf": float(delta) if isinstance(delta, (int, float)) else None,
    }


def _choose_pf():
    live = _normalize(_read_json(PF_LIVE))
    norm = _normalize(_read_json(PF_NORM))
    if live and live["trades_count"] >= 30:
        chosen = live
        source = "live"
    elif norm:
        chosen = norm
        source = "norm"
    else:
        return {
            "pf_value": None,
            "pf_window": "local",
            "trades_count": 0,
            "source": "none",
            "updated_at": None,
            "delta_pf": None,
        }
    chosen["source"] = source
    if not chosen.get("updated_at"):
        chosen["updated_at"] = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    return chosen


def _to_local_min(iso_str):
    if not iso_str:
        return "Updated —"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        local = dt.astimezone().replace(second=0, microsecond=0)
        return "Updated " + local.isoformat(timespec="minutes")
    except Exception:
        return "Updated —"


def _fmt_pf(pf):
    return f"{pf:.2f}" if isinstance(pf, (int, float)) else "—"


def _pf_band(pf):
    if not isinstance(pf, (int, float)):
        return "red", "#dc2626"
    if pf >= 1.10:
        return "green", "#16a34a"
    if pf >= 1.00:
        return "amber", "#d97706"
    return "red", "#dc2626"


def render_pf_tile():
    if st is None:
        return
    d = _choose_pf()
    pf, win, n, src, upd, dp = (
        d.get("pf_value"),
        d.get("pf_window") or "local",
        d.get("trades_count") or 0,
        d.get("source") or "none",
        d.get("updated_at"),
        d.get("delta_pf"),
    )
    _, color_hex = _pf_band(pf)
    value_markup = f"<span style='color:{color_hex}; font-size:1.4rem; font-weight:600;'>{_fmt_pf(pf)}</span>"
    st.markdown('<div id="pf-tile-main"></div>', unsafe_allow_html=True)
    st.subheader("Profit Factor")
    st.markdown(value_markup, unsafe_allow_html=True)
    st.caption(f"{src.upper()} • {win} • {n} trades")
    st.caption(_to_local_min(upd))
    if isinstance(dp, (int, float)):
        arrow = "▲" if dp >= 0 else "▼"
        st.caption(f"{arrow} {abs(dp):.2f}")
# endregion pf-tile
# @cursor-guard:dashboard-safe:v1
# region dashboard-style
try:
    import streamlit as st
    st.markdown(
        """
        <style>
          /* tighter heading & caption rhythm inside tiles */
          .block-container h2, .block-container h3 { margin: 0.15rem 0 0.25rem 0; }
          .block-container .stMarkdown p { margin: 0.15rem 0; }
          .block-container .stCaption { margin: 0.10rem 0 !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )
except Exception:
    pass
# endregion dashboard-style
# @cursor-guard:dashboard-safe:v1
# region dashboard-polish
try:
    import streamlit as st
    st.markdown(
        """
        <style>
        /* ----- Global Dashboard Polish (Phase 40) ----- */
        .block-container { padding-top: 1rem; }
        h2, h3 { margin-bottom: 0.25rem; }
        .stMarkdown p { margin: 0.1rem 0; }

        /* PF, Bias, Confidence numeric colors */
        .pf-tile .green, .bias-green, .conf-green { color: #10B981; font-weight: 600; }
        .pf-tile .amber, .bias-amber, .conf-amber { color: #F59E0B; font-weight: 600; }
        .pf-tile .red,   .bias-red,   .conf-red   { color: #EF4444; font-weight: 600; }

        /* Status highlighting */
        .status-green { color: #10B981; }
        .status-amber { color: #F59E0B; }
        .status-red   { color: #EF4444; }

        /* Optional glow for active/green */
        .glow-green { text-shadow: 0 0 6px rgba(16,185,129,0.7); }

        /* tile captions */
        .stCaption, .st-emotion-cache-q8sbsg { font-size: 0.82rem !important; opacity: 0.9; }

        /* Align expander content spacing */
        div[data-testid="stExpander"] { margin-top: 0.5rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )
except Exception:
    pass
# endregion dashboard-polish
# @cursor-guard:dashboard-safe:v1
# region dashboard-pulse
import os, json, time

try:
    import streamlit as st
except Exception:
    st = None

_PULSE_PATHS = [
    "reports/trades.jsonl",
    "reports/gpt_reflection.jsonl",
    "reports/equity_norm.json",
    "reports/equity_live.json",
]


def _get_latest_mtime(paths):
    mtimes = []
    for p in paths:
        if os.path.exists(p):
            try:
                mtimes.append(os.path.getmtime(p))
            except Exception:
                pass
    return max(mtimes) if mtimes else None


def render_pulse_indicator():
    if st is None:
        return
    mtime = _get_latest_mtime(_PULSE_PATHS)
    if not mtime:
        st.caption("🩶 Pulse: Idle")
        return
    age = time.time() - mtime
    color = "🟢" if age < 15 else "🟡" if age < 60 else "🔴"
    st.caption(f"{color} Pulse – updated {int(age)} s ago")
# endregion dashboard-pulse
# @cursor-guard:dashboard-safe:v1
# region council-details
import os, json
from datetime import datetime

try:
    import streamlit as st
except Exception:
    st = None

_CN_PATH = "reports/council_snapshot.json"


def _read_json_cn(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _fmt_ts_local(iso):
    if not iso:
        return "Updated —"
    try:
        dt = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone()
        return "Updated " + dt.replace(second=0, microsecond=0).isoformat(timespec="minutes")
    except Exception:
        return "Updated —"


def _normalize_cn(obj):
    if not isinstance(obj, dict):
        return None

    def get(d, *ks):
        if not isinstance(d, dict):
            return None
        for k in ks:
            if isinstance(k, str) and k in d:
                return d[k]
        return None

    rec = get(obj, "rec", "recommendation", "decision") or "UNKNOWN"
    sci = get(obj, "sci", "system_confidence", "confidence")
    pa = get(obj, "pa", "profit_amplifier", "pa_status")

    if isinstance(pa, dict):
        pa_on = bool(get(pa, "active", "on"))
    elif isinstance(pa, str):
        pa_on = pa.strip().upper() in {"ON", "TRUE", "ACTIVE", "1"}
    elif isinstance(pa, (int, float)):
        pa_on = bool(pa)
    else:
        pa_on = False

    votes = get(obj, "votes", "council_votes", "weighting", "weights") or {}
    strategies = get(obj, "active_strategies", "strategies", "running") or []
    errors = get(obj, "errors", "incidents", "error_count", "incident_count")
    ts = get(obj, "updated_at", "timestamp", "time")

    try:
        sci = float(sci) if sci is not None else None
    except Exception:
        sci = None

    try:
        if isinstance(errors, list):
            err_count = len(errors)
        elif errors is None:
            err_count = None
        else:
            err_count = int(errors)
    except Exception:
        err_count = None

    if isinstance(votes, dict):
        def w(val):
            try:
                return float(val)
            except Exception:
                return -1.0

        votes = dict(sorted(votes.items(), key=lambda kv: w(kv[1]), reverse=True))

    return {
        "rec": str(rec).upper(),
        "sci": sci,
        "pa_on": pa_on,
        "votes": votes,
        "strategies": strategies,
        "errors": errors if isinstance(errors, list) else None,
        "error_count": err_count,
        "updated_at": ts,
    }


def render_council_details():
    if st is None:
        return
    obj = _read_json_cn(_CN_PATH)
    data = _normalize_cn(obj) or {
        "rec": "UNKNOWN",
        "sci": None,
        "pa_on": False,
        "votes": {},
        "strategies": [],
        "errors": None,
        "error_count": None,
        "updated_at": None,
    }

    with st.expander("Council Snapshot", expanded=False):
        st.caption(_fmt_ts_local(data.get("updated_at")))
        col1, col2 = st.columns([1, 1], gap="small")
        with col1:
            st.markdown(f"**REC:** {data['rec']}")
            st.markdown(f"**SCI:** {data['sci']:.2f}" if isinstance(data["sci"], (int, float)) else "**SCI:** —")
            st.markdown(f"**PA:** {'ON' if data['pa_on'] else 'OFF'}")
            if data.get("error_count") is not None:
                st.markdown(f"**Errors:** {data['error_count']}")
        with col2:
            if isinstance(data.get("strategies"), list) and data["strategies"]:
                st.markdown("**Active Strategies**")
                st.markdown(", ".join(map(str, data["strategies"])))
            if isinstance(data.get("votes"), dict) and data["votes"]:
                st.markdown("**Votes (top)**")
                items = list(data["votes"].items())[:5]
                lines = [f"- **{k}**: {v}" for k, v in items]
                st.markdown("\n".join(lines))
        if isinstance(data.get("errors"), list) and data["errors"]:
            st.markdown("**Recent Errors**")
            for e in data["errors"][:5]:
                st.caption(f"- {e}")
# endregion council-details
# @cursor-guard:dashboard-safe:v1
# region last-signal
import os, json
from datetime import datetime

try:
    import streamlit as st
except Exception:
    st = None

_TRADES_PATH = "reports/trades.jsonl"
_REFLECT_PATHS = [
    "reports/gpt_reflection.jsonl",
    "engine_alpha/reflect/gpt_reflection.jsonl",
]


def _read_last_jsonl(path, max_scan: int = 2000):
    if not os.path.exists(path):
        return None
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            start = max(0, size - max_scan)
            if start:
                f.seek(start)
            tail = f.read().splitlines()
        for line in reversed(tail):
            if not line.strip():
                continue
            try:
                return json.loads(line.decode("utf-8") if isinstance(line, (bytes, bytearray)) else line)
            except Exception:
                continue
    except Exception:
        return None
    return None


def _fmt_ts_local_last(iso):
    if not iso:
        return "Updated —"
    try:
        dt = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone()
        return "Updated " + dt.replace(second=0, microsecond=0).isoformat(timespec="minutes")
    except Exception:
        return "Updated —"


def _normalize_trade(obj):
    if not isinstance(obj, dict):
        return None
    side = obj.get("side") or obj.get("direction") or obj.get("type")
    sym = obj.get("symbol") or obj.get("pair") or obj.get("market") or "—"
    conf = obj.get("confidence") or obj.get("conf") or obj.get("score")
    pnl = obj.get("pnl") or obj.get("pct_pnl") or obj.get("profit_pct") or obj.get("profit")
    ts = obj.get("timestamp") or obj.get("time") or obj.get("updated_at")
    pf_win = obj.get("pf_window") or obj.get("window") or "local"
    reason = obj.get("reason") or obj.get("rationale") or None
    side = str(side).upper() if side else "—"
    try:
        conf = float(conf)
    except Exception:
        conf = None
    try:
        pnl = float(pnl)
    except Exception:
        pnl = None
    return {
        "side": side,
        "symbol": sym,
        "confidence": conf,
        "pnl": pnl,
        "pf_window": pf_win,
        "timestamp": ts,
        "reason": reason,
    }


def _normalize_reflection(obj):
    if not isinstance(obj, dict):
        return None
    txt = obj.get("reflection") or obj.get("note") or obj.get("message") or obj.get("text")
    ts = obj.get("timestamp") or obj.get("time") or obj.get("updated_at")
    if not isinstance(txt, str) or not txt.strip():
        return None
    return {"text": txt.strip(), "timestamp": ts}


def _choose_last_signal():
    tr = _normalize_trade(_read_last_jsonl(_TRADES_PATH))
    ref = None
    for p in _REFLECT_PATHS:
        r = _read_last_jsonl(p)
        ref = _normalize_reflection(r)
        if ref:
            break
    return tr, ref


def render_last_signal():
    if st is None:
        return
    tr, ref = _choose_last_signal()
    with st.expander("Last Signal", expanded=False):
        if not tr:
            st.caption("No recent trades found.")
            return
        conf = f"{tr['confidence']:.2f}" if isinstance(tr["confidence"], (int, float)) else "—"
        pnl = f"{tr['pnl']:.2f}%" if isinstance(tr["pnl"], (int, float)) else "—"
        st.markdown(f"**{tr['side']} • {tr['symbol']}**  |  **Conf:** {conf}  |  **PnL:** {pnl}")
        st.caption(f"{tr['pf_window']} • {_fmt_ts_local_last(tr.get('timestamp'))}")
        if tr.get("reason"):
            st.markdown(f"**Reason**: {tr['reason']}")
        if ref:
            st.markdown("**Reflection**")
            st.caption(ref["text"])
# endregion last-signal
# @cursor-guard:dashboard-safe:v1
# region equity-chart
import os, json
from datetime import datetime
from typing import List, Dict, Any

try:
    import streamlit as st
except Exception:
    st = None


def _read_json(path: str):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_jsonl(path: str, max_lines: int = 5000) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    out: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if not line.strip():
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
                if i >= max_lines:
                    break
    except Exception:
        pass
    return out


def _parse_ts(iso: str):
    try:
        return datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone()
    except Exception:
        return None


def _load_equity_series():
    series: List[tuple[datetime.datetime, float]] = []
    for p in ("reports/equity_norm.json", "reports/equity_live.json"):
        obj = _read_json(p)
        if isinstance(obj, list) and obj:
            for row in obj:
                ts = _parse_ts(row.get("timestamp") or row.get("updated_at"))
                eq = row.get("equity")
                if ts and isinstance(eq, (int, float)):
                    series.append((ts, float(eq)))
            if series:
                series.sort(key=lambda x: x[0])
                return series
        elif isinstance(obj, dict) and obj:
            ts = _parse_ts(obj.get("timestamp") or obj.get("updated_at"))
            eq = obj.get("equity")
            if ts and isinstance(eq, (int, float)):
                return [(ts, float(eq))]

    trades = _read_jsonl("reports/trades.jsonl", max_lines=20000)
    if not trades:
        return series

    tmp: List[tuple[datetime.datetime, float]] = []
    for t in trades:
        ts = _parse_ts(t.get("timestamp") or t.get("time") or t.get("updated_at"))
        eq = t.get("equity_after") or t.get("balance_after")
        if ts and isinstance(eq, (int, float)):
            tmp.append((ts, float(eq)))
    if tmp:
        tmp.sort(key=lambda x: x[0])
        return tmp

    equity = 10_000.0
    series = []
    for t in trades:
        ts = _parse_ts(t.get("timestamp") or t.get("time") or t.get("updated_at"))
        if not ts:
            continue
        if "pct_pnl" in t and isinstance(t["pct_pnl"], (int, float)):
            equity *= 1.0 + float(t["pct_pnl"]) / 100.0
        elif "pnl" in t and isinstance(t["pnl"], (int, float)):
            equity += float(t["pnl"])
        series.append((ts, float(equity)))

    series.sort(key=lambda x: x[0])
    return series


def render_equity_chart():
    if st is None:
        return
    data = _load_equity_series()
    if not data:
        st.caption("Equity chart: no data yet.")
        return

    import pandas as pd
    import altair as alt

    df = pd.DataFrame({"timestamp": [d[0] for d in data], "equity": [d[1] for d in data]})
    if len(df) > 5000:
        df = df.tail(5000)

    y_min, y_max = float(df["equity"].min()), float(df["equity"].max())
    pad = max(1.0, (y_max - y_min) * 0.05)
    y_domain = [y_min - pad, y_max + pad]

    chart = (
        alt.Chart(df)
        .mark_line()
        .encode(
            x=alt.X("timestamp:T", title="Time"),
            y=alt.Y("equity:Q", title="Equity ($)", scale=alt.Scale(domain=y_domain)),
            tooltip=[alt.Tooltip("timestamp:T"), alt.Tooltip("equity:Q", format=",.2f")],
        )
        .properties(height=240)
        .interactive(bind_y=False)
    )

    st.altair_chart(chart, use_container_width=True)
# endregion equity-chart
# @cursor-guard:dashboard-safe:v1
# region loop-health-tile

_LH_PATHS = [
    "reports/loop_health.json",
    "reports/council_snapshot.json",
]


def _read_json_lh(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _ci_get(d, *keys):
    if not isinstance(d, dict):
        return None
    lower = {(k.lower() if isinstance(k, str) else k): v for k, v in d.items()}
    for k in keys:
        if isinstance(k, str):
            if k in d:
                return d[k]
            if k.lower() in lower:
                return lower[k.lower()]
        else:
            return None
    return None


def _normalize_lh(obj):
    if not obj:
        return None
    rec = _ci_get(obj, "rec", "recommendation", "status_rec", "decision")
    sci = _ci_get(obj, "sci", "system_confidence", "confidence")
    try:
        sci = float(sci) if sci is not None else None
    except Exception:
        sci = None
    pa = _ci_get(obj, "pa", "profit_amplifier", "pa_status")
    if isinstance(pa, dict):
        pa_on = bool(_ci_get(pa, "active") or _ci_get(pa, "on"))
    else:
        pa_on = str(pa).strip().upper() in {"ON", "TRUE", "ACTIVE", "1"}
    errs = _ci_get(obj, "errors", "error_count", "incidents", "incident_count")
    try:
        errs = int(errs) if errs is not None else None
    except Exception:
        errs = None
    ts = _ci_get(obj, "updated_at", "timestamp", "time")
    return {
        "rec": str(rec).upper() if rec is not None else "UNKNOWN",
        "sci": sci,
        "pa_on": bool(pa_on),
        "errors": errs,
        "updated_at": ts,
    }


def _choose_loop_health():
    for p in _LH_PATHS:
        j = _read_json_lh(p)
        n = _normalize_lh(j)
        if n:
            if not n.get("updated_at"):
                n["updated_at"] = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
            return n
    return {"rec": "UNKNOWN", "sci": None, "pa_on": False, "errors": None, "updated_at": None}


def _fmt_sci(v):
    return f"{v:.2f}" if isinstance(v, (int, float)) else "—"


def _to_local_min_lh(iso):
    if not iso:
        return "Updated —"
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone()
        return "Updated " + dt.replace(second=0, microsecond=0).isoformat(timespec="minutes")
    except Exception:
        return "Updated —"


def render_loop_health_tile():
    if st is None:
        return
    d = _choose_loop_health()
    rec, sci, pa_on, errs, upd = d["rec"], d["sci"], d["pa_on"], d["errors"], d["updated_at"]
    st.subheader("Status")
    parts = [f"REC: {rec}", f"SCI: {_fmt_sci(sci)}", f"PA: {'ON' if pa_on else 'OFF'}"]
    if errs is not None:
        parts.append(f"ERR: {errs}")
    st.markdown(" | ".join(parts))
    st.caption(_to_local_min_lh(upd))
# endregion loop-health-tile
# @cursor-guard:dashboard-safe:v1
# region bias-tile

_BIAS_PATHS = [
    "reports/bias.json",
    "reports/council_snapshot.json",
]


def _read_json_bias(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _normalize_bias(obj):
    if not obj:
        return None
    raw = (
        obj.get("bias")
        or obj.get("avg_bias")
        or obj.get("value")
        or (obj.get("metrics", {}) if isinstance(obj.get("metrics"), dict) else {}).get("bias")
    )
    if isinstance(raw, str):
        raw_str = raw.strip()
        raw = float(raw_str) if raw_str.replace(".", "", 1).isdigit() else raw
    b = float(raw) if isinstance(raw, (int, float)) else None
    if b is not None:
        b = max(0.0, min(1.0, b))
    ts = obj.get("updated_at") or obj.get("timestamp") or obj.get("time")
    return {"bias": b, "updated_at": ts}


def _choose_bias():
    for p in _BIAS_PATHS:
        j = _read_json_bias(p)
        n = _normalize_bias(j)
        if n:
            if not n.get("updated_at"):
                n["updated_at"] = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
            return n
    return {"bias": None, "updated_at": None}


def _bias_band(v):
    if v is None:
        return "neutral"
    if v >= 0.60:
        return "green"
    if v >= 0.45:
        return "amber"
    return "red"


def _fmt01(v):
    return f"{v:.2f}" if isinstance(v, (int, float)) else "—"


def _to_local_min_bias(iso):
    if not iso:
        return "Updated —"
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone()
        return "Updated " + dt.replace(second=0, microsecond=0).isoformat(timespec="minutes")
    except Exception:
        return "Updated —"


def render_bias_tile():
    if st is None:
        return
    d = _choose_bias()
    v, upd = d.get("bias"), d.get("updated_at")
    st.subheader("Bias")
    st.markdown(f"**{_fmt01(v)}**")
    st.caption(_to_local_min_bias(upd))
# endregion bias-tile
# @cursor-guard:dashboard-safe:v1
# region confidence-tile

_CONF_PATHS = [
    "reports/confidence.json",
    "reports/council_snapshot.json",
    "reports/loop_health.json",
]


def _read_json_conf(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _normalize_conf(obj):
    if not obj:
        return None
    raw = (
        obj.get("confidence")
        or obj.get("sci")
        or obj.get("system_confidence")
        or obj.get("value")
        or (obj.get("metrics", {}) if isinstance(obj.get("metrics"), dict) else {}).get("confidence")
    )
    if isinstance(raw, str):
        raw_str = raw.strip()
        raw = float(raw_str) if raw_str.replace(".", "", 1).isdigit() else raw
    c = float(raw) if isinstance(raw, (int, float)) else None
    if c is not None:
        c = max(0.0, min(1.0, c))
    ts = obj.get("updated_at") or obj.get("timestamp") or obj.get("time")
    return {"confidence": c, "updated_at": ts}


def _choose_confidence():
    for p in _CONF_PATHS:
        j = _read_json_conf(p)
        n = _normalize_conf(j)
        if n:
            if not n.get("updated_at"):
                n["updated_at"] = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
            return n
    return {"confidence": None, "updated_at": None}


def _conf_band(v):
    if v is None:
        return "neutral"
    if v >= 0.65:
        return "green"
    if v >= 0.50:
        return "amber"
    return "red"


def _fmt01c(v):
    return f"{v:.2f}" if isinstance(v, (int, float)) else "—"


def _to_local_min_conf(iso):
    if not iso:
        return "Updated —"
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone()
        return "Updated " + dt.replace(second=0, microsecond=0).isoformat(timespec="minutes")
    except Exception:
        return "Updated —"


def render_confidence_tile():
    if st is None:
        return
    d = _choose_confidence()
    v, upd = d.get("confidence"), d.get("updated_at")
    st.subheader("Confidence")
    st.markdown(f"**{_fmt01c(v)}**")
    st.caption(_to_local_min_conf(upd))
# endregion confidence-tile
def _has_weighted_pf():
    from engine_alpha.core.paths import REPORTS
    import json
    for name in ('pf_local_live.json','pf_local_norm.json'):
        f = REPORTS / name
        if f.exists():
            try:
                d = json.loads(f.read_text() or '{}')
                if 'pf' in d:
                    return True
            except Exception:
                pass
    return False



def _y_zoom(points, pad=5.0):
    try:
        vals = [float(x.get('equity', 0)) for x in points[-100:]]
        if not vals:
            return None
        lo, hi = min(vals), max(vals)
        if hi - lo < pad:
            mid = (hi + lo) / 2.0
            return (mid - pad, mid + pad)
        return (lo - pad, hi + pad)
    except Exception:
        return None

try:
    from streamlit_autorefresh import st_autorefresh
except ModuleNotFoundError:  # pragma: no cover - defensive fallback
    def st_autorefresh(interval: int = 0, key: str | None = None) -> None:
        if interval and interval > 0:
            st.markdown(
                f"<script>setTimeout(function(){{window.location.reload();}}, {int(interval)});</script>",
                unsafe_allow_html=True,
            )
        return None

from engine_alpha.core.paths import REPORTS, LOGS, DATA


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _choose_weighted_pf():
    try:
        from engine_alpha.core.paths import REPORTS
        import json

        live_path = REPORTS / "pf_local_live.json"
        norm_path = REPORTS / "pf_local_norm.json"
        live = json.loads(live_path.read_text()) if live_path.exists() else None
        norm = json.loads(norm_path.read_text()) if norm_path.exists() else None
        if live and int(live.get("count", 0)) >= 30:
            return live
        return norm or live
    except Exception:
        return None


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    """Return JSON object or None if unreadable."""
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def jsonl_tail(path: Path, n: int = 1) -> List[Dict[str, Any]]:
    """Return last n JSONL rows (dicts)."""
    if not path.exists():
        return []
    try:
        lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for line in lines[-n:]:
        try:
            record = json.loads(line)
            if isinstance(record, dict):
                out.append(record)
        except Exception:
            continue
    return out


def load_equity_df(path: Optional[Path] = None, max_points: int = 300) -> Optional[pd.DataFrame]:
    """Load equity curve from reports, returning cleaned DataFrame."""
    target_path = path or (REPORTS / "equity_curve.jsonl")
    if not target_path.exists():
        return None
    try:
        rows: List[Dict[str, Any]] = []
        for raw in target_path.read_text().splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            if "ts" in obj and "equity" in obj:
                rows.append(
                    {
                        "ts": obj["ts"],
                        "equity": obj["equity"],
                        "adj_pct": obj.get("adj_pct"),
                    }
                )
    except Exception:
        return None
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    df["equity"] = pd.to_numeric(df["equity"], errors="coerce")
    if "adj_pct" in df.columns:
        df["adj_pct"] = pd.to_numeric(df["adj_pct"], errors="coerce")
    df = df.dropna(subset=["ts", "equity"])\
        .sort_values("ts")
    if df.empty:
        return None
    return df.tail(max_points)


def load_equity_df_from(path: Path, max_points: int = 300) -> Optional[pd.DataFrame]:
    """Variant for specific JSONL path (e.g., backtests)."""
    if not path.exists():
        return None
    try:
        rows: List[Dict[str, Any]] = []
        for raw in path.read_text().splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            if "ts" in obj and "equity" in obj:
                rows.append(
                    {
                        "ts": obj["ts"],
                        "equity": obj["equity"],
                        "adj_pct": obj.get("adj_pct"),
                    }
                )
    except Exception:
        return None
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    df["equity"] = pd.to_numeric(df["equity"], errors="coerce")
    if "adj_pct" in df.columns:
        df["adj_pct"] = pd.to_numeric(df["adj_pct"], errors="coerce")
    df = df.dropna(subset=["ts", "equity"]).sort_values("ts")
    return df.tail(max_points) if not df.empty else None


def read_text_tail(path: Path, lines: int = 3) -> List[str]:
    """Return tail of plain-text file."""
    if not path.exists():
        return []
    try:
        content = [ln for ln in path.read_text().splitlines() if ln.strip()]
    except Exception:
        return []
    return content[-lines:]


def age_color(ts_val: Optional[str]) -> Tuple[str, str]:
    """Return (color, formatted timestamp) for heartbeat chips."""
    if not ts_val:
        return "gray", "N/A"
    try:
        candidate = ts_val[:-1] + "+00:00" if ts_val.endswith("Z") else ts_val
        dt = datetime.fromisoformat(candidate)
        delta = datetime.now(timezone.utc) - dt
        seconds = delta.total_seconds()
    except Exception:
        return "gray", "N/A"
    color = "green" if seconds < 3600 else "orange" if seconds <= 7200 else "red"
    return color, dt.strftime("%Y-%m-%d %H:%M:%SZ")


def truncate_text(text: str, limit: int = 600) -> Tuple[str, bool]:
    """Truncate text with ellipsis."""
    text = text or ""
    if len(text) <= limit:
        return text, False
    return text[:limit].rstrip() + "…", True


# ---------------------------------------------------------------------------
# Global UI fragments
# ---------------------------------------------------------------------------

def render_heartbeat_and_activity() -> None:
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    policy_ts = (load_json(REPORTS / "orchestrator_snapshot.json") or {}).get("ts")
    live_ts = (load_json(REPORTS / "live_loop_state.json") or {}).get("ts")
    trade_tail = jsonl_tail(REPORTS / "trades.jsonl", n=1)
    dream_tail = jsonl_tail(REPORTS / "dream_log.jsonl", n=1)

    trade_ts = trade_tail[0].get("ts") if trade_tail else None
    dream_ts = dream_tail[0].get("ts") if dream_tail else None

    st.markdown(f"**Last updated:** {now_str}")
    hb_cols = st.columns(4)
    for col, (label, ts_val) in zip(
        hb_cols,
        [("Policy", policy_ts), ("Live", live_ts), ("Trade", trade_ts), ("Dream", dream_ts)],
    ):
        color, text = age_color(ts_val)
        col.markdown(f"**{label}:** :{color}[{text}]")

    st.markdown("### Activity Feed")
    sources = [
        ("Orchestrator", REPORTS / "orchestrator_log.jsonl"),
        ("Sandbox", REPORTS / "sandbox" / "sandbox_runs.jsonl"),
        ("Alerts", REPORTS / "alerts.jsonl"),
    ]
    for label, path in sources:
        entry = jsonl_tail(path, n=1)
        if entry:
            st.markdown(f"**{label}:**")
            st.code(json.dumps(entry[0], indent=2))
    ops_tail = read_text_tail(LOGS / "ops.log", lines=1)
    if ops_tail:
        st.markdown("**Ops:**")
        st.code("\n".join(ops_tail))


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

def overview_tab() -> None:
    st.header("Overview")

    # @cursor-guard:dashboard-safe:v1
    # region dashboard-pulse
    render_pulse_indicator()
    # endregion dashboard-pulse

    # @cursor-guard:dashboard-safe:v1
    # region dashboard-row-tiles
    try:
        import streamlit as _st  # no-op if already imported
    except Exception:
        _st = None
    if _st is None:
        return
    # single, aligned row for PF • Bias • Confidence
    c1, c2, c3 = _st.columns([1, 1, 1], gap="small")
    with c1:
        render_pf_tile()
    with c2:
        render_bias_tile()
    with c3:
        render_confidence_tile()
    # endregion dashboard-row-tiles

    # @cursor-guard:dashboard-safe:v1
    # region loop-health-tile
    render_loop_health_tile()
    # endregion loop-health-tile
    # @cursor-guard:dashboard-safe:v1
    # region council-details
    render_council_details()
    # endregion council-details
    # @cursor-guard:dashboard-safe:v1
    # region last-signal
    render_last_signal()
    # endregion last-signal

    col_pa, col_equity = st.columns(2)

    pa_status = load_json(REPORTS / "pa_status.json")
    governance_snapshot = load_json(REPORTS / "governance_snapshot.json") or {}
    orchestrator_snapshot = load_json(REPORTS / "orchestrator_snapshot.json") or {}

    modes = ["Risk-weighted", "Risk-normalized", "Full"]
    live_curve_path = REPORTS / "equity_curve_live.jsonl"
    live_exists = live_curve_path.exists()
    norm_exists = (REPORTS / "equity_curve_norm.jsonl").exists()
    default_mode = "Risk-weighted" if (live_exists or norm_exists) else "Full"
    mode = st.selectbox("Equity Mode", modes, index=modes.index(default_mode))
    if mode == "Risk-weighted":
        equity_path = REPORTS / "equity_curve_live.jsonl"
    elif mode == "Risk-normalized":
        equity_path = REPORTS / "equity_curve_norm.jsonl"
    else:
        equity_path = REPORTS / "equity_curve.jsonl"

    equity_df = load_equity_df(equity_path)
    last_equity_value = equity_df["equity"].iloc[-1] if equity_df is not None and not equity_df.empty else None

    rec_value = governance_snapshot.get("rec") or governance_snapshot.get("recommendation")
    if rec_value is None:
        inputs_block = orchestrator_snapshot.get("inputs") if isinstance(orchestrator_snapshot, dict) else {}
        rec_value = inputs_block.get("rec")
    rec_display = str(rec_value or "N/A")
    sci_value = governance_snapshot.get("sci")
    if sci_value is None:
        inputs_block = orchestrator_snapshot.get("inputs") if isinstance(orchestrator_snapshot, dict) else {}
        sci_value = inputs_block.get("sci")
    try:
        sci_display = f"{float(sci_value):.2f}"
    except Exception:
        sci_display = "N/A"
    policy_block = orchestrator_snapshot.get("policy") if isinstance(orchestrator_snapshot, dict) else {}
    pa_on = "ON" if policy_block.get("allow_pa") else "OFF"
    st.markdown(f"**Status:** REC: `{rec_display}` | SCI: `{sci_display}` | PA: `{pa_on}`")

    col_pa.metric("PA Armed", str(pa_status.get("armed", "N/A")) if pa_status else "N/A")
    col_equity.metric(
        f"Last Equity ({mode})",
        f"{float(last_equity_value):,.2f}" if isinstance(last_equity_value, (int, float)) else "N/A",
    )

    # @cursor-guard:dashboard-safe:v1
    # region equity-chart
    render_equity_chart()
    # endregion equity-chart


def portfolio_tab() -> None:
    st.header("Portfolio")
    health = load_json(REPORTS / "portfolio" / "portfolio_health.json") or {}
    pf_snapshot = load_json(REPORTS / "portfolio" / "portfolio_pf.json") or {}

    st.metric("Portfolio PF", pf_snapshot.get("portfolio_pf", "N/A"))
    st.subheader("Health")
    st.json(
        {
            "corr_blocks": health.get("corr_blocks", "N/A"),
            "exposure_blocks": health.get("exposure_blocks", "N/A"),
            "open_positions": health.get("open_positions", {}),
        }
    )

    trades_tail = jsonl_tail(REPORTS / "portfolio" / "ETHUSDT_trades.jsonl", n=10)
    if trades_tail:
        st.subheader("ETHUSDT trades (tail)")
        st.code("\n".join(json.dumps(entry) for entry in trades_tail))
    else:
        st.info("No ETHUSDT trades logged.")


def sandbox_tab() -> None:
    st.header("Sandbox")
    entries = jsonl_tail(REPORTS / "sandbox" / "sandbox_runs.jsonl", n=5)
    if not entries:
        st.info("No sandbox runs recorded.")
        return

    df = pd.DataFrame(
        [
            {
                "id": entry.get("id", "N/A"),
                "child": entry.get("child", "N/A"),
                "pf_adj": entry.get("pf_adj", "N/A"),
                "state": entry.get("state", "N/A"),
                "ts": entry.get("ts", "N/A"),
            }
            for entry in entries
        ]
    )

    def highlight(val: Any) -> str:
        try:
            numeric = float(val)
        except Exception:
            return ""
        if numeric >= 1.0:
            return "background-color: #c6f6d5"
        if numeric >= 0.8:
            return "background-color: #fff7c2"
        return "background-color: #fecaca"

    styler = df.style.map(highlight, subset=["pf_adj"])
    st.dataframe(styler, width='stretch')


def load_backtest_runs() -> List[Dict[str, Any]]:
    data = load_json(REPORTS / "backtest" / "index.json")
    return data if isinstance(data, list) else []


def backtest_tab() -> None:
    st.header("Backtest")
    runs = load_backtest_runs()
    if not runs:
        st.info("No backtests yet.")
        return

    runs.sort(key=lambda item: item.get("ts", ""), reverse=True)
    options: List[str] = []
    option_map: Dict[str, Dict[str, Any]] = {}
    for entry in runs:
        label = (
            f"{entry.get('symbol', 'N/A')} {entry.get('timeframe', 'N/A')} | "
            f"{entry.get('start', 'N/A')}→{entry.get('end', 'N/A')} | "
            f"{entry.get('ts', 'N/A')} | {entry.get('tag') or ''}"
        )
        options.append(label)
        option_map[label] = entry

    selection = st.selectbox("Backtest runs", options, index=0)
    run = option_map.get(selection)
    if not run:
        st.warning("Unable to load run metadata.")
        return

    rel_dir = run.get("dir")
    if not rel_dir:
        st.warning("Run directory missing.")
        return
    run_dir = REPORTS / "backtest" / rel_dir

    summary = load_json(run_dir / "summary.json") or {}
    cols = st.columns(4)
    cols[0].metric("PF", summary.get("pf", "N/A"))
    cols[1].metric("PF Adj", summary.get("pf_adj", "N/A"))
    cols[2].metric("Bars", summary.get("bars", "N/A"))
    cols[3].metric("Trades", summary.get("trades", "N/A"))
    st.caption(
        f"Run dir: {rel_dir} | Tag: {summary.get('tag', 'N/A')} | Start equity: {summary.get('start_equity', 'N/A')}"
    )

    df = load_equity_df_from(run_dir / "equity_curve.jsonl")
    if df is None or len(df) < 2:
        st.caption("Backtest equity curve unavailable.")
    else:
        last_point = df.iloc[-1]
        color = "green" if float(last_point.get("adj_pct") or 0.0) >= 0 else "red"
        zoom_domain = _y_zoom(df.to_dict("records"))
        y_encoding = alt.Y("equity:Q", title="Equity ($)")
        if zoom_domain:
            y_encoding = y_encoding.scale(domain=list(zoom_domain))
        line = alt.Chart(df).mark_line(strokeWidth=2).encode(
            x=alt.X("ts:T", title="Time"),
            y=y_encoding,
        )
        dot = alt.Chart(pd.DataFrame([last_point])).mark_circle(size=90, color=color).encode(
            x="ts:T",
            y="equity:Q",
        )
        st.altair_chart(line + dot, width='stretch')

    trades_tail = jsonl_tail(run_dir / "trades.jsonl", n=15)
    if trades_tail:
        st.subheader("Trades (tail)")
        st.code("\n".join(json.dumps(entry) for entry in trades_tail))
    else:
        st.info("No trades recorded for this run.")


def evolution_tab() -> None:
    st.header("Evolution Pipeline")

    candidates = load_json(REPORTS / "mirror_candidates.json")
    if isinstance(candidates, list) and candidates:
        st.subheader("Mirror Candidates")
        df = pd.DataFrame(
            [
                {
                    "id": item.get("id", "N/A"),
                    "score": item.get("score"),
                    "notes": item.get("notes"),
                    "seed_params": json.dumps(item.get("seed_params", {})),
                }
                for item in candidates
                if isinstance(item, dict)
            ]
        )
        st.dataframe(df, width='stretch')
    else:
        st.info("No mirror candidates found.")

    proposals_tail = jsonl_tail(REPORTS / "promotion_proposals.jsonl", n=5)
    if proposals_tail:
        st.subheader("Promotion Proposals (tail)")
        st.code("\n".join(json.dumps(entry) for entry in proposals_tail))
    else:
        st.info("No promotion proposals recorded.")


def intelligence_tab() -> None:
    st.header("Intelligence")
    summary = load_json(REPORTS / "gpt_summary.json")
    news = load_json(REPORTS / "news_tone.json")
    governance_tail = jsonl_tail(REPORTS / "governance_log.jsonl", n=1)

    if summary:
        st.subheader("GPT Reflection")
        text = summary.get("summary") or summary.get("text") or json.dumps(summary, indent=2)
        truncated, clipped = truncate_text(text)
        st.write(truncated)
        if clipped:
            with st.expander("Full reflection"):
                st.write(text)
    else:
        st.info("No GPT reflection summary.")

    if news:
        st.subheader("News Tone")
        st.json(news)
    else:
        st.info("No news tone snapshot.")

    if governance_tail:
        st.subheader("Governance Log (tail)")
        st.json(governance_tail[0])
    else:
        st.info("No governance log entries.")


def feeds_tab() -> None:
    st.header("Feeds / Health")
    feeds_snapshot = load_json(REPORTS / "feeds_snapshot.json")
    if feeds_snapshot:
        st.subheader("Feeds Snapshot")
        st.json(feeds_snapshot)
    else:
        st.info("Feeds snapshot not available.")

    live_state = load_json(REPORTS / "live_loop_state.json")
    if live_state:
        st.subheader("Live Loop State")
        st.json(live_state)

    ops_tail = read_text_tail(LOGS / "ops.log", lines=5)
    if ops_tail:
        st.subheader("Ops Log Tail")
        st.code("\n".join(ops_tail))
    else:
        st.info("Ops log empty.")


def dream_tab() -> None:
    st.header("Dream Mode")

    summary = load_json(REPORTS / "dream_summary.json") or {}
    snapshot = load_json(REPORTS / "dream_snapshot.json") or {}
    log_tail = jsonl_tail(REPORTS / "dream_log.jsonl", n=1)

    governance = summary.get("governance") if isinstance(summary.get("governance"), dict) else {}
    snapshot_governance = snapshot.get("governance") if isinstance(snapshot.get("governance"), dict) else {}
    pf_trend = summary.get("pf_adj_trend") if isinstance(summary.get("pf_adj_trend"), dict) else {}
    trades = summary.get("trades") if isinstance(summary.get("trades"), dict) else {}

    sci = governance.get("sci")
    slope10 = pf_trend.get("slope_10")
    proposal = summary.get("proposal_kind") or snapshot.get("proposal_kind")

    col_sci, col_slope, col_prop = st.columns(3)
    col_sci.metric("SCI", f"{float(sci):.3f}" if isinstance(sci, (int, float)) else "N/A")
    col_slope.metric("Slope 10", f"{float(slope10):.4f}" if isinstance(slope10, (int, float)) else "N/A")
    col_prop.metric("Proposal", proposal or "N/A")

    ts = summary.get("ts") or snapshot.get("ts") or "N/A"
    rec = governance.get("rec") or snapshot_governance.get("rec")
    sci_display = f"{float(sci):.3f}" if isinstance(sci, (int, float)) else "N/A"
    st.write(f"Last run: {ts} • Rec: {rec or 'N/A'} • SCI: {sci_display}")

    if trades:
        st.subheader("Trades Snapshot")
        st.table(pd.DataFrame([trades]))

    gpt_text = summary.get("gpt_text")
    if not gpt_text and log_tail:
        tail_entry = log_tail[-1]
        tail_text = tail_entry.get("gpt_text") or tail_entry.get("summary")
        if isinstance(tail_text, str):
            gpt_text = tail_text
    if isinstance(gpt_text, str) and gpt_text.strip():
        truncated, clipped = truncate_text(gpt_text, limit=600)
        st.subheader("Dream Commentary")
        st.write(truncated)
        if clipped:
            with st.expander("Full Dream Commentary"):
                st.write(gpt_text)

    with st.expander("Dream Summary JSON"):
        st.json(summary or {"note": "No summary available."})

    if "dream_output" in st.session_state:
        with st.expander("Dream Output"):
            st.code(st.session_state.pop("dream_output") or "No output captured.")

    if st.button("Run Dream Now"):
        output = ""
        with st.spinner("Running dream diagnostics..."):
            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "engine_alpha.reflect.diagnostic_dream"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                combined = "\n".join(
                    part for part in [proc.stdout.strip(), proc.stderr.strip()] if part
                ).strip()
                output = combined or "No output captured."
            except subprocess.TimeoutExpired:
                output = "Dream run timed out after 120 seconds."
            except Exception as exc:  # pragma: no cover - defensive
                output = f"Dream run failed: {exc}"
        st.session_state["dream_output"] = output
        st.rerun()


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="Alpha Chloe Dashboard", layout="wide")

    st_autorefresh(interval=10000, key="auto")
    st.sidebar.caption("Auto-refresh cadence: ~10 seconds (Phase 35).")

    render_heartbeat_and_activity()

    st.title("Alpha Chloe Dashboard")
    st.caption("Read-only metrics with health analytics")

    tabs = st.tabs(
        ["Overview", "Portfolio", "Evolution", "Sandbox", "Backtest", "Intelligence", "Dream", "Feeds/Health"]
    )
    with tabs[0]:
        overview_tab()
    with tabs[1]:
        portfolio_tab()
    with tabs[2]:
        evolution_tab()
    with tabs[3]:
        sandbox_tab()
    with tabs[4]:
        backtest_tab()
    with tabs[5]:
        intelligence_tab()
    with tabs[6]:
        dream_tab()
    with tabs[7]:
        feeds_tab()

    st.session_state["_last_refresh"] = time.time()
    st.caption("Auto-refresh active: dashboard updates every ~10 seconds.")


if __name__ == "__main__" and os.getenv("CHLOE_DASH_HEALTHCHECK") != "1":
    main()
