#!/usr/bin/env python3
"""
Wallet CLI - Operator commands for wallet management

Usage:
  python3 -m tools.wallet_cli status
  python3 -m tools.wallet_cli set paper
  python3 -m tools.wallet_cli set live
  python3 -m tools.wallet_cli confirm on
  python3 -m tools.wallet_cli confirm off
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from engine_alpha.config.config_loader import (
    load_wallet_config,
    save_wallet_config,
    load_real_exchange_keys,
    is_live_mode,
    requires_confirmation,
    WalletConfig,
)


def cmd_status() -> None:
    """Show wallet status."""
    config = load_wallet_config()
    keys = load_real_exchange_keys()
    
    print("=" * 60)
    print("WALLET STATUS")
    print("=" * 60)
    
    mode = config.active_wallet_mode
    exchange = config.real_exchange if mode == "real" else config.paper_exchange
    real_exchange = config.real_exchange
    confirm = config.confirm_live_trade
    
    print(f"Active Mode: {mode.upper()}")
    print(f"Active Exchange: {exchange}")
    print(f"Real Exchange: {real_exchange}")
    print(f"Confirm Live Trades: {confirm}")
    print(f"Max Notional Per Trade: ${config.max_live_notional_per_trade_usd:.2f}")
    print(f"Max Daily Notional: ${config.max_live_daily_notional_usd:.2f}")
    
    print("\n" + "-" * 60)
    print("API Keys Status:")
    print("-" * 60)
    
    for venue, creds in keys.items():
        api_key = creds.get("api_key", "")
        api_secret = creds.get("api_secret", "")
        has_key = bool(api_key and len(api_key) > 0)
        has_secret = bool(api_secret and len(api_secret) > 0)
        status = "✅ Configured" if (has_key and has_secret) else "❌ Missing"
        print(f"  {venue.upper():<10} {status}")
        if has_key:
            print(f"    Key: {api_key[:8]}...{api_key[-4:]}")
    
    print("\n" + "-" * 60)
    if mode == "real":
        if requires_confirmation():
            print("⚠️  LIVE MODE: Manual confirmation required for trades")
        else:
            print("🚨 LIVE MODE: Trades will execute automatically")
    else:
        print("✅ PAPER MODE: Safe for testing")
    print("=" * 60)


def cmd_set(mode: str) -> None:
    """Set wallet mode (paper or live)."""
    if mode not in ("paper", "live", "real"):
        print(f"❌ Invalid mode: {mode}")
        print("   Valid modes: paper, live, real")
        sys.exit(1)
    
    if mode == "live":
        mode = "real"  # Normalize
    
    config = load_wallet_config()
    old_mode = config.active_wallet_mode
    
    if mode == "real":
        # Verify keys are configured
        keys = load_real_exchange_keys()
        real_exchange = config.real_exchange
        creds = keys.get(real_exchange, {})
        
        if not creds.get("api_key") or not creds.get("api_secret"):
            print(f"❌ Cannot switch to LIVE mode: Missing API keys for {real_exchange}")
            print("   Set environment variables:")
            print(f"   export {real_exchange.upper()}_API_KEY=...")
            print(f"   export {real_exchange.upper()}_API_SECRET=...")
            sys.exit(1)
        
        print(f"⚠️  Switching to LIVE mode (exchange: {real_exchange})")
        print("   Make sure you've tested thoroughly in PAPER mode!")
        response = input("   Continue? (yes/no): ")
        if response.lower() != "yes":
            print("   Cancelled.")
            sys.exit(0)
    
    # Create new config with updated mode
    new_config = WalletConfig(
        active_wallet_mode=mode,
        paper_exchange=config.paper_exchange,
        real_exchange=config.real_exchange,
        confirm_live_trade=config.confirm_live_trade,
        max_live_notional_per_trade_usd=config.max_live_notional_per_trade_usd,
        max_live_daily_notional_usd=config.max_live_daily_notional_usd,
    )
    
    save_wallet_config(new_config)
    
    print(f"✅ Wallet mode set to: {mode.upper()}")
    if mode == "real":
        print("⚠️  LIVE MODE ACTIVE - Trades will execute on real exchange")
        if new_config.confirm_live_trade:
            print("   Note: confirm_live_trade=true, so trades will be blocked until confirmation is disabled")


def cmd_confirm(enable: bool) -> None:
    """Enable/disable manual confirmation for live trades."""
    config = load_wallet_config()
    
    if not is_live_mode():
        print("⚠️  Not in live mode. Confirmation setting only applies in live mode.")
        return
    
    # Create new config with updated confirmation flag
    new_config = WalletConfig(
        active_wallet_mode=config.active_wallet_mode,
        paper_exchange=config.paper_exchange,
        real_exchange=config.real_exchange,
        confirm_live_trade=enable,
        max_live_notional_per_trade_usd=config.max_live_notional_per_trade_usd,
        max_live_daily_notional_usd=config.max_live_daily_notional_usd,
    )
    
    save_wallet_config(new_config)
    
    if enable:
        print("✅ Manual confirmation ENABLED for live trades")
        print("   Trades will require manual approval before execution")
    else:
        print("🚨 Manual confirmation DISABLED for live trades")
        print("   Trades will execute automatically - USE WITH CAUTION")


def main() -> None:
    parser = argparse.ArgumentParser(description="Chloe Wallet CLI")
    subparsers = parser.add_subparsers(dest="command", help="Command")
    
    # status
    subparsers.add_parser("status", help="Show wallet status")
    
    # set
    set_parser = subparsers.add_parser("set", help="Set wallet mode")
    set_parser.add_argument("mode", choices=["paper", "live", "real"], help="Wallet mode")
    
    # confirm
    confirm_parser = subparsers.add_parser("confirm", help="Enable/disable manual confirmation")
    confirm_parser.add_argument("action", choices=["on", "off"], help="Enable (on) or disable (off)")
    
    args = parser.parse_args()
    
    if args.command == "status":
        cmd_status()
    elif args.command == "set":
        cmd_set(args.mode)
    elif args.command == "confirm":
        cmd_confirm(args.action == "on")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

