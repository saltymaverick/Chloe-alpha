"""
ETH Trades Panel — friendly view of recent ETH paper trades.
"""

from __future__ import annotations

from pathlib import Path
import json
import pandas as pd
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[2]
REPORTS_DIR = ROOT_DIR / "reports"
TRADES_PATH = REPORTS_DIR / "trades.jsonl"


def _read_trades() -> list[dict]:
    if not TRADES_PATH.exists():
        return []

    trades = []
    with TRADES_PATH.open("r") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                trade = json.loads(line)
            except json.JSONDecodeError:
                continue
            trades.append(trade)
    return trades


def render() -> None:
    st.title("ETH Trades")
    st.caption("Recent ETH paper trades with context and PnL.")

    trades = _read_trades()
    if not trades:
        st.info("No trades recorded yet.")
        return

    eth_trades = []
    for trade in trades:
        symbol = trade.get("symbol", "ETHUSDT").upper()
        if symbol != "ETHUSDT":
            continue
        if trade.get("type") != "close":
            continue
        pct = float(trade.get("pct", 0.0))
        eth_trades.append(
            {
                "ts": trade.get("ts"),
                "pct": pct * 100,  # convert to percentage
                "regime": trade.get("regime", "unknown"),
                "strategy": trade.get("strategy", trade.get("strategy_name", "n/a")),
                "exit_reason": trade.get("exit_reason", "n/a"),
            }
        )

    if not eth_trades:
        st.info("No ETH trades yet. Chloe is still learning.")
        return

    df = pd.DataFrame(eth_trades)
    df = df.sort_values(by="ts", ascending=False)

    total = len(df)
    winners = (df["pct"] > 0).sum()
    losers = (df["pct"] < 0).sum()
    avg_win = df[df["pct"] > 0]["pct"].mean() if winners else 0.0
    avg_loss = df[df["pct"] < 0]["pct"].mean() if losers else 0.0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total ETH trades", total)
    col2.metric("Winners", winners)
    col3.metric("Losers", losers)
    col4.metric("Avg win / loss", f"{avg_win:.2f}% / {avg_loss:.2f}%")

    display_df = df.head(20).copy()
    display_df["pct"] = display_df["pct"].map(lambda v: f"{v:+.2f}%")
    display_df.rename(
        columns={
            "ts": "Timestamp",
            "pct": "PnL",
            "regime": "Regime",
            "strategy": "Strategy",
            "exit_reason": "Exit",
        },
        inplace=True,
    )

    st.dataframe(display_df, use_container_width=True, hide_index=True)
    st.caption("Showing latest 20 closes. Chloe trades ETH only in paper mode for now.")

