from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from engine_alpha.core.paths import REPORTS

HISTORY_PATH = REPORTS / "debug" / "signals_history.jsonl"


def _load_history(limit: int = 600) -> pd.DataFrame:
    if not HISTORY_PATH.exists():
        return pd.DataFrame()
    try:
        with HISTORY_PATH.open("r") as handle:
            lines = handle.readlines()[-limit:]
    except Exception:
        return pd.DataFrame()
    records = []
    for line in lines:
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                records.append(parsed)
        except Exception:
            continue
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    if "bar_ts" in df.columns:
        df["bar_ts"] = pd.to_datetime(df["bar_ts"], errors="coerce")
    return df


def render() -> None:
    st.header("Signals Heatmap")
    df = _load_history()
    if df.empty:
        st.info("No signals history yet. Run the live loop for a few bars.")
        return

    df = df.dropna(subset=["bar_ts"]).sort_values("bar_ts")
    st.write(f"Loaded {len(df)} history rows from {HISTORY_PATH.name}.")

    recent = df.tail(600)
    conf_pivot = (
        recent.pivot_table(index="bar_ts", columns="symbol", values="conf")
        .tail(50)
        .fillna(0.0)
    )
    edge_pivot = (
        recent.pivot_table(index="bar_ts", columns="symbol", values="combined_edge")
        .tail(50)
        .fillna(0.0)
    )

    st.subheader("Confidence Heatmap (Last 50 bars)")
    st.dataframe(conf_pivot.style.background_gradient(cmap="Blues"))

    st.subheader("Combined Edge Heatmap (Last 50 bars)")
    st.dataframe(edge_pivot.style.background_gradient(cmap="PuOr"))

    st.subheader("Most Recent Entries")
    st.dataframe(
        recent[["bar_ts", "symbol", "regime", "dir", "conf", "combined_edge", "soft_mode"]].tail(40)
    )

