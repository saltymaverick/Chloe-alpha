#!/usr/bin/env python3
"""
Loop diagnostic script - Phase 3
Tests trading loop execution.
"""

import json
import sys
from pathlib import Path

# Add /root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from engine_alpha.loop.autonomous_trader import AutonomousTrader
from engine_alpha.loop.position_manager import get_position_manager


def main():
    """Run diagnostic checks on trading loop."""
    print("Alpha Chloe - Loop Diagnostic (Phase 3)")
    print("=" * 50)
    
    try:
        # Reset position manager
        position_manager = get_position_manager()
        position_manager.clear_position()
        
        # Create trader
        trader = AutonomousTrader(symbol="ETHUSDT", timeframe="1h")
        
        # Run batch
        print("\nRunning batch of 25 steps...")
        summary = trader.run_batch(n=25)
        
        # Print results
        print(f"\nSummary:")
        print(f"  Steps: {summary['steps']}")
        print(f"  Opens: {summary['opens']}")
        print(f"  Closes: {summary['closes']}")
        print(f"  Reversals: {summary['reversals']}")
        print(f"  PF_local: {summary['pf_local']:.4f}")
        print(f"  PF_live: {summary['pf_live']:.4f}")
        
        # Get final position
        final_position = position_manager.get_open_position()
        print(f"\nFinal position: {final_position['direction']}")
        if final_position['direction'] != "FLAT":
            print(f"  Entry price: {final_position['entry_price']:.2f}")
            print(f"  Bars open: {final_position['bars_open']}")
        
        # Write loop health report
        from datetime import datetime, timezone
        health_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
            "final_position": final_position,
        }
        
        health_path = Path("/reports/loop_health.json")
        health_path.parent.mkdir(parents=True, exist_ok=True)
        with open(health_path, "w") as f:
            json.dump(health_data, f, indent=2)
        
        print(f"\n✅ Loop health written to: {health_path}")
        print("\n✅ Diagnostic complete")
        return 0
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

