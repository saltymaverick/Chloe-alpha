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

import streamlit as st

from engine_alpha.core.paths import REPORTS, LOGS, CONFIG

from datetime import datetime, timezone

MIN_REFRESH = 5
MAX_REFRESH = 120
DEFAULT_REFRESH = 10


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
            data = f.readlines()[-lines:]
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for line in data:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def safe_text(path: Path, lines: int = 3) -> str:
    if not path.exists():
        return ""
    try:
        with path.open("r") as f:
            tail = f.readlines()[-lines:]
        return "".join(tail)
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

    curve = load_jsonl_tail(REPORTS / "equity_curve.jsonl", lines=300)
    if curve:
        chart_data = {
            "ts": [point.get("ts") for point in curve],
            "equity": [point.get("equity") for point in curve],
        }
        st.line_chart(chart_data, x="ts", y="equity")
    else:
        st.info("Equity curve not available yet")

    if st.button("Run acceptance now"):
        with st.spinner("Executing acceptance check..."):
            try:
                proc = subprocess.run(
                    ["python", "tools/acceptance_check.py"],
                    capture_output=True,
                    text=True,
                    cwd=REPORTS.parent,
                    check=False,
                )
                output = proc.stdout.strip() or proc.stderr.strip()
                if not output:
                    output = "No output captured"
                st.code(output)
            except Exception as exc:
                st.error(f"Acceptance run failed: {exc}")


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


def main():
    st.set_page_config(page_title="Alpha Chloe Dashboard", layout="wide")
    refresh = st.sidebar.number_input(
        "Refresh (sec)",
        min_value=MIN_REFRESH,
        max_value=MAX_REFRESH,
        value=DEFAULT_REFRESH,
        step=5,
    )
    st.title("Alpha Chloe Dashboard")
    st.caption(f"Read-only metrics (auto-refresh every {refresh}s)")

    tabs = st.tabs(["Overview", "Portfolio", "Intelligence", "Feeds/Health"])
    with tabs[0]:
        overview_tab()
    with tabs[1]:
        portfolio_tab()
    with tabs[2]:
        intelligence_tab()
    with tabs[3]:
        feeds_tab()

    st.write("Last refresh:", _now())
    time.sleep(refresh)
    st.experimental_rerun()


if __name__ == "__main__":
    main()
