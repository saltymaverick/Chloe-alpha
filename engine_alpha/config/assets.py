# engine_alpha/config/assets.py

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
import json

ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"
ASSET_REGISTRY_PATH = CONFIG_DIR / "asset_registry.json"


@dataclass
class AssetConfig:
    symbol: str
    base_timeframe: str
    enabled: bool
    venue: str
    risk_bucket: str
    quote_ccy: str
    max_leverage: float
    min_notional_usd: float


def _load_registry() -> Dict[str, Dict]:
    if not ASSET_REGISTRY_PATH.exists():
        raise FileNotFoundError(f"asset_registry.json not found at {ASSET_REGISTRY_PATH}")
    with ASSET_REGISTRY_PATH.open("r") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("asset_registry.json must be a JSON object mapping symbol -> config")
    return data


def load_all_assets() -> List[AssetConfig]:
    """Load all assets from registry (enabled and disabled)."""
    raw = _load_registry()
    assets: List[AssetConfig] = []
    
    for symbol, cfg in raw.items():
        assets.append(
            AssetConfig(
                symbol=cfg.get("symbol", symbol),
                base_timeframe=cfg.get("base_timeframe", "15m"),
                enabled=bool(cfg.get("enabled", False)),
                venue=cfg.get("venue", "bybit"),
                risk_bucket=cfg.get("risk_bucket", "core"),
                quote_ccy=cfg.get("quote_ccy", "USDT"),
                max_leverage=float(cfg.get("max_leverage", 1.0)),
                min_notional_usd=float(cfg.get("min_notional_usd", 0.0)),
            )
        )
    
    return assets


def get_asset(symbol: str) -> Optional[AssetConfig]:
    """Get AssetConfig for a specific symbol, or None if not found."""
    for a in load_all_assets():
        if a.symbol == symbol:
            return a
    return None


def get_enabled_assets() -> List[AssetConfig]:
    """Return only enabled assets from registry."""
    return [a for a in load_all_assets() if a.enabled]


