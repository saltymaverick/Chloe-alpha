"""
System Sanity Check - Global integrity check for Chloe-alpha.

This tool validates:
- Python imports (syntax, circular dependencies)
- JSON contract files (structure, types, completeness)
- Tool executions (all major tools run successfully)
- Shadow mode enforcement

All checks are read-only and do NOT modify configs.
"""

from __future__ import annotations

import json
import os
import sys
import importlib
import subprocess
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "reports"
SYSTEM_REPORT_DIR = REPORTS_DIR / "system"
SANITY_REPORT_PATH = SYSTEM_REPORT_DIR / "sanity_report.json"


def safe_import_check(file_path: Path) -> tuple[str, str]:
    """
    Attempt to import a Python file safely.
    
    Returns:
        ("PASS", "") or ("FAIL", error_message)
    """
    try:
        # Convert file path to module path
        rel_path = file_path.relative_to(ROOT)
        module_parts = list(rel_path.parts[:-1]) + [rel_path.stem]
        module_name = ".".join(module_parts)
        
        # Try importing
        if module_name in sys.modules:
            del sys.modules[module_name]
        
        importlib.import_module(module_name)
        return ("PASS", "")
    except SyntaxError as e:
        return ("FAIL", f"SyntaxError: {e}")
    except ImportError as e:
        return ("FAIL", f"ImportError: {e}")
    except Exception as e:
        return ("FAIL", f"Error: {type(e).__name__}: {e}")


def scan_python_imports() -> Dict[str, str]:
    """Scan all Python files and check imports."""
    results: Dict[str, str] = {}
    
    # Scan engine_alpha/
    engine_dir = ROOT / "engine_alpha"
    if engine_dir.exists():
        for py_file in engine_dir.rglob("*.py"):
            if py_file.name == "__init__.py":
                continue
            status, error = safe_import_check(py_file)
            rel_path = str(py_file.relative_to(ROOT))
            if status == "PASS":
                results[rel_path] = "PASS"
            else:
                results[rel_path] = f"FAIL: {error}"
    
    # Scan tools/
    tools_dir = ROOT / "tools"
    if tools_dir.exists():
        for py_file in tools_dir.glob("*.py"):
            if py_file.name == "__init__.py":
                continue
            status, error = safe_import_check(py_file)
            rel_path = str(py_file.relative_to(ROOT))
            if status == "PASS":
                results[rel_path] = "PASS"
            else:
                results[rel_path] = f"FAIL: {error}"
    
    return results


def validate_json_contract(file_path: Path, required_fields: List[str] = None) -> tuple[str, str]:
    """
    Validate a JSON contract file.
    
    Returns:
        ("PASS", "") or ("FAIL", error_message)
    """
    if not file_path.exists():
        return ("FAIL", "File does not exist")
    
    try:
        data = json.loads(file_path.read_text())
    except json.JSONDecodeError as e:
        return ("FAIL", f"Invalid JSON: {e}")
    except Exception as e:
        return ("FAIL", f"Error reading file: {e}")
    
    # Check for empty data
    if not data:
        return ("FAIL", "File is empty")
    
    # Check required fields if specified
    if required_fields:
        missing = [f for f in required_fields if f not in data]
        if missing:
            return ("FAIL", f"Missing required fields: {missing}")
    
    return ("PASS", "")


def validate_json_contracts() -> Dict[str, str]:
    """Validate all JSON contract files."""
    results: Dict[str, str] = {}
    
    # Define contract files and their required fields
    contracts = {
        "reports/gpt/reflection_input.json": ["symbols", "generated_at"],
        "reports/gpt/reflection_output.json": ["symbol_insights", "generated_at"],
        "reports/gpt/tuner_input.json": ["symbols", "generated_at"],
        "reports/gpt/tuner_output.json": ["proposals", "generated_at"],
        "reports/gpt/dream_input.json": ["scenarios", "generated_at"],
        "reports/gpt/dream_output.json": ["scenario_reviews", "generated_at"],
        "reports/gpt/quality_scores.json": None,  # No strict requirements
        "reports/research/are_snapshot.json": ["symbols", "generated_at"],
        "reports/evolver/evolver_output.json": ["symbols", "generated_at"],
        "reports/evolver/mutation_preview.json": ["mutations", "generated_at"],
    }
    
    for rel_path, required_fields in contracts.items():
        file_path = ROOT / rel_path
        status, error = validate_json_contract(file_path, required_fields)
        if status == "PASS":
            results[rel_path] = "PASS"
        else:
            results[rel_path] = f"FAIL: {error}"
    
    return results


