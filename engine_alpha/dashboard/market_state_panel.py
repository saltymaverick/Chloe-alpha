from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

REPORT_PATH = Path("reports/research/market_state_summary.json")


def _load_report() -> dict:
    if not REPORT_PATH.exists():
        return {}
    try:
        data = REPORT_PATH.read_text().strip()
        return json.loads(data) if data else {}
    except Exception:
        return {}


def render() -> None:
    st.header("Market State Summary")

    report = _load_report()
    if not report:
        st.info("No market summary found. Run: `python3 -m tools.market_state_summary`.")
        return

    st.caption(
        f"Generated at {report.get('generated_at', 'unknown')} "
        f"| Timeframe {report.get('timeframe', 'unknown')}"
    )

    assets = report.get("assets", {})
    if not assets:
        st.warning("Report has no asset entries.")
        return

    rows = []
    for symbol, info in assets.items():
        rows.append(
            {
                "symbol": symbol,
                "regime": info.get("regime"),
                "slope_5": info.get("slope_5"),
                "slope_20": info.get("slope_20"),
                "atr_rel": info.get("atr_rel"),
                "feed_state": info.get("feed_state"),
                "expected_frequency": info.get("expected_trade_frequency"),
                "comment": info.get("comment"),
            }
        )

    df = pd.DataFrame(rows)
    st.dataframe(
        df.sort_values(["feed_state", "symbol"]),
        use_container_width=True,
    )

