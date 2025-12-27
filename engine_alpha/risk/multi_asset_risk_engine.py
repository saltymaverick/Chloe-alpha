# engine_alpha/risk/multi_asset_risk_engine.py

"""
Multi-Asset Risk Engine

Computes portfolio-level risk metrics weighted by:
- Expected edge (bps)
- Volatility
- Trade frequency
- Position size
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, List
from dataclasses import dataclass

ROOT_DIR = Path(__file__).resolve().parents[3]
CONFIG_DIR = ROOT_DIR / "config"
REPORTS_DIR = ROOT_DIR / "reports"
RESEARCH_DIR = REPORTS_DIR / "research"

STRATEGY_PROFILER_PATH = CONFIG_DIR / "multi_asset_strategy_profiler.json"
PAPER_CONFIG_PATH = CONFIG_DIR / "multi_asset_paper_config.json"


@dataclass
class AssetRiskMetrics:
    """Risk metrics for a single asset."""
    symbol: str
    tier: str
    edge_bps: float
    regime: str
    enabled: bool
    mode: str
    max_notional_usd: float
    expected_trades_per_day: float
    volatility_multiplier: float
    risk_score: float


def _load_json(path: Path) -> Dict[str, Any]:
    """Safely load JSON file."""
    if not path.exists():
        return {}
    try:
        with path.open("r") as f:
            return json.load(f)
    except Exception:
        return {}


def _estimate_volatility_multiplier(symbol: str) -> float:
    """
    Estimate volatility multiplier based on asset class.
    Higher volatility = higher risk multiplier.
    """
    # Rough volatility estimates (can be refined with actual data)
    volatility_map = {
        "BTCUSDT": 1.0,   # Baseline
        "ETHUSDT": 1.1,
        "MATICUSDT": 1.3,
        "AVAXUSDT": 1.4,
        "SOLUSDT": 1.3,
        "DOGEUSDT": 1.5,  # High volatility
        "XRPUSDT": 1.2,
        "BNBUSDT": 1.1,
        "DOTUSDT": 1.2,
        "ADAUSDT": 1.2,
        "LINKUSDT": 1.2,
        "ATOMUSDT": 1.3,
    }
    return volatility_map.get(symbol, 1.0)


def _estimate_trade_frequency(symbol: str, regime: str, edge_bps: float) -> float:
    """
    Estimate expected trades per day based on:
    - Regime frequency
    - Edge strength
    - Asset liquidity
    """
    # Base frequencies (trades per day)
    base_freq = {
        "high_vol": 0.5,      # High-vol regimes are less frequent
        "trend_down": 0.3,
        "trend_up": 0.3,
        "chop": 0.8,           # Chop is more frequent
    }
    
    freq = base_freq.get(regime, 0.5)
    
    # Adjust by edge strength (higher edge = more selective = fewer trades)
    if edge_bps > 10:
        freq *= 0.7  # Very selective
    elif edge_bps > 5:
        freq *= 0.85
    elif edge_bps > 0:
        freq *= 1.0
    else:
        freq *= 0.5  # Negative edge = very selective
    
    return freq


def compute_asset_risk_metrics(
    symbol: str,
    profiler: Dict[str, Any],
    paper_config: Dict[str, Any]
) -> AssetRiskMetrics:
    """Compute risk metrics for a single asset."""
    
    # Get asset data
    tier1 = profiler.get("tier1_primary_alpha", {})
    tier2 = profiler.get("tier2_observation", {})
    tier3 = profiler.get("tier3_research_only", {})
    
    if symbol in tier1:
        data = tier1[symbol]
        tier = "Tier 1"
        edge_bps = data.get("edge_bps", 0.0)
        regime = data.get("regime", "unknown")
        sizing = data.get("position_sizing", {})
        max_notional = sizing.get("max_notional_usd", 500)
    elif symbol in tier2:
        data = tier2[symbol]
        tier = "Tier 2"
        edge_bps = data.get("edge_bps", 0.0)
        regime = data.get("regime", "unknown")
        sizing = data.get("position_sizing", {})
        max_notional = sizing.get("max_notional_usd", 250)
    elif symbol in tier3:
        data = tier3[symbol]
        tier = "Tier 3"
        edge_bps = data.get("overall_edge_bps", 0.0)
        regime = "selective_only"
        max_notional = 0.0  # Not trading
    else:
        return AssetRiskMetrics(
            symbol=symbol,
            tier="Unknown",
            edge_bps=0.0,
            regime="unknown",
            enabled=False,
            mode="unknown",
            max_notional_usd=0.0,
            expected_trades_per_day=0.0,
            volatility_multiplier=1.0,
            risk_score=0.0
        )
    
    # Get status
    status = _get_asset_status(symbol, paper_config)
    
    # Compute metrics
    volatility_mult = _estimate_volatility_multiplier(symbol)
    trade_freq = _estimate_trade_frequency(symbol, regime, edge_bps)
    
    # Risk score = edge × volatility × trade_freq × max_notional
    # Higher score = higher expected contribution to portfolio risk
    risk_score = abs(edge_bps) * volatility_mult * trade_freq * (max_notional / 1000.0)
    
    return AssetRiskMetrics(
        symbol=symbol,
        tier=tier,
        edge_bps=edge_bps,
        regime=regime,
        enabled=status.get("enabled", False),
        mode=status.get("mode", "unknown"),
        max_notional_usd=max_notional,
        expected_trades_per_day=trade_freq,
        volatility_multiplier=volatility_mult,
        risk_score=risk_score
    )


def _get_asset_status(symbol: str, paper_config: Dict[str, Any]) -> Dict[str, Any]:
    """Get asset activation status."""
    enabled = paper_config.get("enabled_assets", {})
    observation = paper_config.get("observation_assets", {})
    research = paper_config.get("research_only_assets", {})
    
    if symbol in enabled:
        return {
            "enabled": enabled[symbol].get("enabled", False),
            "mode": enabled[symbol].get("mode", "paper")
        }
    elif symbol in observation:
        return {
            "enabled": observation[symbol].get("enabled", False),
            "mode": observation[symbol].get("mode", "observation")
        }
    elif symbol in research:
        return {
            "enabled": False,
            "mode": "research_only"
        }
    
    return {"enabled": False, "mode": "unknown"}


def compute_portfolio_risk_summary() -> Dict[str, Any]:
    """
    Compute portfolio-level risk summary.
    
    Returns:
        Dictionary with portfolio risk metrics
    """
    profiler = _load_json(STRATEGY_PROFILER_PATH)
    paper_config = _load_json(PAPER_CONFIG_PATH)
    
    if not profiler:
        return {}
    
    all_assets = []
    
    # Collect all assets
    for symbol in profiler.get("tier1_primary_alpha", {}).keys():
        all_assets.append(symbol)
    for symbol in profiler.get("tier2_observation", {}).keys():
        all_assets.append(symbol)
    for symbol in profiler.get("tier3_research_only", {}).keys():
        all_assets.append(symbol)
    
    # Compute metrics for each asset
    asset_metrics = []
    for symbol in all_assets:
        metrics = compute_asset_risk_metrics(symbol, profiler, paper_config)
        asset_metrics.append(metrics)
    
    # Portfolio aggregates
    enabled_assets = [m for m in asset_metrics if m.enabled]
    
    total_expected_edge = sum(m.edge_bps for m in enabled_assets)
    total_max_notional = sum(m.max_notional_usd for m in enabled_assets)
    total_expected_trades_per_day = sum(m.expected_trades_per_day for m in enabled_assets)
    total_risk_score = sum(m.risk_score for m in enabled_assets)
    
    # Weighted average edge (by max_notional)
    if total_max_notional > 0:
        weighted_edge = sum(m.edge_bps * m.max_notional_usd for m in enabled_assets) / total_max_notional
    else:
        weighted_edge = 0.0
    
    return {
        "total_assets": len(all_assets),
        "enabled_assets": len(enabled_assets),
        "tier1_count": len([m for m in asset_metrics if m.tier == "Tier 1"]),
        "tier2_count": len([m for m in asset_metrics if m.tier == "Tier 2"]),
        "tier3_count": len([m for m in asset_metrics if m.tier == "Tier 3"]),
        "total_expected_edge_bps": total_expected_edge,
        "weighted_avg_edge_bps": weighted_edge,
        "total_max_notional_usd": total_max_notional,
        "total_expected_trades_per_day": total_expected_trades_per_day,
        "total_risk_score": total_risk_score,
        "per_asset_metrics": [
            {
                "symbol": m.symbol,
                "tier": m.tier,
                "edge_bps": m.edge_bps,
                "regime": m.regime,
                "enabled": m.enabled,
                "mode": m.mode,
                "max_notional_usd": m.max_notional_usd,
                "expected_trades_per_day": m.expected_trades_per_day,
                "volatility_multiplier": m.volatility_multiplier,
                "risk_score": m.risk_score
            }
            for m in asset_metrics
        ]
    }


if __name__ == "__main__":
    summary = compute_portfolio_risk_summary()
    print(json.dumps(summary, indent=2))


