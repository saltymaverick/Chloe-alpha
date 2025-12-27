from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

REPORT_PATH = Path("reports/research/staleness_overseer.json")


def _load_report() -> dict:
    if not REPORT_PATH.exists():
        return {}
    try:
        data = REPORT_PATH.read_text().strip()
        return json.loads(data) if data else {}
    except Exception:
        return {}


def render() -> None:
    st.header("Staleness & Activity")

    report = _load_report()
    if not report:
        st.info("No staleness report found. Run: `python3 -m tools.staleness_report`.")
        return

    st.caption(
        f"Phase: {report.get('phase', 'unknown')} | "
        f"Generated at: {report.get('generated_at', 'N/A')}"
    )

    assets = report.get("assets", {})
    if not assets:
        st.warning("Staleness report contains no asset entries.")
        return

    rows = []
    for symbol, info in assets.items():
        rows.append(
            {
                "symbol": symbol,
                "tier": info.get("tier"),
                "enabled": info.get("trading_enabled"),
                "hours_since_last_trade": info.get("hours_since_last_trade"),
                "trades_1d": info.get("trades_1d"),
                "trades_3d": info.get("trades_3d"),
                "trades_7d": info.get("trades_7d"),
                "total_trades": info.get("total_trades"),
                "pf": info.get("pf"),
                "feed_state": info.get("feed_state"),
                "classification": info.get("classification"),
                "suggestion": info.get("suggestion"),
            }
        )

    if not rows:
        st.warning("No asset rows to display.")
        return

    df = pd.DataFrame(rows)

    with st.expander("Per-Asset Staleness Table", expanded=True):
        st.dataframe(
            df.sort_values(
                ["enabled", "tier", "symbol"],
                ascending=[False, True, True],
                na_position="last",
            ),
            use_container_width=True,
        )

    st.subheader("Suggestions")
    for symbol, info in assets.items():
        st.markdown(
            f"- **{symbol}** — {info.get('suggestion')} "
            f"({info.get('classification')}, feed={info.get('feed_state')})"
        )