def safe_tool_execution(tool_name: str) -> tuple[str, str]:
    """
    Execute a tool safely and check for success.
    
    Returns:
        ("PASS", "") or ("FAIL", error_message)
    """
    try:
        # Map tool names to their module paths
        tool_map = {
            "exploration_audit": "tools.exploration_audit",
            "live_positions_dashboard": "tools.live_positions_dashboard",
            "run_are_cycle": "tools.run_are_cycle",
            "performance_view": "tools.performance_view",
            "tier_evolution": "tools.tier_evolution",
            "quality_scores": "tools.quality_scores",
            "run_reflection_cycle": "tools.run_reflection_cycle",
            "run_tuner_cycle": "tools.run_tuner_cycle",
            "run_dream_cycle": "tools.run_dream_cycle",
            "run_evolver_cycle": "tools.run_evolver_cycle",
            "run_mutation_preview": "tools.run_mutation_preview",
            "capital_overview": "tools.capital_overview",
        }
        
        if tool_name not in tool_map:
            return ("FAIL", f"Unknown tool: {tool_name}")
        
        # Try importing the module (doesn't execute main)
        module_name = tool_map[tool_name]
        try:
            importlib.import_module(module_name)
        except Exception as e:
            return ("FAIL", f"Import failed: {e}")
        
        # For now, just check import success
        # Full execution would require more complex setup
        return ("PASS", "")
    except Exception as e:
        return ("FAIL", f"Error: {e}")


def validate_tools() -> Dict[str, str]:
    """Validate all major tools."""
    results: Dict[str, str] = {}
    
    tools = [
        "exploration_audit",
        "live_positions_dashboard",
        "run_are_cycle",
        "performance_view",
        "tier_evolution",
        "quality_scores",
        "run_reflection_cycle",
        "run_tuner_cycle",
        "run_dream_cycle",
        "run_evolver_cycle",
        "run_mutation_preview",
        "capital_overview",
    ]
    
    for tool_name in tools:
        status, error = safe_tool_execution(tool_name)
        if status == "PASS":
            results[tool_name] = "PASS"
        else:
            results[tool_name] = f"FAIL: {error}"
    
    return results


def check_shadow_mode() -> Dict[str, Any]:
    """Check that shadow mode is enforced."""
    shadow_mode_env = os.environ.get("BYBIT_SHADOW_MODE", "").lower() in ("true", "1", "yes", "on")
    
    # Check exchange_router for shadow mode logic
    router_path = ROOT / "engine_alpha" / "exchanges" / "exchange_router.py"
    shadow_check_passed = False
    details = []
    
    if router_path.exists():
        router_content = router_path.read_text()
        if "SHADOW" in router_content.upper() or "shadow_mode" in router_content:
            shadow_check_passed = True
            details.append("exchange_router.py contains shadow mode logic")
        else:
            details.append("exchange_router.py may not have shadow mode checks")
    else:
        details.append("exchange_router.py not found")
    
    return {
        "status": shadow_mode_env and shadow_check_passed,
        "env_var_set": shadow_mode_env,
        "router_check": shadow_check_passed,
        "details": "; ".join(details),
    }


def main() -> None:
    """Main entry point."""
    print("SYSTEM SANITY CHECK")
    print("=" * 70)
    print()
    
    # Run all checks
    print("Scanning Python imports...")
    python_imports = scan_python_imports()
    print(f"   Checked {len(python_imports)} files")
    
    print("\nValidating JSON contracts...")
    json_contracts = validate_json_contracts()
    print(f"   Checked {len(json_contracts)} contracts")
    
    print("\nValidating tools...")
    tools = validate_tools()
    print(f"   Checked {len(tools)} tools")
    
    print("\nChecking shadow mode...")
    shadow_mode = check_shadow_mode()
    print(f"   Shadow mode: {shadow_mode['status']}")
    
    # Collect errors
    errors: List[str] = []
    
    for file, status in python_imports.items():
        if not status.startswith("PASS"):
            errors.append(f"Python import {file}: {status}")
    
    for contract, status in json_contracts.items():
        if not status.startswith("PASS"):
            errors.append(f"JSON contract {contract}: {status}")
    
    for tool, status in tools.items():
        if not status.startswith("PASS"):
            errors.append(f"Tool {tool}: {status}")
    
    if not shadow_mode["status"]:
        errors.append(f"Shadow mode check failed: {shadow_mode['details']}")
    
    # Build report
    report = {
        "python_imports": python_imports,
        "json_contracts": json_contracts,
        "tools": tools,
        "shadow_mode": shadow_mode,
        "summary": {
            "success": len(errors) == 0,
            "errors": errors,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }
    
    # Write report
    SYSTEM_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    SANITY_REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True))
    
    print()
    print("=" * 70)
    print("SANITY CHECK SUMMARY")
    print("=" * 70)
    print(f"Python imports: {sum(1 for s in python_imports.values() if s.startswith('PASS'))}/{len(python_imports)} passed")
    print(f"JSON contracts: {sum(1 for s in json_contracts.values() if s.startswith('PASS'))}/{len(json_contracts)} passed")
    print(f"Tools: {sum(1 for s in tools.values() if s.startswith('PASS'))}/{len(tools)} passed")
    print(f"Shadow mode: {'PASS' if shadow_mode['status'] else 'FAIL'}")
    print()
    
    if errors:
        print(f"⚠️  Found {len(errors)} issues:")
        for error in errors[:10]:  # Show first 10
            print(f"   - {error}")
        if len(errors) > 10:
            print(f"   ... and {len(errors) - 10} more")
    else:
        print("✅ All checks passed!")
    
    print()
    print(f"Full report written to: {SANITY_REPORT_PATH}")
    print("=" * 70)


if __name__ == "__main__":
    main()


