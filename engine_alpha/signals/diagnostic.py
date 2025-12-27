#!/usr/bin/env python3
"""
Signal diagnostic script - Phase 1
Prints diagnostic information about signal vector generation.
"""

import sys
from pathlib import Path

# Add /root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from engine_alpha.signals.signal_processor import get_signal_vector


def main():
    """Run diagnostic checks on signal vector."""
    print("Alpha Chloe - Signal Diagnostic (Phase 1)")
    print("=" * 50)
    
    try:
        # Get signal vector
        result = get_signal_vector(symbol="ETHUSDT", timeframe="15m")
        
        signal_vector = result["signal_vector"]
        raw_registry = result["raw_registry"]
        ts = result["ts"]
        
        # Print diagnostics
        print(f"\nTimestamp: {ts}")
        print(f"\nVector length: {len(signal_vector)}")
        
        # Count non-zero signals
        non_zero_count = sum(1 for v in signal_vector if abs(v) > 1e-10)
        print(f"Non-zero signals: {non_zero_count}/{len(signal_vector)}")
        
        # First 5 raw values
        print("\nFirst 5 raw values:")
        signal_names = list(raw_registry.keys())
        for i, name in enumerate(signal_names[:5]):
            raw_value = raw_registry[name].get("value", 0.0)
            normalized = signal_vector[i] if i < len(signal_vector) else 0.0
            print(f"  {name}: raw={raw_value:.6f}, normalized={normalized:.6f}")
        
        # Summary statistics
        print(f"\nSummary:")
        print(f"  Min normalized: {min(signal_vector):.6f}")
        print(f"  Max normalized: {max(signal_vector):.6f}")
        print(f"  Mean normalized: {sum(signal_vector) / len(signal_vector):.6f}")
        
        # Check that all values are in [-1, 1]
        all_in_range = all(-1.0 <= v <= 1.0 for v in signal_vector)
        print(f"  All values in [-1, 1]: {all_in_range}")
        
        # Check for NaN or Inf
        has_nan = any(v != v or not (-1e10 < v < 1e10) for v in signal_vector)
        print(f"  Contains NaN/Inf: {has_nan}")
        
        print("\n✅ Diagnostic complete")
        return 0
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

