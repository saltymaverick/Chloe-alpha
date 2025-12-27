#!/usr/bin/env python3
"""
Recovery Ramp CLI Tool (Phase 5H)
----------------------------------

Runs recovery ramp evaluation and prints status.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from engine_alpha.risk.recovery_ramp import evaluate_recovery_ramp


def main() -> int:
    """Run recovery ramp evaluation."""
    print("RECOVERY RAMP (Phase 5H)")
    print("=" * 70)
    
    result = evaluate_recovery_ramp()
    
    # Print status
    capital_mode = result.get("capital_mode", "unknown")
    recovery_mode = result.get("recovery_mode", "OFF")
    recovery_score = result.get("recovery_score", 0.0)
    reason = result.get("reason", "")
    
    print(f"Capital Mode: {capital_mode}")
    print(f"Recovery Mode: {recovery_mode}")
    print(f"Recovery Score: {recovery_score:.3f}")
    print(f"Reason: {reason}")
    print()
    
    # Print gates
    print("Gates:")
    gates = result.get("gates", {})
    for gate_name, gate_pass in gates.items():
        status = "✓" if gate_pass else "✗"
        print(f"  {status} {gate_name}: {gate_pass}")
    print()
    
    # Print metrics
    print("Metrics:")
    metrics = result.get("metrics", {})
    pf_7d = metrics.get("pf_7d")
    pf_30d = metrics.get("pf_30d")
    pf_7d_slope = metrics.get("pf_7d_slope")
    clean_closes = metrics.get("recent_clean_closes", 0)
    loss_closes = metrics.get("recent_loss_closes", 0)
    
    print(f"  PF_7D: {pf_7d:.3f}" if pf_7d is not None else "  PF_7D: —")
    print(f"  PF_30D: {pf_30d:.3f}" if pf_30d is not None else "  PF_30D: —")
    if pf_7d_slope is not None:
        print(f"  PF_7D Slope: {pf_7d_slope:+.6f} PF/hour")
    else:
        print(f"  PF_7D Slope: —")
    pf_age = metrics.get("pf_timeseries_age_minutes")
    if pf_age is not None:
        print(f"  PF Timeseries Age: {pf_age:.1f} minutes")
    else:
        print(f"  PF Timeseries Age: —")
    min_base = metrics.get("min_clean_closes_base")
    min_req = metrics.get("min_clean_closes_required")
    if min_base is not None and min_req is not None:
        print(f"  Clean Closes (24h): {clean_closes} (required={min_req}, base={min_base})")
    else:
        print(f"  Clean Closes (24h): {clean_closes}")
    print(f"  Loss Closes (24h): {loss_closes}")
    print()
    
    # Print hysteresis
    print("Hysteresis:")
    hysteresis = result.get("hysteresis", {})
    ok_ticks = hysteresis.get("ok_ticks", 0)
    needed_ticks = hysteresis.get("needed_ok_ticks", 6)
    print(f"  OK Ticks: {ok_ticks}/{needed_ticks}")
    print()
    
    # Print allowances
    print("Allowances:")
    allowances = result.get("allowances", {})
    allow_trading = allowances.get("allow_recovery_trading", False)
    allowed_symbols = allowances.get("allowed_symbols", [])
    
    print(f"  Allow Recovery Trading: {allow_trading}")
    print(f"  Allowed Symbols: {', '.join(allowed_symbols) if allowed_symbols else '(none)'}")
    print()
    
    # Print notes
    notes = result.get("notes", [])
    if notes:
        print("Notes:")
        for note in notes:
            print(f"  • {note}")
        print()
    
    print(f"State written to: {REPO_ROOT / 'reports' / 'risk' / 'recovery_ramp.json'}")
    print("=" * 70)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

