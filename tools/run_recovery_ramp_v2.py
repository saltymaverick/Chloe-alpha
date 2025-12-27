#!/usr/bin/env python3
"""
Recovery Ramp V2 CLI Tool (Phase 5H.2)
---------------------------------------

Runs per-symbol recovery ramp v2 evaluation and prints status.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from engine_alpha.risk.recovery_ramp_v2 import evaluate_recovery_ramp_v2


def main() -> int:
    """Run recovery ramp v2 evaluation."""
    print("RECOVERY RAMP V2 (Per-Symbol) (Phase 5H.2)")
    print("=" * 70)
    
    result = evaluate_recovery_ramp_v2()
    
    # Print global status
    capital_mode = result.get("capital_mode", "unknown")
    global_data = result.get("global", {})
    decision = result.get("decision", {})
    
    print(f"Capital Mode: {capital_mode}")
    print(f"PF Timeseries Fresh: {global_data.get('pf_timeseries_fresh_pass', False)}")
    pf_age = global_data.get("pf_timeseries_age_minutes")
    if pf_age is not None:
        print(f"PF Timeseries Age: {pf_age:.1f} minutes")
    print(f"Allow Recovery Lane: {decision.get('allow_recovery_lane', False)}")
    print(f"Reason: {decision.get('reason', '')}")
    print()
    
    # Print allowed symbols
    allowed_symbols = decision.get("allowed_symbols", [])
    if allowed_symbols:
        print(f"Allowed Symbols: {', '.join(allowed_symbols)}")
    else:
        print("Allowed Symbols: (none)")
    print()
    
    # Print top candidates
    symbols = result.get("symbols", {})
    candidates = []
    
    for symbol, symbol_data in symbols.items():
        eligible = symbol_data.get("eligible", False)
        score = symbol_data.get("score", 0.0)
        reasons = symbol_data.get("reasons", [])
        
        candidates.append({
            "symbol": symbol,
            "eligible": eligible,
            "score": score,
            "reasons": reasons,
        })
    
    # Sort by score (descending)
    candidates.sort(key=lambda x: -x["score"])
    
    print("Top Candidates:")
    for i, cand in enumerate(candidates[:5], 1):
        status = "✓" if cand["eligible"] else "✗"
        print(f"  {status} {cand['symbol']:<10} Score: {cand['score']:.3f}  Reasons: {', '.join(cand['reasons'][:2])}")
    print()
    
    print(f"State written to: {REPO_ROOT / 'reports' / 'risk' / 'recovery_ramp_v2.json'}")
    print("=" * 70)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

