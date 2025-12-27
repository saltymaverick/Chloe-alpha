#!/usr/bin/env python3
"""
Wallet CLI tool - Phase 1
Simple interface for inspecting wallet state.
All operations are read-only / simulated.

README
======

How Wallets Work:
-----------------
Chloe uses a unified wallet abstraction that supports multiple wallet types:
- paper: Simulated wallets with no real funds (current implementation)
- cex_stub: Placeholder for future CEX (Binance, Bybit) integration
- evm_stub: Placeholder for future EVM (Ethereum, L2s) integration

Everything is 100% simulated - no API calls, no blockchain RPC, no real money.

Wallet Registry:
-----------------
Wallets are registered in config/wallet_registry.json. This file is safe to commit
as it contains no secrets (only metadata). Real API keys/secrets will go in a
separate wallet_secrets.yaml file (gitignored) when CEX/EVM integration is added.

Usage:
------
List all wallets:
    python3 -m tools.wallets list

Get snapshot for a specific wallet:
    python3 -m tools.wallets snapshot --id paper_ethusdt_main

Simulate an order (dry-run):
    python3 -m tools.wallets simulate --id paper_ethusdt_main --symbol ETHUSDT --side buy --qty 0.1

JSON output:
    Add --json flag to any command for machine-readable output.
"""

import argparse
import json
from pathlib import Path

from engine_alpha.wallets.registry import load_wallets, get_wallet
from engine_alpha.core.paths import CONFIG


def cmd_list(args):
    """List all registered wallets."""
    registry_path = CONFIG / "wallet_registry.json"
    
    if not registry_path.exists():
        print(f"❌ Wallet registry not found at {registry_path}")
        print("   Create config/wallet_registry.json to register wallets.")
        return 1
    
    wallets = load_wallets(registry_path)
    
    if not wallets:
        print("No wallets registered.")
        return 0
    
    print(f"{'ID':<25} {'Label':<30} {'Kind':<12} {'Equity':>12} {'Currency':<8} {'Positions':<10}")
    print("-" * 100)
    
    for wallet_id, wallet in sorted(wallets.items()):
        try:
            snapshot = wallet.snapshot()
            pos_count = len(snapshot.positions)
            print(
                f"{snapshot.id:<25} "
                f"{snapshot.label:<30} "
                f"kind={snapshot.kind:<10} "
                f"equity={snapshot.equity:>10.2f} "
                f"{snapshot.base_ccy:<8} "
                f"{pos_count} symbols"
            )
        except Exception as e:
            print(f"{wallet_id:<25} ERROR: {e}")
    
    return 0


def cmd_snapshot(args):
    """Get detailed snapshot for a specific wallet."""
    registry_path = CONFIG / "wallet_registry.json"
    
    if not registry_path.exists():
        print(f"❌ Wallet registry not found at {registry_path}")
        return 1
    
    wallet = get_wallet(args.id, registry_path)
    
    if not wallet:
        print(f"❌ Wallet '{args.id}' not found in registry.")
        print(f"   Available wallets:")
        wallets = load_wallets(registry_path)
        for w_id in sorted(wallets.keys()):
            print(f"     - {w_id}")
        return 1
    
    try:
        snapshot = wallet.snapshot()
        
        if args.json:
            # JSON output
            output = {
                "id": snapshot.id,
                "label": snapshot.label,
                "kind": snapshot.kind,
                "equity": snapshot.equity,
                "base_ccy": snapshot.base_ccy,
                "positions": snapshot.positions,
            }
            print(json.dumps(output, indent=2))
        else:
            # Human-readable output
            print("=" * 70)
            print(f"Wallet Snapshot: {snapshot.label}")
            print("=" * 70)
            print(f"ID:       {snapshot.id}")
            print(f"Label:    {snapshot.label}")
            print(f"Kind:     {snapshot.kind}")
            print(f"Equity:   {snapshot.equity:.2f} {snapshot.base_ccy}")
            print(f"Positions: {len(snapshot.positions)} symbols")
            
            if snapshot.positions:
                print("\nOpen Positions:")
                for symbol, pos_data in snapshot.positions.items():
                    print(f"  {symbol}: {json.dumps(pos_data, indent=4)}")
            else:
                print("\nNo open positions.")
            
            print("=" * 70)
        
        return 0
    except Exception as e:
        print(f"❌ Error getting snapshot: {e}")
        return 1


def cmd_simulate(args):
    """Simulate an order (dry-run, no real execution)."""
    registry_path = CONFIG / "wallet_registry.json"
    
    if not registry_path.exists():
        print(f"❌ Wallet registry not found at {registry_path}")
        return 1
    
    wallet = get_wallet(args.id, registry_path)
    
    if not wallet:
        print(f"❌ Wallet '{args.id}' not found in registry.")
        return 1
    
    try:
        result = wallet.simulate_order(
            symbol=args.symbol,
            side=args.side,
            qty=float(args.qty),
        )
        
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("=" * 70)
            print(f"Order Simulation: {args.symbol} {args.side.upper()} {args.qty}")
            print("=" * 70)
            print(f"Status: {result.get('status', 'unknown')}")
            print(f"Symbol: {result.get('symbol', 'N/A')}")
            print(f"Side:   {result.get('side', 'N/A').upper()}")
            print(f"Qty:    {result.get('qty', 0.0)}")
            
            fills = result.get("fills", [])
            if fills:
                print(f"\nFills ({len(fills)}):")
                for i, fill in enumerate(fills, 1):
                    print(f"  {i}. Price: {fill.get('price', 0.0):.2f}, Qty: {fill.get('qty', 0.0)}, Fee: {fill.get('fee', 0.0):.4f}")
            else:
                print("\nNo fills (simulation only)")
            
            if "note" in result:
                print(f"\nNote: {result['note']}")
            
            print("=" * 70)
        
        return 0
    except Exception as e:
        print(f"❌ Error simulating order: {e}")
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Wallet CLI - Inspect wallet state (read-only)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s list
  %(prog)s snapshot --id paper_ethusdt_main
  %(prog)s snapshot --id paper_ethusdt_main --json
  %(prog)s simulate --id paper_ethusdt_main --symbol ETHUSDT --side buy --qty 0.1
        """,
    )
    
    subparsers = parser.add_subparsers(dest="cmd", help="Command")
    
    # list command
    subparsers.add_parser("list", help="List all registered wallets")
    
    # snapshot command
    snap_parser = subparsers.add_parser("snapshot", help="Get wallet snapshot")
    snap_parser.add_argument("--id", required=True, help="Wallet ID")
    snap_parser.add_argument("--json", action="store_true", help="Output as JSON")
    
    # simulate command
    sim_parser = subparsers.add_parser("simulate", help="Simulate an order (dry-run)")
    sim_parser.add_argument("--id", required=True, help="Wallet ID")
    sim_parser.add_argument("--symbol", required=True, help="Trading pair (e.g., ETHUSDT)")
    sim_parser.add_argument("--side", required=True, choices=["buy", "sell"], help="Order side")
    sim_parser.add_argument("--qty", required=True, type=float, help="Quantity to trade")
    sim_parser.add_argument("--json", action="store_true", help="Output as JSON")
    
    args = parser.parse_args()
    
    if not args.cmd:
        parser.print_help()
        return 1
    
    if args.cmd == "list":
        return cmd_list(args)
    elif args.cmd == "snapshot":
        return cmd_snapshot(args)
    elif args.cmd == "simulate":
        return cmd_simulate(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())

