#!/usr/bin/env python3
"""
CLI wrapper for Capital Protection Engine.

Usage:
    python3 -m tools.run_capital_protection

This is ADVISORY-ONLY and PAPER-SAFE.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine_alpha.risk.capital_protection import run_capital_protection


def main() -> int:
    try:
        result = run_capital_protection()
        print("Capital Protection analysis completed")
        print(f"Results written to: reports/risk/capital_protection.json")
        
        # Print summary
        global_mode = result.get("global", {})
        if global_mode:
            mode = global_mode.get("mode", "unknown")
            pf_7d = global_mode.get("pf_7d")
            pf_30d = global_mode.get("pf_30d")
            print(f"\nGlobal Risk Mode: {mode}")
            print(f"PF_7D: {pf_7d if pf_7d is not None else '—'}")
            print(f"PF_30D: {pf_30d if pf_30d is not None else '—'}")
            
            reasons = global_mode.get("reasons", [])
            if reasons:
                print("\nReasons:")
                for r in reasons:
                    print(f"  • {r}")
            
            actions = global_mode.get("actions", [])
            if actions:
                print("\nRecommended Actions:")
                for a in actions:
                    print(f"  • {a}")
        
        symbols = result.get("symbols", [])
        if symbols:
            print(f"\nSymbol Stances ({len(symbols)} symbols):")
            print("-" * 70)
            print("Symbol   Stance      PF_7D    PF_30D")
            print("-" * 70)
            for sym in symbols[:10]:  # Show first 10
                symbol = sym.get("symbol", "?")
                stance = sym.get("stance", "?")
                pf_7d = sym.get("pf_7d")
                pf_30d = sym.get("pf_30d")
                pf_7d_str = f"{pf_7d:.3f}" if pf_7d is not None else " — "
                pf_30d_str = f"{pf_30d:.3f}" if pf_30d is not None else " — "
                print(f"{symbol:<8} {stance:<12} {pf_7d_str:<8} {pf_30d_str}")
            if len(symbols) > 10:
                print(f"... and {len(symbols) - 10} more symbols")
        
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

