"""
Nightly Orchestrator - Phase 4
Coordinates system sanity, gatekeeper, and nightly research cycle.

This orchestrator:
1. Runs system sanity checks
2. Evaluates gatekeeper status
3. Runs nightly research cycle if gates pass
4. Writes orchestration report

All operations are advisory-only. No configs are modified, no exchange APIs are called.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List

ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "reports"
SYSTEM_REPORT_DIR = REPORTS_DIR / "system"
PIPELINE_DIR = REPORTS_DIR / "pipeline"
SANITY_REPORT_PATH = SYSTEM_REPORT_DIR / "sanity_report.json"
GATEKEEPER_REPORT_PATH = SYSTEM_REPORT_DIR / "gatekeeper_report.json"
ORCHESTRATION_REPORT_PATH = PIPELINE_DIR / "nightly_orchestration.json"


def load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file, return empty dict if missing or invalid."""
    if not path.exists():
        return {}
    try:
        content = path.read_text().strip()
        if not content:
            return {}
        return json.loads(content)
    except Exception:
        return {}


def main() -> None:
    """Main orchestration entry point."""
    print("NIGHTLY ORCHESTRATION")
    print("=" * 70)
    print()
    
    reasons: List[str] = []
    research_run = False
    
    # Step 1: Run System Sanity
    print("Step 1: Running system sanity check...")
    try:
        from tools import system_sanity
        system_sanity.main()
        print("  ✅ System sanity check completed")
    except Exception as e:
        print(f"  ⚠️  System sanity check failed: {e}")
        reasons.append(f"System sanity check failed: {e}")
    
    # Load sanity report
    sanity_report = load_json(SANITY_REPORT_PATH)
    sanity_ok = False
    
    if sanity_report:
        summary = sanity_report.get("summary", {})
        sanity_ok = summary.get("success", False)
        if sanity_ok:
            reasons.append("System sanity passed")
        else:
            errors = summary.get("errors", [])
            reasons.append(f"Sanity suite failed: {len(errors)} errors")
    else:
        reasons.append("Sanity report missing")
    
    print(f"  Sanity status: {'PASS' if sanity_ok else 'FAIL'}")
    print()
    
    # Step 2: Evaluate Gatekeeper
    print("Step 2: Evaluating gatekeeper...")
    gate_decision = False
    
    # Check if gatekeeper module exists
    gatekeeper_path = ROOT / "engine_alpha" / "evolve" / "gatekeeper.py"
    if gatekeeper_path.exists():
        try:
            # Run gatekeeper cycle
            from tools import run_gatekeeper_cycle
            run_gatekeeper_cycle.main()
            print("  ✅ Gatekeeper cycle completed")
            
            # Load gatekeeper report with safe error handling
            gate_status = "UNKNOWN"
            gate_decision = False
            
            try:
                gatekeeper_report = load_json(GATEKEEPER_REPORT_PATH)
                
                if isinstance(gatekeeper_report, list):
                    raise ValueError("Gatekeeper report is list, expected dict")
                
                if not isinstance(gatekeeper_report, dict):
                    raise ValueError(f"Gatekeeper report is {type(gatekeeper_report).__name__}, expected dict")
                
                gate_decision = bool(gatekeeper_report.get("allow_automation", False))
                gate_status = "PASS" if gate_decision else "DENY"
                
                if gate_decision:
                    reasons.append("Gatekeeper allowed automation")
                else:
                    reasons.append("Gatekeeper denied automation")
            except Exception as exc:
                gate_status = f"FAIL ({exc})"
                gate_decision = False
                reasons.append(f"Gatekeeper evaluation failed: {exc}")
        except Exception as e:
            print(f"  ⚠️  Gatekeeper evaluation failed: {e}")
            reasons.append(f"Gatekeeper evaluation failed: {e}")
            # If gatekeeper fails, don't allow automation
            gate_decision = False
    else:
        print("  ⚠️  Gatekeeper module not found")
        # If gatekeeper missing, only allow if sanity passed
        gate_decision = sanity_ok
        if gate_decision:
            reasons.append("Gatekeeper missing; allowing based on sanity check only")
        else:
            reasons.append("Gatekeeper missing; refusing to run automation")
    
    print(f"  Gatekeeper status: {gate_status}")
    print(f"  Gatekeeper decision: {'ALLOW' if gate_decision else 'DENY'}")
    print()
    
    # Step 3: Decide whether to run research cycle
    print("Step 3: Evaluating research cycle decision...")
    
    if sanity_ok and gate_decision:
        print("  ✅ All gates passed - running research cycle")
        print()
        
        try:
            from tools import nightly_research_cycle
            nightly_research_cycle.main()
            research_run = True
            reasons.append("Nightly research cycle executed")
        except Exception as e:
            print(f"  ⚠️  Research cycle failed: {e}")
            reasons.append(f"Research cycle execution failed: {e}")
    else:
        print("  ⚠️  Gates not passed - skipping research cycle")
        if not sanity_ok:
            reasons.append("Skipped research cycle: sanity check failed")
        if not gate_decision:
            reasons.append("Skipped research cycle: gatekeeper denied automation")
    
    print()
    
    # Step 4: Write orchestration report
    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "sanity_ok": sanity_ok,
        "gate_decision": gate_decision,
        "research_run": research_run,
        "reasons": reasons,
    }
    
    PIPELINE_DIR.mkdir(parents=True, exist_ok=True)
    ORCHESTRATION_REPORT_PATH.write_text(json.dumps(report, indent=2))
    
    # Print summary
    print("=" * 70)
    print("ORCHESTRATION SUMMARY")
    print("=" * 70)
    print(f"Sanity: {'PASS' if sanity_ok else 'FAIL'}")
    print(f"Gatekeeper: {gate_status}")
    print(f"Nightly Research: {'RUN' if research_run else 'SKIP'}")
    print()
    
    if reasons:
        print("Reasons:")
        for reason in reasons:
            print(f"  • {reason}")
    
    print()
    print(f"Report written to: {ORCHESTRATION_REPORT_PATH}")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️  Orchestration interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Orchestration crashed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

