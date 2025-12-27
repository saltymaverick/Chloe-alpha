"""
Wallet Operator - CLI commands for wallet management

Text command parser for wallet operations.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any

from engine_alpha.config.config_loader import (
    load_wallet_config,
    save_wallet_config,
    WALLET_DIR,
)


def wallet_status() -> Dict[str, Any]:
    """
    Get current wallet status.
    
    Returns dict with wallet configuration and runtime checks.
    """
    cfg = load_wallet_config()
    
    # Convert dataclass to dict
    status = {
        "active_wallet_mode": cfg.active_wallet_mode,
        "paper_exchange": cfg.paper_exchange,
        "real_exchange": cfg.real_exchange,
        "confirm_live_trade": cfg.confirm_live_trade,
        "max_live_notional_per_trade_usd": cfg.max_live_notional_per_trade_usd,
        "max_live_daily_notional_usd": cfg.max_live_daily_notional_usd,
    }
    
    # Add runtime checks (keys present, etc.)
    from engine_alpha.config.config_loader import load_real_exchange_keys
    keys = load_real_exchange_keys()
    
    status["keys_configured"] = {}
    for venue, creds in keys.items():
        status["keys_configured"][venue] = {
            "has_api_key": bool(creds.get("api_key")),
            "has_api_secret": bool(creds.get("api_secret")),
        }
    
    return status


def wallet_set_mode(mode: str) -> Dict[str, Any]:
    """
    Set wallet mode.
    
    Args:
        mode: "paper" or "real"
    
    Returns:
        Updated wallet config dict
    """
    mode = mode.lower()
    if mode not in ("paper", "real"):
        raise ValueError("mode must be 'paper' or 'real'")
    
    cfg = load_wallet_config()
    
    # Create new config with updated mode
    from engine_alpha.config.config_loader import WalletConfig
    new_cfg = WalletConfig(
        active_wallet_mode=mode,
        paper_exchange=cfg.paper_exchange,
        real_exchange=cfg.real_exchange,
        confirm_live_trade=cfg.confirm_live_trade,
        max_live_notional_per_trade_usd=cfg.max_live_notional_per_trade_usd,
        max_live_daily_notional_usd=cfg.max_live_daily_notional_usd,
    )
    
    save_wallet_config(new_cfg)
    
    return {
        "active_wallet_mode": new_cfg.active_wallet_mode,
        "paper_exchange": new_cfg.paper_exchange,
        "real_exchange": new_cfg.real_exchange,
        "confirm_live_trade": new_cfg.confirm_live_trade,
        "max_live_notional_per_trade_usd": new_cfg.max_live_notional_per_trade_usd,
        "max_live_daily_notional_usd": new_cfg.max_live_daily_notional_usd,
    }


def wallet_set_confirm_live(confirm: bool) -> Dict[str, Any]:
    """
    Set confirm_live_trade flag.
    
    Args:
        confirm: True to require confirmation, False to disable
    
    Returns:
        Updated wallet config dict
    """
    cfg = load_wallet_config()
    
    from engine_alpha.config.config_loader import WalletConfig
    new_cfg = WalletConfig(
        active_wallet_mode=cfg.active_wallet_mode,
        paper_exchange=cfg.paper_exchange,
        real_exchange=cfg.real_exchange,
        confirm_live_trade=bool(confirm),
        max_live_notional_per_trade_usd=cfg.max_live_notional_per_trade_usd,
        max_live_daily_notional_usd=cfg.max_live_daily_notional_usd,
    )
    
    save_wallet_config(new_cfg)
    
    return {
        "active_wallet_mode": new_cfg.active_wallet_mode,
        "paper_exchange": new_cfg.paper_exchange,
        "real_exchange": new_cfg.real_exchange,
        "confirm_live_trade": new_cfg.confirm_live_trade,
        "max_live_notional_per_trade_usd": new_cfg.max_live_notional_per_trade_usd,
        "max_live_daily_notional_usd": new_cfg.max_live_daily_notional_usd,
    }


def handle_wallet_command(text: str) -> str:
    """
    Very simple text command parser.
    
    Commands:
      'wallet status'
      'wallet set paper'
      'wallet set real'
      'wallet confirm on'
      'wallet confirm off'
    
    Args:
        text: Command text
    
    Returns:
        Response string
    """
    parts = text.strip().lower().split()
    if not parts or parts[0] != "wallet":
        return "Not a wallet command."
    
    if len(parts) == 2 and parts[1] == "status":
        status = wallet_status()
        return "Wallet status:\n" + json.dumps(status, indent=2)
    
    if len(parts) == 3 and parts[1] == "set":
        mode = parts[2]
        try:
            cfg = wallet_set_mode(mode)
            return f"Set wallet mode to {mode}.\nNew config:\n" + json.dumps(cfg, indent=2)
        except ValueError as e:
            return f"Error: {e}"
    
    if len(parts) == 3 and parts[1] == "confirm":
        val = parts[2]
        confirm = val in ("on", "true", "yes", "1")
        cfg = wallet_set_confirm_live(confirm)
        return f"Set confirm_live_trade to {confirm}.\nNew config:\n" + json.dumps(cfg, indent=2)
    
    return "Unknown wallet command. Try: 'wallet status', 'wallet set paper/real', 'wallet confirm on/off'"


