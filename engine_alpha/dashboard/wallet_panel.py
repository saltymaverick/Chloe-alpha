"""
Wallet Panel — Wallet mode, credentials, safety settings
"""

from __future__ import annotations

from pathlib import Path
import json
import streamlit as st
import pandas as pd

from engine_alpha.config.config_loader import load_wallet_config, load_real_exchange_keys

ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"
WALLET_DIR = CONFIG_DIR / "wallets"


def render():
    st.title("Wallet & Exchange")
    
    cfg = load_wallet_config()
    
    st.subheader("Wallet Mode")
    st.write(f"**Active wallet mode:** `{cfg.active_wallet_mode}`")
    st.write(f"**Paper exchange:** `{cfg.paper_exchange}`")
    st.write(f"**Real exchange:** `{cfg.real_exchange}`")
    st.write(f"**Confirm live trades:** `{cfg.confirm_live_trade}`")
    st.write(f"**Max live notional / trade (USD):** {cfg.max_live_notional_per_trade_usd}")
    st.write(f"**Max live daily notional (USD):** {cfg.max_live_daily_notional_usd}")
    
    st.subheader("Real Exchange Credentials")
    keys = load_real_exchange_keys()
    rows = []
    for venue, info in keys.items():
        rows.append(
            {
                "venue": venue,
                "has_api_key": bool(info.get("api_key")),
                "has_api_secret": bool(info.get("api_secret")),
            }
        )
    
    if rows:
        st.table(pd.DataFrame(rows))
    else:
        st.info("No real_exchange_keys.json template loaded or empty.")
    
    st.caption(
        "Note: Keys are expected via environment variables; dashboard only checks presence."
    )

