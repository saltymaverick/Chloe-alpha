"""
Chloe Coin Explainer — friendly descriptions per asset.
"""

from __future__ import annotations

import streamlit as st
import pandas as pd
from pathlib import Path
import json

ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"

TIERS = {
    "tier_1": ["MATICUSDT", "BTCUSDT", "AVAXUSDT", "DOGEUSDT"],
    "tier_2": ["XRPUSDT", "SOLUSDT", "ETHUSDT"],
    "tier_3": ["BNBUSDT", "DOTUSDT", "ADAUSDT", "LINKUSDT", "ATOMUSDT"],
}

IDENTITY_MAP = {
    "BTCUSDT": "High-volatility breakout engine. Chloe trades BTC when the market is moving strongly.",
    "MATICUSDT": "Strong breakout coin. Chloe waits for decisive, high-confidence moves.",
    "AVAXUSDT": "Short-bias engine. Chloe likes AVAX when downtrends accelerate.",
    "DOGEUSDT": "Explosive meme coin. Chloe only touches DOGE during huge volatility.",
    "SOLUSDT": "Selective breakout coin. Needs a very specific signal to act.",
    "ETHUSDT": "Benchmark learner. ETH is Chloe's training ground in paper mode.",
    "XRPUSDT": "Occasional fast mover. Mostly under observation for now.",
    "BNBUSDT": "Research asset. Chloe studies it but does not trade it yet.",
    "DOTUSDT": "Experimental research asset for future strategies.",
    "ADAUSDT": "High-risk asset. Chloe keeps it research-only for now.",
    "LINKUSDT": "Selective, research-focused asset. No trades yet.",
    "ATOMUSDT": "Experimental research asset. Watching only.",
}


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


def _get_tier(symbol: str) -> int:
    symbol = symbol.upper()
    if symbol in TIERS["tier_1"]:
        return 1
    if symbol in TIERS["tier_2"]:
        return 2
    return 3


def render() -> None:
    st.title("Chloe Coin Explainer")
    st.caption("Friendly descriptions of what each coin means to Chloe.")

    asset_registry = _load_json(CONFIG_DIR / "asset_registry.json")
    enablement = _load_json(CONFIG_DIR / "trading_enablement.json")

    trading_enabled = {s.upper() for s in enablement.get("enabled_for_trading", [])}
    phase = enablement.get("phase", "phase_0")

    st.info(
        f"Current rollout phase: **{phase.replace('_', ' ').title()}**. "
        "Coins marked as trading are active in paper-only mode."
    )

    rows = []
    for symbol, info in asset_registry.items():
        sym = info.get("symbol", symbol).upper()
        tier = _get_tier(sym)
        view = IDENTITY_MAP.get(sym, "Learning mode asset.")
        rows.append(
            {
                "Symbol": sym,
                "Tier": tier,
                "Chloe's View": view,
                "Trading now?": sym in trading_enabled,
            }
        )

    if not rows:
        st.warning("No assets found in registry.")
        return

    df = pd.DataFrame(rows)
    df = df.sort_values(by=["Tier", "Symbol"])

    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption("Tier guide — 1: Primary alpha, 2: Observation, 3: Research-only.")

