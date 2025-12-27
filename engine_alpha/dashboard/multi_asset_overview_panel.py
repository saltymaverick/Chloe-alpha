"""
Multi-Asset Overview Panel — PM-style at-a-glance view of all 12 assets
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Any
import pandas as pd
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"
OHLVC_DIR = DATA_DIR / "ohlcv"
REPORTS_DIR = ROOT_DIR / "reports"
RESEARCH_ROOT = REPORTS_DIR / "research"
TRADES_PATH = REPORTS_DIR / "trades.jsonl"
PF_LOCAL_PATH = REPORTS_DIR / "pf_local.json"

# Hardcoded tier mapping (from docs/multi_asset_rollout_plan.md)
TIERS = {
    "tier_1": ["MATICUSDT", "BTCUSDT", "AVAXUSDT", "DOGEUSDT"],
    "tier_2": ["XRPUSDT", "SOLUSDT", "ETHUSDT"],
    "tier_3": ["BNBUSDT", "DOTUSDT", "ADAUSDT", "LINKUSDT", "ATOMUSDT"],
}


def _load_json(path: Path) -> dict:
    """Safely load JSON file."""
    if not path.exists():
        return {}
    try:
        with path.open("r") as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return {}


def _get_tier(symbol: str) -> int:
    """Get tier number (1, 2, or 3) for a symbol."""
    symbol_upper = symbol.upper()
    if symbol_upper in TIERS["tier_1"]:
        return 1
    elif symbol_upper in TIERS["tier_2"]:
        return 2
    elif symbol_upper in TIERS["tier_3"]:
        return 3
    return 3  # Default to tier 3 if not found


def _count_live_rows(symbol: str, timeframe: str) -> int:
    """Count rows in live OHLCV CSV."""
    live_path = OHLVC_DIR / f"{symbol.lower()}_{timeframe.lower()}_live.csv"
    if not live_path.exists():
        return 0
    try:
        # Quick row count (minus header)
        with live_path.open("r") as f:
            return max(sum(1 for _ in f) - 1, 0)
    except Exception:
        return 0


def _has_hybrid_dataset(symbol: str) -> bool:
    """Check if hybrid dataset exists."""
    hybrid_path = RESEARCH_ROOT / symbol / "hybrid_research_dataset.parquet"
    return hybrid_path.exists()


def _has_stats(symbol: str) -> bool:
    """Check if multi_horizon_stats.json exists and is non-empty."""
    stats_path = RESEARCH_ROOT / symbol / "multi_horizon_stats.json"
    if not stats_path.exists():
        return False
    try:
        data = _load_json(stats_path)
        return bool(data)  # Non-empty dict
    except Exception:
        return False


def _compute_pf_and_trades(symbol: str) -> tuple[Optional[float], int]:
    """
    Compute PF and trade count for a symbol from trades.jsonl.
    Returns: (pf_value or None, trade_count)
    """
    if not TRADES_PATH.exists():
        return None, 0
    
    symbol_upper = symbol.upper()
    wins_sum = 0.0
    losses_sum = 0.0
    trade_count = 0
    
    try:
        with TRADES_PATH.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trade = json.loads(line)
                    # Filter by symbol (fallback to ETHUSDT if missing)
                    trade_symbol = trade.get("symbol", "ETHUSDT").upper()
                    if trade_symbol != symbol_upper:
                        continue
                    
                    # Only count close events
                    if trade.get("type") != "close":
                        continue
                    
                    # Skip scratch trades
                    if trade.get("is_scratch", False):
                        continue
                    
                    pct = float(trade.get("pct", 0.0))
                    if pct > 0:
                        wins_sum += pct
                        trade_count += 1
                    elif pct < 0:
                        losses_sum += abs(pct)
                        trade_count += 1
                except (json.JSONDecodeError, ValueError, KeyError):
                    continue
    except Exception:
        return None, 0
    
    # Compute PF
    if losses_sum > 0:
        pf = wins_sum / losses_sum
    elif wins_sum > 0:
        pf = float("inf")
    else:
        pf = None
    
    return pf, trade_count


def _get_status_label(tier: int, trading_enabled: bool) -> str:
    """Get status label for display."""
    if trading_enabled:
        if tier == 1:
            return "🟢 Paper (Tier 1)"
        elif tier == 2:
            return "🟡 Observation (Tier 2)"
        else:
            return "Paper (Tier 3)"
    else:
        if tier == 1 or tier == 2:
            return f"Not Trading (Tier {tier})"
        else:
            return "🔴 Research-only"


def _build_asset_data() -> List[Dict[str, Any]]:
    """Build data for all assets."""
    # Load configs
    asset_registry = _load_json(CONFIG_DIR / "asset_registry.json")
    trading_enablement = _load_json(CONFIG_DIR / "trading_enablement.json")
    
    enabled_symbols = set(
        s.upper() for s in trading_enablement.get("enabled_for_trading", [])
    )
    phase = trading_enablement.get("phase", "phase_0")
    
    assets_data = []
    
    for symbol_key, asset_info in asset_registry.items():
        symbol = asset_info.get("symbol", symbol_key).upper()
        timeframe = asset_info.get("base_timeframe", "1h")
        enabled = asset_info.get("enabled", False)
        
        if not enabled:
            continue  # Skip disabled assets
        
        tier = _get_tier(symbol)
        trading_enabled = symbol in enabled_symbols
        
        # Compute metrics
        live_rows = _count_live_rows(symbol, timeframe)
        has_hybrid = _has_hybrid_dataset(symbol)
        has_stats = _has_stats(symbol)
        pf, trade_count = _compute_pf_and_trades(symbol)
        
        status = _get_status_label(tier, trading_enabled)
        
        assets_data.append({
            "symbol": symbol,
            "tier": tier,
            "phase": phase,
            "trading_enabled": trading_enabled,
            "pf": pf,
            "trades": trade_count,
            "live_rows": live_rows,
            "has_hybrid": has_hybrid,
            "has_stats": has_stats,
            "status": status,
        })
    
    return assets_data


def render():
    """Render the Multi-Asset Overview panel."""
    st.title("Multi-Asset Overview")
    
    # Load trading enablement for header info
    trading_enablement = _load_json(CONFIG_DIR / "trading_enablement.json")
    phase = trading_enablement.get("phase", "phase_0")
    enabled_symbols = trading_enablement.get("enabled_for_trading", [])
    
    # Header metrics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Current Phase", phase.replace("_", " ").title())
    with col2:
        st.metric("Trading Enabled", len(enabled_symbols))
    with col3:
        st.metric("Total Assets", 12)
    
    # Phase description
    phase_notes = trading_enablement.get("notes", "")
    if phase_notes:
        st.info(phase_notes)
    
    st.divider()
    
    # Build and display table
    assets_data = _build_asset_data()
    
    if not assets_data:
        st.warning("No assets found in registry.")
        return
    
    # Convert to DataFrame
    df = pd.DataFrame(assets_data)
    
    # Format PF column
    def format_pf(pf_val):
        if pf_val is None:
            return "—"
        elif pf_val == float("inf"):
            return "∞"
        else:
            return f"{pf_val:.2f}"
    
    df["pf_display"] = df["pf"].apply(format_pf)
    
    # Reorder columns for display
    display_cols = [
        "symbol",
        "tier",
        "status",
        "trading_enabled",
        "pf_display",
        "trades",
        "live_rows",
        "has_hybrid",
        "has_stats",
    ]
    
    df_display = df[display_cols].copy()
    df_display.columns = [
        "Symbol",
        "Tier",
        "Status",
        "Trading Enabled",
        "PF",
        "Trades",
        "Live Rows",
        "Has Hybrid",
        "Has Stats",
    ]
    
    # Sort: tier ascending, trading_enabled (True first), pf descending
    df_display = df_display.sort_values(
        by=["Tier", "Trading Enabled", "PF"],
        ascending=[True, False, False],
        na_position="last",
    )
    
    # Display table
    st.dataframe(
        df_display,
        use_container_width=True,
        hide_index=True,
    )
    
    # Legend
    st.caption(
        "🟢 Tier 1 (Primary Alpha) | 🟡 Tier 2 (Observation) | 🔴 Tier 3 (Research-only)"
    )


