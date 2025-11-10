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

from engine_alpha.core.paths import REPORTS, LOGS, DATA


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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

    pf_local_adj = load_json(REPORTS / "pf_local_adj.json")
    pa_status = load_json(REPORTS / "pa_status.json")

    modes = ["Risk-weighted", "Risk-normalized", "Full"]
    live_curve_path = REPORTS / "equity_curve_live.jsonl"
    live_exists = live_curve_path.exists()
    norm_exists = (REPORTS / "equity_curve_norm.jsonl").exists()
    default_mode = "Risk-weighted" if live_exists else ("Risk-normalized" if norm_exists else "Full")
    mode = st.selectbox("Equity Mode", modes, index=modes.index(default_mode))
    if mode == "Risk-weighted":
        equity_path = REPORTS / "equity_curve_live.jsonl"
    elif mode == "Risk-normalized":
        equity_path = REPORTS / "equity_curve_norm.jsonl"
    else:
        equity_path = REPORTS / "equity_curve.jsonl"

    equity_df = load_equity_df(equity_path)
    pf_live = load_json(REPORTS / "pf_local_live.json")
    live_pf_value = pf_live.get("pf") if isinstance(pf_live, dict) else None
    pf_full = load_json(REPORTS / "pf_local.json")
    full_pf_value = pf_full.get("pf") if isinstance(pf_full, dict) else None
    pf_label = "PF"
    pf_value = None
    if isinstance(live_pf_value, (int, float)):
        pf_label = "PF (Risk-weighted)"
        pf_value = live_pf_value
    elif isinstance(full_pf_value, (int, float)):
        pf_label = "PF (Full)"
        pf_value = full_pf_value

    last_equity_value = equity_df["equity"].iloc[-1] if equity_df is not None and not equity_df.empty else None

    if isinstance(pf_value, (int, float)):
        pf_display = "∞" if pf_value == float("inf") else f"{pf_value:.4f}"
    else:
        pf_display = "N/A"

    col_pf, col_adj, col_pa, col_equity = st.columns(4)
    col_pf.metric(pf_label, pf_display)
    col_adj.metric("PF Local Adj", pf_local_adj.get("pf", "N/A") if pf_local_adj else "N/A")
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
        line = alt.Chart(equity_df).mark_line(strokeWidth=2).encode(
            x=alt.X("ts:T", title="Time"),
            y=alt.Y("equity:Q", title="Equity ($)"),
        )
        dot = alt.Chart(pd.DataFrame([last_point])).mark_circle(size=90, color=color).encode(
            x="ts:T",
            y="equity:Q",
        )
        st.altair_chart(line + dot, use_container_width=True)


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

    st.dataframe(df.style.applymap(highlight, subset=["pf_adj"]), use_container_width=True)


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
        line = alt.Chart(df).mark_line(strokeWidth=2).encode(
            x=alt.X("ts:T", title="Time"),
            y=alt.Y("equity:Q", title="Equity ($)"),
        )
        dot = alt.Chart(pd.DataFrame([last_point])).mark_circle(size=90, color=color).encode(
            x="ts:T",
            y="equity:Q",
        )
        st.altair_chart(line + dot, use_container_width=True)

    trades_tail = jsonl_tail(run_dir / "trades.jsonl", n=15)
    if trades_tail:
        st.subheader("Trades (tail)")
        st.code("\n".join(json.dumps(entry) for entry in trades_tail))
    else:
        st.info("No trades recorded for this run.")


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

    refresh_choice = st.sidebar.selectbox(
        "Auto-refresh",
        ["Off", "5 s", "10 s", "30 s"],
        index=2,
    )
    interval_map = {"Off": 0, "5 s": 5, "10 s": 10, "30 s": 30}
    interval_sec = interval_map.get(refresh_choice, 0)

    if st.sidebar.button("Refresh now"):
        st.info("Manual refresh is disabled in this SAFE MODE build.")

    render_heartbeat_and_activity()

    st.title("Alpha Chloe Dashboard")
    st.caption("Read-only metrics with health analytics")

    tabs = st.tabs(["Overview", "Portfolio", "Sandbox", "Backtest", "Intelligence", "Dream", "Feeds/Health"])
    with tabs[0]:
        overview_tab()
    with tabs[1]:
        portfolio_tab()
    with tabs[2]:
        sandbox_tab()
    with tabs[3]:
        backtest_tab()
    with tabs[4]:
        intelligence_tab()
    with tabs[5]:
        dream_tab()
    with tabs[6]:
        feeds_tab()

    if "_last_refresh" not in st.session_state:
        st.session_state["_last_refresh"] = time.time()

    if interval_sec:
        st.caption("Auto-refresh is disabled in this SAFE MODE build.")


if __name__ == "__main__" and os.getenv("CHLOE_DASH_HEALTHCHECK") != "1":
    main()
