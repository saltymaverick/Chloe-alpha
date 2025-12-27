"""
Streamlit panel for viewing scorecards.
"""

from __future__ import annotations

from pathlib import Path
import json
import pandas as pd
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[2]
SCORECARD_DIR = ROOT_DIR / "reports" / "scorecards"


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = path.read_text().strip()
        if not data:
            return {}
        return json.loads(data)
    except Exception:
        return {}


def _format_pf(row) -> str:
    pf_val = row.get("pf")
    wins = row.get("wins", 0)
    losses = row.get("losses", 0)
    if pf_val is None:
        if wins > 0 and losses == 0:
            return "∞"
        return "—"
    return f"{pf_val:.2f}"


def render() -> None:
    st.title("Performance Scorecards")
    st.caption("Realized performance per asset and per strategy (paper/live trades).")

    asset_path = SCORECARD_DIR / "asset_scorecards.json"
    strat_path = SCORECARD_DIR / "strategy_scorecards.json"

    assets = _load_json(asset_path)
    strategies = _load_json(strat_path)

    if not assets or not assets.get("assets"):
        st.warning("Scorecards not built yet. Run `python3 -m tools.scorecards` after some trades.")
        return

    st.subheader("Asset Scorecards")
    asset_rows = assets.get("assets", [])
    if asset_rows:
        asset_df = pd.DataFrame(asset_rows)
        asset_df["pf_display"] = asset_df.apply(_format_pf, axis=1)
        display_cols = [
            "symbol",
            "total_trades",
            "pf_display",
            "wins",
            "losses",
            "max_drawdown",
            "most_used_regime",
            "most_used_strategy",
        ]
        renamed = {
            "symbol": "Symbol",
            "total_trades": "Trades",
            "pf_display": "PF",
            "wins": "Wins",
            "losses": "Losses",
            "max_drawdown": "Max DD (fractional)",
            "most_used_regime": "Top Regime",
            "most_used_strategy": "Top Strategy",
        }
        asset_display = asset_df[display_cols].rename(columns=renamed)
        asset_display = asset_display.sort_values(by=["Trades", "PF"], ascending=[False, False])
        st.dataframe(asset_display, use_container_width=True, hide_index=True)
    else:
        st.info("No asset scorecard data available yet.")

    st.subheader("Strategy Scorecards (Per Symbol)")
    per_symbol = strategies.get("per_symbol") if strategies else None
    if per_symbol:
        strat_df = pd.DataFrame(per_symbol)
        strat_df["pf_display"] = strat_df.apply(_format_pf, axis=1)
        display_cols = [
            "strategy",
            "symbol",
            "total_trades",
            "pf_display",
            "wins",
            "losses",
        ]
        renamed = {
            "strategy": "Strategy",
            "symbol": "Symbol",
            "total_trades": "Trades",
            "pf_display": "PF",
            "wins": "Wins",
            "losses": "Losses",
        }
        strat_display = strat_df[display_cols].rename(columns=renamed)
        strat_display = strat_display.sort_values(by=["Trades", "PF"], ascending=[False, False])
        st.dataframe(strat_display, use_container_width=True, hide_index=True)
    else:
        st.info("No per-strategy scorecard data yet.")

    st.caption("Tip: run `python3 -m tools.scorecards` nightly to refresh these tables.")

