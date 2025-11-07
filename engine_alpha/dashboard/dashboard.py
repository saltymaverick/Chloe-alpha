"""
Streamlit dashboard - Phase 10 (read-only)
Displays key reports from /reports and /logs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import streamlit as st

from engine_alpha.core.paths import REPORTS, LOGS

from datetime import datetime, timezone

def _now() -> str:
    """Return ISO8601 UTC timestamp, e.g. 2025-11-07T16:25:00Z"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

REFRESH_SECONDS = 10


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
            data = f.readlines()[-lines:]
        out = []
        for line in data:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
        return out
    except Exception:
        return []


def overview_tab() -> None:
    st.header("Overview")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("PF local")
        st.json(_read_json(REPORTS / "pf_local.json") or {"pf": "N/A"})
        st.subheader("PF live")
        st.json(_read_json(REPORTS / "pf_live.json") or {"pf": "N/A"})
    with col2:
        st.subheader("PA status")
        st.json(_read_json(REPORTS / "pa_status.json") or {"armed": "N/A"})
        st.subheader("Ops health (last 5)")
        tail = _read_jsonl_tail(LOGS / "ops.log", lines=5)
        if tail:
            for entry in tail:
                st.write(entry)
        else:
            st.write("No ops log yet")


def portfolio_tab() -> None:
    st.header("Portfolio")
    portfolio_dir = REPORTS / "portfolio"
    st.subheader("Portfolio PF")
    st.json(_read_json(portfolio_dir / "portfolio_pf.json") or {"portfolio_pf": "N/A"})

    symbols_seen = []
    if (portfolio_dir / "portfolio_snapshot.json").exists():
        snapshot = _read_json(portfolio_dir / "portfolio_snapshot.json")
        symbols_seen = snapshot.get("symbols", [])
    if not symbols_seen:
        # fallback: scan files
        symbols_seen = [p.name.split("_")[0] for p in portfolio_dir.glob("*_trades.jsonl")]

    for symbol in symbols_seen:
        st.subheader(f"{symbol} metrics")
        st.json(_read_json(portfolio_dir / f"{symbol}_pf.json") or {"pf": "N/A"})
        tail = _read_jsonl_tail(portfolio_dir / f"{symbol}_trades.jsonl", lines=5)
        if tail:
            for entry in tail:
                st.write(entry)
        else:
            st.write("No trades logged")


def intelligence_tab() -> None:
    st.header("Intelligence")
    cols = st.columns(3)

    with cols[0]:
        st.subheader("Dream mode")
        st.json(_read_json(REPORTS / "dream_snapshot.json") or {"status": "N/A"})
        st.json(_read_json(REPORTS / "dream_proposals.json") or {"proposal": "N/A"})
        tail = _read_jsonl_tail(REPORTS / "dream_log.jsonl", lines=1)
        if tail:
            st.write("Last dream:", tail[0])
        else:
            st.write("No dream log yet")

    with cols[1]:
        st.subheader("Strategy evolver")
        st.json(_read_json(REPORTS / "evolver_snapshot.json") or {"status": "N/A"})
        lineage_tail = _read_jsonl_tail(REPORTS / "strategy_lineage.jsonl", lines=1)
        run_tail = _read_jsonl_tail(REPORTS / "evolver_runs.jsonl", lines=1)
        if lineage_tail:
            st.write("Last lineage: ", lineage_tail[0])
        if run_tail:
            st.write("Last run: ", run_tail[0])
        if not (lineage_tail or run_tail):
            st.write("No evolver runs yet")

    with cols[2]:
        st.subheader("Mirror mode")
        st.json(_read_json(REPORTS / "mirror_snapshot.json") or {"status": "N/A"})
        tail = _read_jsonl_tail(REPORTS / "mirror_memory.jsonl", lines=5)
        if tail:
            for entry in tail:
                st.write(entry)
        else:
            st.write("No mirror memory yet")


def signals_tab() -> None:
    st.header("Signals / Council")
    st.json(_read_json(REPORTS / "council_snapshot.json") or {"status": "N/A"})


def main():
    st.set_page_config(page_title="Alpha Chloe Dashboard", layout="wide")
    st.title("Alpha Chloe Dashboard")
    st.caption("Read-only metrics (updates every 10 seconds)")

    st_autorefresh = st.empty()
    st_autorefresh.empty()

    tabs = st.tabs(["Overview", "Portfolio", "Intelligence", "Signals/Council"])

    with tabs[0]:
        overview_tab()
    with tabs[1]:
        portfolio_tab()
    with tabs[2]:
        intelligence_tab()
    with tabs[3]:
        signals_tab()

    st.query_params(ts=_now())
    st.write("Last refresh:", _now())


if __name__ == "__main__":
    main()
