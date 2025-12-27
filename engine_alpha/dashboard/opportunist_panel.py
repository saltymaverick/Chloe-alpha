from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from engine_alpha.core.paths import REPORTS

OPPORTUNIST_DIR = REPORTS / "opportunist"
CANDIDATES_PATH = OPPORTUNIST_DIR / "opportunist_candidates.json"
MICRO_RESEARCH_PATH = OPPORTUNIST_DIR / "micro_research.json"
TRADES_PATH = OPPORTUNIST_DIR / "opportunist_trades.jsonl"


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _load_trades(path: Path, limit: int = 50) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    with path.open("r") as handle:
        lines = handle.readlines()
    if not lines:
        return pd.DataFrame()
    tail = lines[-limit:]
    try:
        records = [json.loads(line) for line in tail if line.strip()]
    except json.JSONDecodeError:
        records = []
    return pd.DataFrame(records)


def render() -> None:
    st.header("Opportunist Scanner")
    st.caption("Scan everything → micro research → paper trades (sandbox).")

    st.subheader("Top Movers (scan)")
    candidates = _load_json(CANDIDATES_PATH)
    cand_df = pd.DataFrame(candidates.get("candidates", []))
    if cand_df.empty:
        st.info("No opportunist candidates yet. Run `python3 -m tools.run_opportunist_scan`.")
    else:
        st.dataframe(cand_df)

    st.subheader("Micro Research Summary")
    micro = _load_json(MICRO_RESEARCH_PATH)
    micro_df = pd.DataFrame(micro.get("results", []))
    if micro_df.empty:
        st.info("Micro research has not been generated yet.")
    else:
        st.dataframe(micro_df)

    st.subheader("Recent Paper Trades")
    trades_df = _load_trades(TRADES_PATH)
    if trades_df.empty:
        st.info("No opportunist paper trades logged yet.")
    else:
        st.dataframe(trades_df)

