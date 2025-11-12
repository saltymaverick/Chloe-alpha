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
# region bias-tile
_ci_get = lambda o,k: (o.get(k) if isinstance(o,dict) and k in o else next((o[v] for v in (o or {}) if isinstance(v,str) and v.lower()==k.lower()), None))

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

    col_pf, col_bias, col_conf = st.columns(3)
    # @cursor-guard:pf-tile:v1
    # region pf-tile
    with col_pf:
        render_pf_tile()
    # endregion pf-tile
    # @cursor-guard:dashboard-safe:v1
    # region bias-tile
    with col_bias:
        render_bias_tile()
    # endregion bias-tile
    # @cursor-guard:dashboard-safe:v1
    # region confidence-tile
    with col_conf:
        render_confidence_tile()
    # endregion confidence-tile

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

    if equity_df is None or len(equity_df) < 2:
        st.caption("Equity curve: N/A (need ≥2 points)")
        if mode == "Risk-weighted":
            st.info("Run: python -m tools.diagnostic_risk_exec")
        elif mode == "Risk-normalized":
            st.info("Run: python -m tools.normalize_equity")
    else:
        last_point = equity_df.iloc[-1]
        color = "green" if last_point.get("adj_pct", 0.0) >= 0 else "red"
        zoom_domain = _y_zoom(equity_df.to_dict("records"))
        y_encoding = alt.Y("equity:Q", title="Equity ($)")
        if zoom_domain:
            y_encoding = y_encoding.scale(domain=list(zoom_domain))
        line = alt.Chart(equity_df).mark_line(strokeWidth=2).encode(
            x=alt.X("ts:T", title="Time"),
            y=y_encoding,
        )
        dot = alt.Chart(pd.DataFrame([last_point])).mark_circle(size=90, color=color).encode(
            x="ts:T",
            y="equity:Q",
        )
        st.altair_chart(line + dot, width='stretch')


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
