#!/usr/bin/env python3
"""
Council diagnostic script - Phase 2
Tests confidence engine and regime classifier.
"""

import json
import sys
from pathlib import Path

# Add /root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from engine_alpha.signals.signal_processor import get_signal_vector
from engine_alpha.core.confidence_engine import decide
from engine_alpha.core.regime import RegimeClassifier


def main():
    """Run diagnostic checks on council decision."""
    print("Alpha Chloe - Council Diagnostic (Phase 2)")
    print("=" * 50)
    
    try:
        # Get signal vector
        signal_result = get_signal_vector(symbol="ETHUSDT", timeframe="1h")
        signal_vector = signal_result["signal_vector"]
        raw_registry = signal_result["raw_registry"]
        ts = signal_result["ts"]
        
        print(f"\nTimestamp: {ts}")
        print(f"Signal vector length: {len(signal_vector)}")
        
        # Initialize regime classifier (persistent state)
        classifier = RegimeClassifier()
        
        # Get decision
        decision = decide(signal_vector, raw_registry, classifier)
        
        # Print results
        print(f"\nRegime: {decision['regime']}")
        
        print("\nBucket breakdown:")
        for bucket_name, bucket_data in decision["buckets"].items():
            print(f"  {bucket_name:12s}: dir={bucket_data['dir']:2d}, conf={bucket_data['conf']:.4f}, score={bucket_data['score']:.4f}")
        
        print(f"\nFinal:")
        print(f"  dir: {decision['final']['dir']}")
        print(f"  conf: {decision['final']['conf']:.4f}")
        
        print(f"\nGates:")
        print(f"  entry_min_conf: {decision['gates']['entry_min_conf']:.2f}")
        print(f"  exit_min_conf: {decision['gates']['exit_min_conf']:.2f}")
        print(f"  reverse_min_conf: {decision['gates']['reverse_min_conf']:.2f}")
        
        # Write snapshot to reports
        snapshot = {
            "timestamp": ts,
            "regime": decision["regime"],
            "buckets": decision["buckets"],
            "final": decision["final"],
            "gates": decision["gates"],
        }
        
        # Write to /root/Chloe-alpha/reports/council_snapshot.json
        reports_dir = Path("/root/Chloe-alpha/reports")
        reports_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = reports_dir / "council_snapshot.json"
        
        with open(snapshot_path, "w") as f:
            json.dump(snapshot, f, indent=2)
        
        print(f"\n✅ Council snapshot written to: {snapshot_path}")
        print("\n✅ Diagnostic complete")
        return 0
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

