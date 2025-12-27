#!/usr/bin/env python3
"""
Run Quarantine Engine (Phase 5g)
---------------------------------

CLI tool to run the loss-contributor quarantine engine.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.risk.quarantine import run_quarantine
from engine_alpha.risk.capital_plan_quarantine import run_capital_plan_quarantine


def main() -> int:
    """Run quarantine engine."""
    print("LOSS-CONTRIBUTOR QUARANTINE (Phase 5g)")
    print("=" * 70)
    print()
    
    # Run quarantine builder
    quarantine_state = run_quarantine()
    
    enabled = quarantine_state.get("enabled", False)
    capital_mode = quarantine_state.get("capital_mode", "unknown")
    quarantined = quarantine_state.get("quarantined", [])
    blocked_symbols = quarantine_state.get("blocked_symbols", [])
    
    print(f"Enabled: {enabled}")
    print(f"Capital Mode: {capital_mode}")
    print(f"Quarantined Symbols: {len(quarantined)}")
    print()
    
    if quarantined:
        print("QUARANTINED SYMBOLS:")
        print("-" * 70)
        for q in quarantined:
            symbol = q["symbol"]
            pnl = q["pnl_usd"]
            contrib = q["contribution_pct"]
            cooldown = q.get("cooldown_until", "?")
            print(f"{symbol:<12} PnL=${pnl:+.2f}  Contribution={contrib:.1f}%  Cooldown={cooldown[:19]}")
        print()
    
    if blocked_symbols:
        print(f"BLOCKED SYMBOLS: {', '.join(blocked_symbols)}")
        print()
    
    # Run capital plan overlay
    if enabled and quarantine_state.get("weight_adjustments"):
        print("Applying quarantine weight adjustments...")
        modified_plan = run_capital_plan_quarantine()
        print(f"Modified capital plan written to: reports/risk/capital_plan_quarantine.json")
        print()
    
    notes = quarantine_state.get("notes", [])
    if notes:
        print("NOTES:")
        for note in notes:
            print(f"  - {note}")
    
    print()
    print("=" * 70)
    print(f"State written to: reports/risk/quarantine.json")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

