# engine_alpha/dashboard/multi_asset_panel.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, List

import streamlit as st
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[3]
CONFIG_DIR = ROOT_DIR / "config"
REPORTS_DIR = ROOT_DIR / "reports"
RESEARCH_DIR = REPORTS_DIR / "research"

STRATEGY_PROFILER_PATH = CONFIG_DIR / "multi_asset_strategy_profiler.json"
PAPER_CONFIG_PATH = CONFIG_DIR / "multi_asset_paper_config.json"


def _load_json(path: Path) -> Dict[str, Any]:
    """Safely load JSON file, returning empty dict if missing or malformed."""
    if not path.exists():
        return {}
    try:
        with path.open("r") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _get_asset_tier(asset: str, profiler: Dict[str, Any]) -> str:
    """Determine asset tier from profiler."""
    if asset in profiler.get("tier1_primary_alpha", {}):
        return "Tier 1"
    elif asset in profiler.get("tier2_observation", {}):
        return "Tier 2"
    elif asset in profiler.get("tier3_research_only", {}):
        return "Tier 3"
    return "Unknown"


def _get_asset_edge(asset: str, profiler: Dict[str, Any]) -> float:
    """Get asset edge in bps."""
    tier1 = profiler.get("tier1_primary_alpha", {})
    tier2 = profiler.get("tier2_observation", {})
    
    if asset in tier1:
        return tier1[asset].get("edge_bps", 0.0)
    elif asset in tier2:
        return tier2[asset].get("edge_bps", 0.0)
    elif asset in profiler.get("tier3_research_only", {}):
        return profiler["tier3_research_only"][asset].get("overall_edge_bps", 0.0)
    return 0.0


