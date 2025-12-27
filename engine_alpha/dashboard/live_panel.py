"""
Live Panel — Trade blotter and current positions
"""

from __future__ import annotations

from pathlib import Path
import json
import streamlit as st
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]
REPORTS_DIR = ROOT_DIR / "reports"
DATA_DIR = ROOT_DIR / "data"


def _load_trades(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    
    records = []
    with path.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    
    if not records:
        return pd.DataFrame()
    
    df = pd.DataFrame(records)
    if "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"])
    return df


def render():
    st.title("Live Trading — Blotter")
    
    trades_path = REPORTS_DIR / "trades.jsonl"
    df = _load_trades(trades_path)
    
    if df.empty:
        st.info("No trades recorded yet.")
    else:
        st.subheader("Recent Trades")
        st.dataframe(df.sort_values("ts", ascending=False).head(50))
    
    st.subheader("Current Position (if tracked)")
    pos_path = REPORTS_DIR / "position.json"
    if pos_path.exists():
        pos = json.loads(pos_path.read_text())
        st.json(pos)
    else:
        st.info("No position.json found. If you track open positions, write them there.")
    
    st.subheader("Live Candles Snapshot")
    ohlcv_dir = DATA_DIR / "ohlcv"
    candidates = list(ohlcv_dir.glob("*_live.csv"))
    if not candidates:
        st.info("No live OHLCV files found in data/ohlcv.")
    else:
        file = st.selectbox("Choose live feed", candidates, format_func=lambda p: p.name)
        df_c = pd.read_csv(file)
        if "ts" in df_c.columns:
            df_c["ts"] = pd.to_datetime(df_c["ts"])
            df_c = df_c.sort_values("ts")
        st.dataframe(df_c.tail(50))


