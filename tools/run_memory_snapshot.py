"""
Run Memory Snapshot - Phase 2
CLI tool to take a snapshot of current GPT outputs and research data.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine_alpha.research.research_memory import take_snapshot, get_memory_count


def main() -> int:
    """Take a memory snapshot and print summary."""
    print("📸 Taking research memory snapshot...")
    
    snapshot = take_snapshot()
    
    # Count non-None entries
    non_none = sum(1 for v in snapshot.values() if v is not None and v != snapshot.get("ts"))
    
    print(f"✅ Snapshot taken at {snapshot['ts']}")
    print(f"   Captured {non_none} data sources:")
    
    if snapshot.get("reflection"):
        print("   - Reflection output")
    if snapshot.get("tuner"):
        print("   - Tuner output")
    if snapshot.get("dream"):
        print("   - Dream output")
    if snapshot.get("quality_scores"):
        print("   - Quality scores")
    if snapshot.get("drift"):
        print("   - Drift report")
    if snapshot.get("are"):
        print("   - ARE snapshot")
    
    total_count = get_memory_count()
    print(f"\n📚 Total memory entries: {total_count}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

