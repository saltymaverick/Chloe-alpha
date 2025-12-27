"""
Run Drift Scan - Phase 5
CLI tool to compute and display drift analysis.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine_alpha.research.drift_tracker import compute_drift_report


def main() -> int:
    """Run drift scan and print summary."""
    print("DRIFT SCAN")
    print("=" * 70)
    print()
    
    report = compute_drift_report()
    symbols_data = report.get("symbols", {})
    
    if not symbols_data:
        print("⚠️  No symbol data found")
        print("   Run some trades first to generate drift analysis")
        return 0
    
    print("DRIFT STATUS BY SYMBOL:")
    print("-" * 70)
    print(f"{'Symbol':<12} {'Status':<12} {'Early PF':>10} {'Recent PF':>10} {'Delta PF':>10} {'Trades':>8}")
    print("-" * 70)
    
    for symbol, data in sorted(symbols_data.items()):
        status = data.get("status", "unknown")
        early_pf = data.get("early_pf")
        recent_pf = data.get("recent_pf")
        delta_pf = data.get("delta_pf")
        total_trades = data.get("total_trades", 0)
        
        early_str = "inf" if early_pf == "inf" else (f"{early_pf:.2f}" if early_pf is not None else "N/A")
        recent_str = "inf" if recent_pf == "inf" else (f"{recent_pf:.2f}" if recent_pf is not None else "N/A")
        delta_str = f"{delta_pf:+.2f}" if delta_pf is not None else "N/A"
        
        print(f"{symbol:<12} {status:<12} {early_str:>10} {recent_str:>10} {delta_str:>10} {total_trades:>8}")
    
    print()
    print(f"✅ Drift report written to: {report.get('_report_path', 'reports/research/drift_report.json')}")
    print("=" * 70)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

