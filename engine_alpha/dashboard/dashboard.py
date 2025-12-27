"""
Chloe Alpha Quant Dashboard — Main Entry

Run with: streamlit run engine_alpha/dashboard/dashboard.py
"""

from __future__ import annotations

import streamlit as st

from engine_alpha.dashboard import (
    activity_meta_panel,
    activity_reflection_panel,
    coin_explainer_panel,
    eth_trades_panel,
    home_panel,
    live_panel,
    matic_decisions_panel,
    market_state_panel,
    meta_strategy_panel,
    multi_asset_overview_panel,
    operator_panel,
    opportunist_panel,
    overseer_panel,
    quant_panel,
    redflag_panel,
    research_panel,
    risk_panel,
    scorecards_panel,
    signals_heatmap_panel,
    staleness_panel,
    swarm_panel,
    system_panel,
    thresholds_confidence_panel,
    wallet_panel,
)


def main():
    st.set_page_config(
        page_title="Chloe Alpha Dashboard",
        layout="wide",
    )
    
    st.sidebar.title("Chloe Alpha")
    
    panel = st.sidebar.radio(
        "Panels",
        (
            "Home",
            "Live",
            "Research",
            "SWARM",
            "Risk",
            "Wallet",
            "Quant View",
            "Signals Heatmap",
            "Meta Strategy",
            "Multi-Asset Overview",
            "Chloe Coin Explainer",
            "ETH Trades",
            "MATIC Decisions",
            "Staleness & Activity",
            "Activity Reflection",
            "Meta Activity Reflection",
            "Market State Summary",
            "Thresholds & Confidence",
            "Scorecards",
            "SWARM Red Flags",
            "Overseer Quant",
            "Opportunist Scanner",
            "Operator",
            "System",
        ),
    )
    
    if panel == "Home":
        home_panel.render()
    elif panel == "Live":
        live_panel.render()
    elif panel == "Research":
        research_panel.render()
    elif panel == "SWARM":
        swarm_panel.render()
    elif panel == "Risk":
        risk_panel.render()
    elif panel == "Wallet":
        wallet_panel.render()
    elif panel == "Quant View":
        quant_panel.render()
    elif panel == "Signals Heatmap":
        signals_heatmap_panel.render()
    elif panel == "Meta Strategy":
        meta_strategy_panel.render()
    elif panel == "Multi-Asset Overview":
        multi_asset_overview_panel.render()
    elif panel == "Chloe Coin Explainer":
        coin_explainer_panel.render()
    elif panel == "ETH Trades":
        eth_trades_panel.render()
    elif panel == "MATIC Decisions":
        matic_decisions_panel.render()
    elif panel == "Staleness & Activity":
        staleness_panel.render()
    elif panel == "Activity Reflection":
        activity_reflection_panel.render()
    elif panel == "Meta Activity Reflection":
        activity_meta_panel.render()
    elif panel == "Market State Summary":
        market_state_panel.render()
    elif panel == "Thresholds & Confidence":
        thresholds_confidence_panel.render()
    elif panel == "Scorecards":
        scorecards_panel.render()
    elif panel == "SWARM Red Flags":
        redflag_panel.render()
    elif panel == "Overseer Quant":
        overseer_panel.render()
    elif panel == "Opportunist Scanner":
        opportunist_panel.render()
    elif panel == "Operator":
        operator_panel.render()
    elif panel == "System":
        system_panel.render()


if __name__ == "__main__":
    main()
