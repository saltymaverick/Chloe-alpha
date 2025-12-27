"""
Capital Overview - CLI summary of all capital advisory outputs.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAPITAL_DIR = ROOT / "reports" / "capital"


def load_json(path: Path) -> dict:
    """Load JSON file."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def main() -> None:
    """Display capital overview."""
    print("\nCAPITAL OVERVIEW")
    print("=" * 70)
    print()
    
    # Load all capital advisory files
    allocation_advice = load_json(CAPITAL_DIR / "allocation_advice.json")
    buffers = load_json(CAPITAL_DIR / "buffers.json")
    subaccount_recs = load_json(CAPITAL_DIR / "subaccount_recommendations.json")
    consolidation_advice = load_json(CAPITAL_DIR / "consolidation_advice.json")
    withdrawal_plan = load_json(CAPITAL_DIR / "withdrawal_plan.json")
    
    # 1. Allocation Advice
    print("1. ALLOCATION ADVICE")
    print("-" * 70)
    if allocation_advice:
        allocations = allocation_advice.get("allocations", {})
        if allocations:
            print(f"Total symbols: {len(allocations)}")
            print(f"Total allocated: {allocation_advice.get('total_allocated_pct', 0):.1%}")
            print()
            for symbol, alloc in sorted(allocations.items()):
                print(f"  {symbol}: {alloc.get('target_pct', 0):.1%} "
                      f"(Tier: {alloc.get('tier', 'N/A')}, "
                      f"Score: {alloc.get('quality_score', 'N/A')})")
        else:
            print("  No allocations found")
    else:
        print("  No data yet — run capital allocation engine")
    print()
    
    # 2. Buffers
    print("2. BUFFERS")
    print("-" * 70)
    if buffers:
        print(f"Equity: ${buffers.get('equity', 0):,.2f}")
        print(f"Liquidity buffer: ${buffers.get('liquidity_buffer', 0):,.2f}")
        print(f"Emergency buffer: ${buffers.get('emergency_buffer', 0):,.2f}")
        print(f"Total buffers: ${buffers.get('total_buffers', 0):,.2f}")
        print(f"Available: ${buffers.get('available_for_allocation', 0):,.2f}")
    else:
        print("  No data yet — run capital buffer calculator")
    print()
    
    # 3. Subaccount Recommendations
    print("3. SUBACCOUNT RECOMMENDATIONS")
    print("-" * 70)
    if subaccount_recs:
        recommendations = subaccount_recs.get("recommendations", {})
        if recommendations:
            for subaccount, symbols in recommendations.items():
                if symbols:
                    print(f"  {subaccount}: {len(symbols)} symbols")
                    for sym in symbols[:5]:  # Show first 5
                        print(f"    - {sym}")
                    if len(symbols) > 5:
                        print(f"    ... and {len(symbols) - 5} more")
        else:
            print("  No recommendations found")
    else:
        print("  No data yet — run subaccount manager stub")
    print()
    
    # 4. Consolidation Advice
    print("4. CONSOLIDATION ADVICE")
    print("-" * 70)
    if consolidation_advice:
        action = consolidation_advice.get("action", "none")
        reason = consolidation_advice.get("reason", "N/A")
        print(f"Action: {action}")
        print(f"Reason: {reason}")
        if action == "consolidate":
            pct = consolidation_advice.get("suggested_pct_of_profit", 0)
            print(f"Suggested: {pct:.0%} of profit to VAULT")
    else:
        print("  No data yet — run profit consolidation engine")
    print()
    
    # 5. Withdrawal Plan
    print("5. WITHDRAWAL PLAN")
    print("-" * 70)
    if withdrawal_plan:
        allowed = withdrawal_plan.get("allowed", False)
        reason = withdrawal_plan.get("reason", "N/A")
        print(f"Allowed: {allowed}")
        print(f"Reason: {reason}")
        if withdrawal_plan.get("shadow"):
            print("  (Shadow mode - no real withdrawal)")
    else:
        print("  No data yet — run withdrawal adapter stub")
    print()
    
    print("=" * 70)
    print("💡 All capital operations are advisory-only and read-only.")
    print("   No real funds have been moved or allocated.")


if __name__ == "__main__":
    main()


