#!/usr/bin/env python3
"""
Recovery Assist CLI Tool (Phase 5H.4)
--------------------------------------

Runs recovery assist evaluation and prints status.
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from engine_alpha.risk.recovery_assist import evaluate_recovery_assist
from engine_alpha.core.paths import REPORTS

RECOVERY_ASSIST_PATH = REPORTS / "risk" / "recovery_assist.json"


def main() -> int:
    """Main entry point."""
    print("Recovery Assist (Phase 5H.4)")
    print("=" * 70)
    print()
    
    # Evaluate
    result = evaluate_recovery_assist()
    
    # Save to file
    RECOVERY_ASSIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    RECOVERY_ASSIST_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    
    # Print status
    assist_enabled = result.get("assist_enabled", False)
    reason = result.get("reason", "")
    gates = result.get("gates", {})
    metrics = result.get("metrics", {})
    
    print(f"Assist Enabled: {'YES' if assist_enabled else 'NO'}")
    print(f"Reason         : {reason}")
    print()
    print("Gates:")
    print(f"  Trades 24h (>=30)     : {'PASS' if gates.get('trades_24h') else 'FAIL'}")
    print(f"  PF 24h (>=1.10)       : {'PASS' if gates.get('pf_24h') else 'FAIL'}")
    print(f"  MDD 24h (<=2.0%)      : {'PASS' if gates.get('mdd_24h') else 'FAIL'}")
    print(f"  Symbol Diversity      : {'PASS' if gates.get('symbol_diversity') else 'FAIL'}")
    print(f"  Net PnL USD (>0)      : {'PASS' if gates.get('net_pnl_usd_24h') else 'FAIL'}")
    print(f"  Worst Dominant Symbol Exp (>=-0.05%): {'PASS' if gates.get('worst_symbol_expectancy_24h') else 'FAIL'}")
    print()
    print("Metrics:")
    print(f"  Trades 24h    : {metrics.get('trades_24h', 0)}")
    print(f"  PF 24h        : {metrics.get('pf_24h', 0.0):.3f}")
    print(f"  MDD 24h       : {metrics.get('mdd_24h', 0.0):.3f}%")
    print(f"  Symbols (3+ closes): {metrics.get('symbols_with_3+_closes', metrics.get('symbols_with_sufficient_closes', 0))}")
    print(f"  Non-SOL closes: {metrics.get('non_sol_closes_24h', 0)}")
    net_pnl = metrics.get('net_pnl_usd_24h', 0.0)
    print(f"  Net PnL USD   : ${net_pnl:+.4f}")
    worst_exp = metrics.get('worst_symbol_expectancy_24h')
    if worst_exp is not None:
        print(f"  Worst Dominant Symbol Exp: {worst_exp:.3f}% (dominant=≥8 closes or ≥25%)")
    else:
        print(f"  Worst Dominant Symbol Exp: N/A (no dominant symbols)")
    print()
    print("Symbol Counts (24h):")
    symbol_counts = result.get("symbol_counts_24h", {})
    if symbol_counts:
        for symbol, count in sorted(symbol_counts.items(), key=lambda x: -x[1]):
            print(f"  {symbol}: {count}")
    else:
        print("  (none)")
    print()
    print("=" * 70)
    print(f"State saved to: {RECOVERY_ASSIST_PATH}")
    print()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

