"""
Apply Promotion - Promote a variant strategy to active status (paper mode only).

This tool updates the strategy registry to mark a variant as the active strategy
for a symbol. This ONLY affects paper mode trading, not live trading.

Usage:
    python3 -m tools.apply_promotion --symbol ETHUSDT --variant ETH_main_mut_0003
"""

from __future__ import annotations

import argparse
import sys
import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.core.paths import CONFIG

REGISTRY_PATH = CONFIG / "strategy_registry.yaml"


def apply_promotion(symbol: str, variant_id: str) -> None:
    """
    Apply promotion by updating strategy registry.
    
    Args:
        symbol: Symbol to promote (e.g., "ETHUSDT")
        variant_id: Variant ID to promote (e.g., "ETH_main_mut_0003")
    
    Raises:
        ValueError: If symbol not in registry or variant_id invalid
    """
    # Load registry
    if not REGISTRY_PATH.exists():
        raise ValueError(f"Strategy registry not found at {REGISTRY_PATH}")
    
    try:
        data = yaml.safe_load(REGISTRY_PATH.read_text()) or {}
    except Exception as e:
        raise ValueError(f"Failed to load strategy registry: {e}")
    
    # Ensure symbol exists
    if symbol not in data:
        # Auto-create entry if symbol not found
        data[symbol] = {
            "active_strategy": f"{symbol}_main",
            "parent_strategy": f"{symbol}_main",
            "variants": [],
        }
    
    entry = data[symbol]
    
    # Update active strategy
    old_strategy = entry.get("active_strategy", f"{symbol}_main")
    entry["active_strategy"] = variant_id
    
    # Track variant in variants list if not already there
    variants = entry.setdefault("variants", [])
    if variant_id not in variants:
        variants.append(variant_id)
    
    # Save registry
    try:
        REGISTRY_PATH.write_text(yaml.safe_dump(data, default_flow_style=False, sort_keys=True))
    except Exception as e:
        raise ValueError(f"Failed to save strategy registry: {e}")
    
    print(f"📈 Paper promotion applied: {symbol}")
    print(f"   Old strategy: {old_strategy}")
    print(f"   New strategy: {variant_id}")
    print()
    print("⚠️  This change affects PAPER MODE ONLY.")
    print("   Live trading is NOT affected.")
    print()
    print(f"   Registry updated: {REGISTRY_PATH}")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Promote a variant strategy to active status (paper mode only)"
    )
    parser.add_argument(
        "--symbol",
        required=True,
        help="Symbol to promote (e.g., ETHUSDT)",
    )
    parser.add_argument(
        "--variant",
        required=True,
        help="Variant ID to promote (e.g., ETH_main_mut_0003)",
    )
    
    args = parser.parse_args()
    
    try:
        apply_promotion(args.symbol.upper(), args.variant)
        return 0
    except ValueError as e:
        print(f"❌ Error: {e}")
        return 1
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

