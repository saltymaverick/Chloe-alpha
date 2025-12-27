"""
Config Loader - Safe wallet key loading from environment variables

Never stores real API keys in files. Loads from environment variables only.
"""

from __future__ import annotations

import os
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Any

CONFIG_DIR = Path(__file__).resolve().parent
WALLET_DIR = CONFIG_DIR / "wallets"


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r") as f:
        return json.load(f)


@dataclass
class WalletConfig:
    active_wallet_mode: str          # "paper" or "real"
    paper_exchange: str
    real_exchange: str
    confirm_live_trade: bool
    max_live_notional_per_trade_usd: float
    max_live_daily_notional_usd: float


def load_wallet_config() -> WalletConfig:
    """
    Load wallet configuration (which wallet to use, mode, etc.).
    
    Returns WalletConfig dataclass with all wallet settings.
    """
    cfg = _load_json(WALLET_DIR / "wallet_config.json")
    return WalletConfig(
        active_wallet_mode=cfg.get("active_wallet_mode", "paper"),
        paper_exchange=cfg.get("paper_exchange", "paper"),
        real_exchange=cfg.get("real_exchange", "bybit"),
        confirm_live_trade=bool(cfg.get("confirm_live_trade", True)),
        max_live_notional_per_trade_usd=float(cfg.get("max_live_notional_per_trade_usd", 500.0)),
        max_live_daily_notional_usd=float(cfg.get("max_live_daily_notional_usd", 5000.0)),
    )


def save_wallet_config(config: WalletConfig) -> None:
    """Save wallet configuration to file."""
    config_path = WALLET_DIR / "wallet_config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(asdict(config), indent=2))


def load_real_exchange_keys() -> Dict[str, Dict[str, str]]:
    """
    Merge template with environment variables.
    
    Env names:
      BYBIT_API_KEY / BYBIT_API_SECRET
      BINANCE_API_KEY / BINANCE_API_SECRET
      OKX_API_KEY / OKX_API_SECRET / OKX_PASSPHRASE
    """
    template = _load_json(WALLET_DIR / "real_exchange_keys.json")
    
    for venue, info in template.items():
        u = venue.upper()
        info["api_key"] = os.getenv(f"{u}_API_KEY", "")
        info["api_secret"] = os.getenv(f"{u}_API_SECRET", "")
        if "passphrase" in info:
            info["passphrase"] = os.getenv(f"{u}_PASSPHRASE", "")
    
    return template


def load_real_onchain_keys() -> Dict[str, Dict[str, str]]:
    """Load onchain keys (remains env-free for now; you can later env-ify private keys too)."""
    return _load_json(WALLET_DIR / "real_onchain_keys.json")


def is_live_mode() -> bool:
    """Check if wallet is in live mode."""
    config = load_wallet_config()
    return config.active_wallet_mode == "real"


def requires_confirmation() -> bool:
    """Check if live trades require manual confirmation."""
    config = load_wallet_config()
    return config.confirm_live_trade and is_live_mode()

