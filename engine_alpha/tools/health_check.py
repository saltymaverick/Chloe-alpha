"""
Health check CLI tool for Phase A bulletproof core.

Prints loop health status, latest snapshot location, and recent incidents.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from engine_alpha.core.paths import REPORTS


def main() -> int:
    """Main entry point."""
    health_path = REPORTS / "loop_health.json"
    snapshot_path = REPORTS / "latest_snapshot.json"
    incidents_path = REPORTS / "incidents.jsonl"
    
    # Read health
    print("=== Loop Health ===")
    if not health_path.exists():
        print("No health data found (loop may not have run yet)")
    elif health_path.stat().st_size == 0:
        print("No loop health found (file exists but is empty - loop hasn't written yet)")
    else:
        try:
            content = health_path.read_text(encoding="utf-8")
            health = json.loads(content)
            
            print(f"Last tick: {health.get('last_tick_ts', 'N/A')}")
            print(f"Status: {'OK' if health.get('last_tick_ok', False) else 'FAIL'}")
            print(f"Duration: {health.get('last_tick_ms', 0):.1f}ms")
            print(f"Symbol: {health.get('symbol', 'N/A')}")
            print(f"Timeframe: {health.get('timeframe', 'N/A')}")
            print(f"Mode: {health.get('mode', 'N/A')}")
            print(f"Last action: {health.get('last_action', 'N/A')}")
            if health.get('last_reason'):
                print(f"Last reason: {health.get('last_reason')}")
            if health.get('last_error'):
                print(f"Last error: {health.get('last_error')}")
        except json.JSONDecodeError as e:
            size = health_path.stat().st_size
            preview = content[:200] if 'content' in locals() else ""
            print(f"Loop health unreadable (size={size} bytes, JSON decode error)")
            if preview:
                print(f"Preview: {preview}")
        except Exception as e:
            print(f"Error reading health: {e}")
    
    print()
    
    # Check snapshot
    print(f"\n=== Latest Snapshot ===")
    if not snapshot_path.exists():
        print("No snapshot found (loop may not have run yet)")
    elif snapshot_path.stat().st_size == 0:
        print("No snapshot found (file exists but is empty - loop hasn't written yet)")
    else:
        try:
            content = snapshot_path.read_text(encoding="utf-8")
            snapshot = json.loads(content)
            print(f"Location: {snapshot_path}")
            print(f"Timestamp: {snapshot.get('ts', 'N/A')}")
            print(f"Symbol: {snapshot.get('symbol', 'N/A')}")
            print(f"Timeframe: {snapshot.get('timeframe', 'N/A')}")
            print(f"Tick ID: {snapshot.get('meta', {}).get('tick_id', 'N/A')}")
        except json.JSONDecodeError as e:
            size = snapshot_path.stat().st_size
            preview = content[:200] if 'content' in locals() else ""
            print(f"Snapshot unreadable (size={size} bytes, JSON decode error)")
            if preview:
                print(f"Preview: {preview}")
        except Exception as e:
            print(f"Error reading snapshot: {e}")
    
    print()
    
    # Check incidents
    if incidents_path.exists():
        try:
            with incidents_path.open("r") as f:
                lines = f.readlines()
            
            print(f"=== Incidents ===")
            print(f"Total incidents: {len(lines)}")
            print(f"Location: {incidents_path}")
            
            # Show last 3 incidents
            if lines:
                print("\nLast 3 incidents:")
                for line in lines[-3:]:
                    try:
                        incident = json.loads(line.strip())
                        print(f"  [{incident.get('ts', 'N/A')}] {incident.get('level', 'UNKNOWN')}: {incident.get('error_type', 'N/A')} - {incident.get('error', 'N/A')[:60]}")
                    except Exception:
                        print(f"  (invalid JSON line)")
        except Exception as e:
            print(f"Error reading incidents: {e}")
    else:
        print("=== Incidents ===")
        print("No incidents file found (good - no errors yet)")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

