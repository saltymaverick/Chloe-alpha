"""
Run Execution Quality Scan - Analyze execution performance by microstructure regime.

This tool analyzes how well execution performs in different microstructure regimes
and writes an advisory report to reports/research/execution_quality.json.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.research.execution_quality_analyzer import (
    analyze_execution_quality,
    save_execution_quality,
    RESEARCH_DIR,
    TRADES_PATH,
)

MICROSTRUCTURE_PATH = RESEARCH_DIR / "microstructure_snapshot_15m.json"


def main() -> int:
    """Main entry point."""
    print("EXECUTION QUALITY SCAN")
    print("=" * 70)
    print()
    
    # Check if required files exist
    if not TRADES_PATH.exists():
        print("⚠️  Warning: trades.jsonl not found. Skipping execution quality scan.")
        return 0
    
    if not MICROSTRUCTURE_PATH.exists():
        print("⚠️  Warning: microstructure_snapshot_15m.json not found.")
        print("   Run: python3 -m tools.run_microstructure_scan")
        print("   Skipping execution quality scan.")
        return 0
    
    try:
        # Analyze execution quality
        quality_data = analyze_execution_quality(
            trades_path=TRADES_PATH,
            microstructure_path=MICROSTRUCTURE_PATH,
            timeframe="15m"
        )
        
        if not quality_data:
            print("⚠️  No execution quality data computed.")
            print("   Ensure trades.jsonl contains closed trades with pct values.")
            return 0
        
        # Save report
        output_path = save_execution_quality(quality_data)
        print(f"✅ Execution quality report written to: {output_path}")
        print()
        
        # Print summary
        print("EXECUTION QUALITY SUMMARY")
        print("-" * 70)
        
        friendly_regimes = []
        hostile_regimes = []
        
        for symbol in sorted(quality_data.keys()):
            symbol_data = quality_data[symbol]
            print(f"\n{symbol}:")
            
            for micro_regime in sorted(symbol_data.keys()):
                # Skip "summary" key - it's not a regime
                if micro_regime == "summary":
                    continue
                
                regime_data = symbol_data[micro_regime]
                if not isinstance(regime_data, dict):
                    continue
                
                trades = regime_data.get("trades", 0)
                avg_pct = regime_data.get("avg_pct", 0.0)
                win_rate = regime_data.get("win_rate", 0.0)
                label = regime_data.get("label", "neutral")
                big_win = regime_data.get("big_win_count", regime_data.get("big_win", 0))  # Support both old and new field names
                big_loss = regime_data.get("big_loss_count", regime_data.get("big_loss", 0))  # Support both old and new field names
                
                avg_pct_pct = avg_pct * 100
                win_rate_pct = win_rate * 100
                
                print(f"  {micro_regime}:")
                print(f"    trades={trades}, avg_pct={avg_pct_pct:+.2f}%, win_rate={win_rate_pct:.1f}%")
                print(f"    big_win_count={big_win}, big_loss_count={big_loss}, label={label}")
            
            # v2: Show overall summary
            summary = symbol_data.get("summary", {})
            if summary:
                overall_label = summary.get("overall_label", "neutral")
                friendly = summary.get("friendly_regimes", [])
                hostile = summary.get("hostile_regimes", [])
                print(f"  Overall: {overall_label}")
                if friendly:
                    print(f"    Friendly regimes: {', '.join(friendly)}")
                if hostile:
                    print(f"    Hostile regimes: {', '.join(hostile)}")
                
                # Collect friendly/hostile regimes for overall summary
                for micro_regime_inner in symbol_data.keys():
                    if micro_regime_inner == "summary":
                        continue
                    regime_data_inner = symbol_data[micro_regime_inner]
                    if isinstance(regime_data_inner, dict):
                        label_inner = regime_data_inner.get("label", "neutral")
                        if label_inner == "friendly":
                            friendly_regimes.append(f"{symbol}:{micro_regime_inner}")
                        elif label_inner == "hostile":
                            hostile_regimes.append(f"{symbol}:{micro_regime_inner}")
        
        # Overall summary
        print()
        print("OVERALL SUMMARY")
        print("-" * 70)
        
        if friendly_regimes:
            print("  Friendly regimes:")
            for regime in friendly_regimes:
                print(f"    - {regime}")
        else:
            print("  Friendly regimes: (none identified)")
        
        if hostile_regimes:
            print("  Hostile regimes:")
            for regime in hostile_regimes:
                print(f"    - {regime}")
        else:
            print("  Hostile regimes: (none identified)")
        
        print()
        print("=" * 70)
        print("Note: Execution quality analysis is advisory-only.")
        print("=" * 70)
        
        return 0
    
    except Exception as e:
        print(f"❌ Execution quality scan failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