def _get_asset_pf(asset: str) -> Dict[str, Any]:
    """Get per-asset PF stats."""
    pf_path = RESEARCH_DIR / asset / "pf_local.json"
    if pf_path.exists():
        return _load_json(pf_path)
    
    # Fallback to global PF if per-asset doesn't exist
    global_pf_path = REPORTS_DIR / "pf_local.json"
    pf_data = _load_json(global_pf_path)
    
    # Try to extract per-asset from trades.jsonl
    trades_path = REPORTS_DIR / "trades.jsonl"
    if trades_path.exists():
        try:
            asset_trades = []
            with trades_path.open("r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        trade = json.loads(line)
                        if trade.get("symbol", "").upper() == asset:
                            asset_trades.append(trade)
                    except Exception:
                        continue
            
            if asset_trades:
                wins = sum(1 for t in asset_trades if t.get("pct", 0) > 0 and not t.get("is_scratch", False))
                losses = sum(1 for t in asset_trades if t.get("pct", 0) < 0 and not t.get("is_scratch", False))
                total = wins + losses
                
                if total > 0:
                    return {
                        "pf": pf_data.get("pf", 1.0),
                        "wins": wins,
                        "losses": losses,
                        "total_trades": total
                    }
        except Exception:
            pass
    
    return pf_data


def _get_asset_status(asset: str, paper_config: Dict[str, Any]) -> Dict[str, Any]:
    """Get asset activation status."""
    enabled = paper_config.get("enabled_assets", {})
    observation = paper_config.get("observation_assets", {})
    research = paper_config.get("research_only_assets", {})
    
    if asset in enabled:
        return {
            "enabled": enabled[asset].get("enabled", False),
            "mode": enabled[asset].get("mode", "paper"),
            "priority": enabled[asset].get("priority", 999)
        }
    elif asset in observation:
        return {
            "enabled": observation[asset].get("enabled", False),
            "mode": observation[asset].get("mode", "observation"),
            "priority": observation[asset].get("priority", 999)
        }
    elif asset in research:
        return {
            "enabled": False,
            "mode": "research_only",
            "priority": None
        }
    
    return {"enabled": False, "mode": "unknown", "priority": None}


def render() -> None:
    """Render the multi-asset dashboard panel."""
    st.header("Multi-Asset Alpha Portfolio")
    
    profiler = _load_json(STRATEGY_PROFILER_PATH)
    paper_config = _load_json(PAPER_CONFIG_PATH)
    
    if not profiler:
        st.warning("Multi-asset strategy profiler not found. Run research first.")
        return
    
    # Build asset summary
    all_assets = []
    
    # Tier 1
    for asset, data in profiler.get("tier1_primary_alpha", {}).items():
        pf_data = _get_asset_pf(asset)
        status = _get_asset_status(asset, paper_config)
        all_assets.append({
            "asset": asset,
            "tier": "Tier 1",
            "edge_bps": data.get("edge_bps", 0.0),
            "regime": data.get("regime", "unknown"),
            "best_bucket": data.get("best_bucket", "N/A"),
            "pf": pf_data.get("pf", 0.0),
            "trades": pf_data.get("total_trades", 0),
            "enabled": status.get("enabled", False),
            "mode": status.get("mode", "unknown"),
            "priority": status.get("priority", 999)
        })
    
    # Tier 2
    for asset, data in profiler.get("tier2_observation", {}).items():
        pf_data = _get_asset_pf(asset)
        status = _get_asset_status(asset, paper_config)
        all_assets.append({
            "asset": asset,
            "tier": "Tier 2",
            "edge_bps": data.get("edge_bps", 0.0),
            "regime": data.get("regime", "unknown"),
            "best_bucket": data.get("best_bucket", "N/A"),
            "pf": pf_data.get("pf", 0.0),
            "trades": pf_data.get("total_trades", 0),
            "enabled": status.get("enabled", False),
            "mode": status.get("mode", "unknown"),
            "priority": status.get("priority", 999)
        })
    
    # Tier 3
    for asset, data in profiler.get("tier3_research_only", {}).items():
        pf_data = _get_asset_pf(asset)
        status = _get_asset_status(asset, paper_config)
        all_assets.append({
            "asset": asset,
            "tier": "Tier 3",
            "edge_bps": data.get("overall_edge_bps", 0.0),
            "regime": "selective_only",
            "best_bucket": "N/A",
            "pf": pf_data.get("pf", 0.0),
            "trades": pf_data.get("total_trades", 0),
            "enabled": False,
            "mode": "research_only",
            "priority": None
        })
    
    df = pd.DataFrame(all_assets)
    
    # Display by tier
    st.subheader("🥇 Tier 1 - Primary Alpha Engines")
    tier1_df = df[df["tier"] == "Tier 1"].sort_values("edge_bps", ascending=False)
    if not tier1_df.empty:
        st.dataframe(
            tier1_df[["asset", "edge_bps", "regime", "best_bucket", "pf", "trades", "enabled", "mode"]],
            use_container_width=True
        )
    else:
        st.info("No Tier 1 assets configured.")
    
    st.subheader("🥈 Tier 2 - Observation Mode")
    tier2_df = df[df["tier"] == "Tier 2"].sort_values("edge_bps", ascending=False)
    if not tier2_df.empty:
        st.dataframe(
            tier2_df[["asset", "edge_bps", "regime", "best_bucket", "pf", "trades", "enabled", "mode"]],
            use_container_width=True
        )
    else:
        st.info("No Tier 2 assets configured.")
    
    st.subheader("🥉 Tier 3 - Research-Only")
    tier3_df = df[df["tier"] == "Tier 3"].sort_values("edge_bps", ascending=True)
    if not tier3_df.empty:
        st.dataframe(
            tier3_df[["asset", "edge_bps", "regime", "pf", "trades"]],
            use_container_width=True
        )
    else:
        st.info("No Tier 3 assets configured.")
    
    # Summary stats
    st.subheader("Portfolio Summary")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Tier 1 Assets", len(tier1_df))
    with col2:
        st.metric("Tier 2 Assets", len(tier2_df))
    with col3:
        st.metric("Tier 3 Assets", len(tier3_df))
    with col4:
        enabled_count = len(df[df["enabled"] == True])
        st.metric("Enabled Assets", enabled_count)
    
    # Rollout plan
    st.subheader("🚀 Phase 2 Rollout Plan")
    rollout = profiler.get("rollout_plan", {})
    
    if "phase_2_1_immediate" in rollout:
        st.write("**Phase 2.1 - Immediate (Paper Trading):**")
        for asset in rollout["phase_2_1_immediate"].get("assets", []):
            status = _get_asset_status(asset, paper_config)
            enabled_icon = "✅" if status.get("enabled") else "⏸️"
            st.write(f"  {enabled_icon} {asset} - {status.get('mode', 'unknown')} mode")
    
    if "phase_2_2_observation" in rollout:
        st.write("**Phase 2.2 - Observation Mode:**")
        for asset in rollout["phase_2_2_observation"].get("assets", []):
            status = _get_asset_status(asset, paper_config)
            enabled_icon = "✅" if status.get("enabled") else "⏸️"
            st.write(f"  {enabled_icon} {asset} - {status.get('mode', 'unknown')} mode")


