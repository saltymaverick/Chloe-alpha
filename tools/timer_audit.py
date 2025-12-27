"""
Timer Audit Tool
-----------------

Checks for timer conflicts and provides recommendations.
"""

from __future__ import annotations

import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Tuple


def get_timers() -> List[Dict[str, str]]:
    """Get list of chloe timers from systemctl."""
    try:
        result = subprocess.run(
            ["systemctl", "list-timers", "--all", "--no-pager"],
            capture_output=True,
            text=True,
            check=True,
        )
        
        timers = []
        lines = result.stdout.splitlines()
        
        # Skip header lines (first 3 lines are headers)
        # Find where actual timer data starts
        start_idx = 0
        for i, line in enumerate(lines):
            if "next" in line.lower() and "left" in line.lower() and "last" in line.lower():
                start_idx = i + 1
                break
        
        for line in lines[start_idx:]:
            if not line.strip() or "timers listed" in line.lower():
                continue
            
            # Parse timer line
            parts = line.split()
            if len(parts) < 4:
                continue
            
            # Extract timer name - look for .timer first, then .service
            # Timer name is typically second-to-last (parts[-2]) or last (parts[-1])
            timer_name = None
            
            # First, try to find .timer in any part
            for part in parts:
                if part.endswith(".timer") and "chloe" in part.lower():
                    timer_name = part
                    break
            
            # If no .timer found, look for .service and convert
            if timer_name is None:
                for part in parts:
                    if part.endswith(".service") and "chloe" in part.lower():
                        timer_name = part.replace(".service", ".timer")
                        break
            
            # Fallback: check last two parts (timer is often second-to-last)
            if timer_name is None:
                for idx in [-2, -1]:
                    if abs(idx) <= len(parts):
                        candidate = parts[idx]
                        if "chloe" in candidate.lower():
                            if candidate.endswith(".timer"):
                                timer_name = candidate
                                break
                            elif candidate.endswith(".service"):
                                timer_name = candidate.replace(".service", ".timer")
                                break
            
            # Skip if no timer name found
            if timer_name is None or "chloe" not in timer_name.lower():
                continue
            
            # Extract next trigger time
            try:
                # Format: "Fri 2025-12-12 05:55:52 UTC"
                date_str = " ".join(parts[0:4])
                next_trigger = datetime.strptime(date_str, "%a %Y-%m-%d %H:%M:%S %Z")
            except Exception:
                next_trigger = None
            
            timers.append({
                "name": timer_name,
                "next_trigger": next_trigger,
                "raw_line": line,
            })
        
        return timers
    except Exception as e:
        print(f"ERROR: Failed to get timers: {e}")
        return []


def classify_timer(name: str) -> str:
    """Classify timer by workload type."""
    name_lower = name.lower()
    
    if "orchestrator" in name_lower:
        # Check for legacy orchestrator timer (no mode suffix)
        if name_lower == "chloe-orchestrator.timer":
            return "legacy_orchestrator"
        mode = name_lower.split("-")[-1].replace(".timer", "")
        return f"orchestrator_{mode}"
    
    if "policy" in name_lower and "refresh" in name_lower:
        return "policy_refresh"
    
    if "shadow" in name_lower and "exploit" in name_lower:
        return "shadow_exploit"
    
    if "hindsight" in name_lower:
        return "hindsight"
    
    if "nightly" in name_lower and "research" in name_lower:
        return "nightly_research"
    
    if "dream" in name_lower:
        return "dream"
    
    if "reflect" in name_lower:
        return "reflection"
    
    if "swarm" in name_lower or "audit" in name_lower:
        return "legacy_other"
    
    return "other"


def detect_conflicts(timers: List[Dict[str, str]]) -> List[Tuple[str, List[str]]]:
    """Detect timer conflicts (same workload class)."""
    by_class = defaultdict(list)
    
    for timer in timers:
        workload_class = classify_timer(timer["name"])
        by_class[workload_class].append(timer["name"])
    
    conflicts = []
    for workload_class, timer_names in by_class.items():
        if len(timer_names) > 1:
            conflicts.append((workload_class, timer_names))
    
    return conflicts


def check_model_a_compliance(timers: List[Dict[str, str]]) -> Tuple[bool, List[str]]:
    """
    Check Model A compliance: only fast/slow/nightly orchestrator timers should exist.
    
    Returns:
        (is_compliant, violations)
    """
    violations = []
    allowed_timers = {
        "chloe-orchestrator-fast.timer",
        "chloe-orchestrator-slow.timer",
        "chloe-orchestrator-nightly.timer",
    }
    
    for timer in timers:
        timer_name = timer["name"]
        if timer_name not in allowed_timers:
            violations.append(timer_name)
    
    return len(violations) == 0, violations


def main() -> int:
    """Main entry point."""
    print("TIMER AUDIT")
    print("=" * 80)
    print()
    
    timers = get_timers()
    
    if not timers:
        print("No chloe timers found.")
        return 0
    
    print(f"Found {len(timers)} chloe timer(s):")
    print("-" * 80)
    print(f"{'Timer Name':<50} {'Workload Class':<30}")
    print("-" * 80)
    
    for timer in timers:
        workload_class = classify_timer(timer["name"])
        print(f"{timer['name']:<50} {workload_class:<30}")
    
    print()
    
    # Check Model A compliance
    is_compliant, violations = check_model_a_compliance(timers)
    
    if not is_compliant:
        print("⚠️  MODEL A COMPLIANCE VIOLATION:")
        print("-" * 80)
        print("Legacy or non-orchestrator timers detected:")
        for violation in violations:
            print(f"  ❌ {violation}")
        print()
        print("RECOMMENDATION: Disable legacy timers. Model A requires only:")
        print("  ✅ chloe-orchestrator-fast.timer")
        print("  ✅ chloe-orchestrator-slow.timer")
        print("  ✅ chloe-orchestrator-nightly.timer")
        print()
        print("To disable a legacy timer:")
        print(f"  sudo systemctl disable --now {violations[0]}")
        print()
    else:
        print("✅ MODEL A COMPLIANT: Only orchestrator timers detected.")
        print()
    
    # Check for conflicts
    conflicts = detect_conflicts(timers)
    
    if conflicts:
        print("CONFLICTS FOUND:")
        print("-" * 80)
        for workload_class, timer_names in conflicts:
            print(f"  {workload_class}: {', '.join(timer_names)}")
        print()
        print("RECOMMENDATION: Disable overlapping timers and use orchestrator timers only.")
        print()
        return 1
    else:
        print("OK: No conflicts detected.")
        print()
    
    return 0 if is_compliant else 1


if __name__ == "__main__":
    sys.exit(main())

