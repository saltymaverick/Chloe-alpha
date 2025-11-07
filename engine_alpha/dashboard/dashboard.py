"""
Streamlit dashboard - Phase 16
Displays key reports from /reports and /logs.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import altair as alt
import pandas as pd
import streamlit as st

from engine_alpha.core.paths import REPORTS, LOGS, CONFIG

from datetime import datetime, timezone

REFRESH_OPTIONS = {"Off": None, "5s": 5, "10s": 10, "30s": 30}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with path.open("r") as f:
            return json.load(f)
    except Exception:
        return None


def load_jsonl_tail(path: Path, lines: int = 1) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r") as f:
            rows = f.readlines()[-lines:]
    except Exception:
        return []
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


def load_equity_df() -> Optional[pd.DataFrame]:
    path = REPORTS / "equity_curve.jsonl"
    if not path.exists():
        return None
    rows: List[Dict[str, Any]] = []
    try:
        with path.open("r") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    rows.append(
                        {
                            "ts": pd.to_datetime(obj.get("ts")),
                            "equity": float(obj.get("equity", float("nan"))),
                            "adj_pct": float(obj.get("adj_pct", 0.0)),
                        }
                    )
                except Exception:
                    continue
    except Exception:
        return None
    df = pd.DataFrame(rows).dropna(subset=["ts", "equity"])
    if len(df) < 2:
        return None
    return df.sort_values("ts").tail(300)


def safe_text(path: Path, lines: int = 3) -> str:
    if not path.exists():
        return ""
    try:
        with path.open("r") as f:
            return "".join(f.readlines()[-lines:])
    except Exception:
        return ""


def get_value(data: Optional[Dict[str, Any]], *keys, default=None):
    cur: Any = data or {}
    for key in keys:
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return default
    return cur


def overview_tab():
    st.header("Overview")

    pf_local = load_json(REPORTS / "pf_local.json")
    pf_local_adj = load_json(REPORTS / "pf_local_adj.json")
    pa_status = load_json(REPORTS / "pa_status.json")
    equity_tail = load_jsonl_tail(REPORTS / "equity_curve.jsonl", lines=1)
    last_equity = get_value(equity_tail[0], "equity", default="N/A") if equity_tail else "N/A"

    col_pf, col_adj, col_pa, col_equity = st.columns(4)
    col_pf.metric("PF Local", get_value(pf_local, "pf", default="N/A"))
    col_adj.metric("PF Local Adj", get_value(pf_local_adj, "pf", default="N/A"))
    col_pa.metric("PA Armed", str(get_value(pa_status, "armed", default="N/A")))
    col_equity.metric("Last Equity", last_equity)

    df = load_equity_df()
    if df is not None and not df.empty:
        last_point = df.iloc[-1]
        color = "green" if last_point.get("adj_pct", 0.0) >= 0 else "red"
        base = alt.Chart(df).mark_line(strokeWidth=2).encode(
            x=alt.X("ts:T", title="Time"),
            y=alt.Y("equity:Q", title="Equity ($)")
        )
        dot = alt.Chart(pd.DataFrame([last_point])).mark_circle(size=90, color=color).encode(
            x="ts:T",
            y="equity:Q",
        )
        st.altair_chart(base + dot, use_container_width=True)
    else:
        st.caption("Equity curve: N/A (need ≥2 points)")

    if st.button("Run Acceptance Check"):
        with st.spinner("Running acceptance check..."):
            try:
                proc = subprocess.run(
                    ["python", "-m", "tools.acceptance_check"],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    cwd=REPORTS.parent,
                )
                output = proc.stdout.strip() or proc.stderr.strip() or "No output captured"
                try:
                    st.json(json.loads(output))
                except Exception:
                    st.code(output)
            except FileNotFoundError:
                st.error("tools/acceptance_check.py not found")
            except subprocess.TimeoutExpired:
                st.error("Acceptance check timed out")


def portfolio_tab():
    st.header("Portfolio")
    portfolio_dir = REPORTS / "portfolio"

    pf = load_json(portfolio_dir / "portfolio_pf.json")
    health = load_json(portfolio_dir / "portfolio_health.json")
    snapshot = load_json(portfolio_dir / "portfolio_snapshot.json")

    if pf:
        st.metric("Portfolio PF", pf.get("portfolio_pf", "N/A"))
    if health:
        st.write(
            "Health",
            {
                "corr_blocks": health.get("corr_blocks"),
                "exposure_blocks": health.get("exposure_blocks"),
                "net_exposure": sum(health.get("open_positions", {}).values()),
                "cap": get_value(load_json(CONFIG / "asset_list.yaml"), "guard", "net_exposure_cap", default="N/A"),
            },
        )

    symbols = snapshot.get("symbols", []) if snapshot else []
    if not symbols:
        symbols = [p.name.split("_")[0] for p in portfolio_dir.glob("*_trades.jsonl")]

    if symbols:
        cols = st.columns(len(symbols))
        for idx, symbol in enumerate(symbols):
            data = load_json(portfolio_dir / f"{symbol}_pf.json")
            if data:
                cols[idx % len(cols)].metric(symbol, data.get("pf", "N/A"))

    eth_trades = safe_text(portfolio_dir / "ETHUSDT_trades.jsonl", lines=5)
    if eth_trades:
        st.subheader("ETHUSDT trade tail")
        st.code(eth_trades)
    else:
        st.info("No ETHUSDT trades logged yet")


def intelligence_tab():
    st.header("Intelligence")
    cols = st.columns(3)

    with cols[0]:
        st.subheader("Dream")
        st.json(load_json(REPORTS / "dream_snapshot.json") or {"status": "N/A"})
        dream_tail = load_jsonl_tail(REPORTS / "dream_log.jsonl", 1)
        if dream_tail:
            st.write(dream_tail[0])
    with cols[1]:
        st.subheader("Evolver")
        st.json(load_json(REPORTS / "evolver_snapshot.json") or {"status": "N/A"})
        lineage_tail = load_jsonl_tail(REPORTS / "strategy_lineage.jsonl", 1)
        if lineage_tail:
            st.write(lineage_tail[0])
    with cols[2]:
        st.subheader("Confidence")
        entries = load_jsonl_tail(REPORTS / "confidence_tune.jsonl", 3)
        if entries:
            st.table(entries)
        else:
            st.write("No tune data yet")


def feeds_tab():
    st.header("Feeds & Health")
    snapshot = load_json(REPORTS / "feeds_snapshot.json")
    if snapshot:
        for exchange, data in snapshot.items():
            if exchange == "ts":
                continue
            st.subheader(exchange.upper())
            enabled = data.get("enabled", False)
            st.write("Enabled", enabled)
            if not enabled:
                continue
            time_info = data.get("time", {})
            st.write("Clock skew", time_info.get("clock_skew_ms", "N/A"))
            symbols_info = data.get("symbols", {}).get("symbols", {})
            for symbol, info in symbols_info.items():
                if info.get("ok"):
                    st.success(f"{symbol}: ok ({info.get('latency_ms')} ms)")
                else:
                    st.error(f"{symbol}: {info.get('error', 'fail')}")
    ops_tail = safe_text(LOGS / "ops.log", 3)
    if ops_tail:
        st.subheader("Ops log tail")
        st.code(ops_tail)


def sandbox_tab():
    st.header("Sandbox")
    runs_path = REPORTS / "sandbox" / "sandbox_runs.jsonl"
    status_path = REPORTS / "sandbox" / "sandbox_status.json"

    if not runs_path.exists() and not status_path.exists():
        st.info("No sandbox data yet")
        return

    runs = load_jsonl_tail(runs_path, lines=5)
    if runs:
        df = pd.DataFrame(runs)
        df = df[[col for col in ["id", "child", "pf_adj", "state", "ts"] if col in df.columns]]
        if not df.empty:
            def highlight(row):
                val = row.get("pf_adj")
                if not isinstance(val, (int, float)):
                    return [""] * len(row)
                if val >= 1.0:
                    color = "background-color: rgba(0,200,0,0.2)"
                elif val >= 0.8:
                    color = "background-color: rgba(255,200,0,0.2)"
                else:
                    color = "background-color: rgba(255,0,0,0.2)"
                return [color] * len(row)
            st.dataframe(df.style.apply(highlight, axis=1), use_container_width=True)
    else:
        st.write("No sandbox runs yet")

    status = load_json(status_path)
    if status:
        st.subheader("Status")
        st.json(status)

    if runs:
        last_id = runs[-1].get("id")
        if last_id:
            trades_path = REPORTS / "sandbox" / last_id / "trades.jsonl"
            trades_tail = safe_text(trades_path, lines=3)
            if trades_tail:
                with st.expander("Last run trades tail"):
                    st.code(trades_tail)

    if st.button("Run Sandbox Cycle"):
        with st.spinner("Running sandbox cycle..."):
            try:
                proc = subprocess.run(
                    ["python3", "-m", "engine_alpha.evolve.diagnostic_sandbox", "--steps", "150", "--max-new", "1"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                output = proc.stdout.strip() or proc.stderr.strip() or "No output captured"
                with st.expander("Sandbox Output"):
                    st.code(output)
            except subprocess.TimeoutExpired:
                st.error("Sandbox cycle timed out")
            except Exception as exc:
                st.error(f"Sandbox cycle failed: {exc}")
            st.rerun()


def main():
    st.set_page_config(page_title="Alpha Chloe Dashboard", layout="wide")
    refresh_choice = st.sidebar.selectbox("Auto-refresh", list(REFRESH_OPTIONS.keys()), index=1)
    st.title("Alpha Chloe Dashboard")
    st.caption("Read-only metrics with health analytics")

    tabs = st.tabs(["Overview", "Portfolio", "Intelligence", "Feeds/Health", "Sandbox"])
    with tabs[0]:
        overview_tab()
    with tabs[1]:
        portfolio_tab()
    with tabs[2]:
        intelligence_tab()
    with tabs[3]:
        feeds_tab()
    with tabs[4]:
        sandbox_tab()

    st.write("Last refresh:", _now())
    st.query_params = {"ts": _now()}

    refresh_seconds = REFRESH_OPTIONS.get(refresh_choice)
    if refresh_seconds:
        time.sleep(refresh_seconds)
        st.rerun()


if __name__ == "__main__":
    main()
