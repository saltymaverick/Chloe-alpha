"""
Run Gatekeeper Cycle - Run sanity + gate evaluation as a single step.

This tool runs system sanity checks and then evaluates whether automation
is allowed to proceed. All decisions are ADVISORY ONLY.
"""

from __future__ import annotations

from pathlib import Path
from engine_alpha.evolve.gatekeeper import (
    evaluate_gate_status,
    save_gatekeeper_report,
)
from tools import system_sanity

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """Main entry point."""
    print("GATEKEEPER CYCLE")
    print("-" * 70)
    print()
    
    # Step 1: Run system sanity
    print("Step 1: Running system sanity check...")
    try:
        system_sanity.main()
        print("   ✅ System sanity check completed")
    except Exception as e:
        print(f"   ⚠️  System sanity check failed: {e}")
        print("   Continuing with gatekeeper evaluation...")
    print()
    
    # Step 2: Evaluate gate status
    print("Step 2: Evaluating gate status...")
    gate_status = evaluate_gate_status()
    
    # Step 3: Save report
    report_path = save_gatekeeper_report(gate_status)
    print(f"   ✅ Gatekeeper report written to: {report_path}")
    print()
    
    # Step 4: Print summary
    print("GATEKEEPER SUMMARY")
    print("-" * 70)
    
    sanity_status = "PASS" if gate_status["sanity_ok"] else "FAIL"
    pf_status = "PASS" if gate_status["pf_ok"] else "FAIL"
    automation_status = "YES" if gate_status["allow_automation"] else "NO"
    
    print(f"Sanity: {sanity_status}")
    print(f"PF: {pf_status}")
    print(f"Allow Automation: {automation_status}")
    print()
    
    if gate_status.get("reasons"):
        print("Reasons:")
        for reason in gate_status["reasons"]:
            print(f"  - {reason}")
    
    print()
    print("=" * 70)
    print("Note: All decisions are ADVISORY ONLY. No actions were taken.")
    print("=" * 70)


if __name__ == "__main__":
    main()


