#!/usr/bin/env python3
"""
SWARM Audit Loop Runner

Run this periodically (e.g., every 5-10 minutes) via systemd/cron.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from engine_alpha.swarm.swarm_audit_loop import run_swarm_audit


def main():
    """Run SWARM audit and print results."""
    try:
        audit = run_swarm_audit()
        
        # Print summary
        print("=" * 60)
        print("SWARM AUDIT")
        print("=" * 60)
        print(f"Timestamp: {audit.ts}")
        print(f"Critical: {audit.sentinel.get('critical', False)}")
        print(f"PF Local: {audit.sentinel.get('pf_local', 0.0):.3f}")
        print(f"Drawdown: {audit.sentinel.get('drawdown', 0.0):.2%}")
        
        if audit.issues:
            print("\n⚠️  Issues:")
            for key, msg in audit.issues.items():
                print(f"  {key}: {msg}")
        else:
            print("\n✅ No issues detected")
        
        print("=" * 60)
        
        # Exit with error code if critical
        if audit.sentinel.get("critical", False):
            sys.exit(1)
        
    except Exception as e:
        print(f"❌ SWARM audit failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()


