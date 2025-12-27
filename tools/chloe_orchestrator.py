"""
Chloe Orchestrator (Unified Automation Spine)
----------------------------------------------

Single source of truth for all automation cadences.

Modes:
  - fast: Lightweight policy stack (every 5 minutes)
  - slow: Intraday heavy stack (hourly)
  - nightly: Full research cycle (daily)

All modes log to reports/ops/orchestrator_runs.jsonl and update
reports/ops/orchestrator_state.json.

Safety:
  - PAPER-only
  - Restrictive-only (never enables live trading)
  - No config mutation (writes reports/logs only)
  - Fail-safe: one step failure doesn't crash the whole run
"""

from __future__ import annotations

import json
import signal
import sys
import time
import traceback
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

# Ensure clean exit when stdout is closed (e.g. piping to head/grep)
signal.signal(signal.SIGPIPE, signal.SIG_DFL)
from typing import Dict, Any, List, Optional

ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "reports"
OPS_DIR = REPORTS_DIR / "ops"
RUNS_PATH = OPS_DIR / "orchestrator_runs.jsonl"
STATE_PATH = OPS_DIR / "orchestrator_state.json"

OPS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class StepResult:
    """Result of a single step execution."""
    step_name: str
    success: bool
    runtime_seconds: float
    error: Optional[str] = None
    traceback: Optional[str] = None


@dataclass
class OrchestratorRun:
    """Complete orchestrator run record."""
    ts: str
    mode: str
    steps: List[StepResult]
    total_runtime_seconds: float
    success: bool
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _log_run(run: OrchestratorRun) -> None:
    """Log orchestrator run to JSONL."""
    try:
        with RUNS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(run.to_dict()) + "\n")
    except Exception:
        pass


def _update_state(mode: str, run: OrchestratorRun) -> None:
    """Update orchestrator state file."""
    try:
        if STATE_PATH.exists():
            state = json.loads(STATE_PATH.read_text())
        else:
            state = {}
        
        state[mode] = {
            "last_run_ts": run.ts,
            "last_status": "success" if run.success else "failed",
            "last_runtime_seconds": run.total_runtime_seconds,
        }
        
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with STATE_PATH.open("w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def _run_step(step_name: str, module_path: str, function_name: str = "main", args: Optional[List[str]] = None) -> StepResult:
    """
    Run a single step and return result.
    
    Args:
        step_name: Human-readable step name
        module_path: Python module path (e.g., "tools.policy_refresh")
        function_name: Function to call (default: "main")
        args: Command-line arguments to pass (for modules that use sys.argv)
    
    Returns:
        StepResult with success status and runtime
    """
    start_time = time.time()
    error = None
    tb = None
    
    try:
        # Import module
        module = __import__(module_path, fromlist=[function_name])
        func = getattr(module, function_name)
        
        # Save original sys.argv
        original_argv = sys.argv.copy()
        
        try:
            # Set sys.argv if args provided
            if args:
                sys.argv = [module_path] + args
            else:
                sys.argv = [module_path]
            
            # Call function
            result = func()
            
            # Check if result is an exit code (int)
            if isinstance(result, int) and result != 0:
                raise RuntimeError(f"Step returned non-zero exit code: {result}")
            
            runtime = time.time() - start_time
            return StepResult(
                step_name=step_name,
                success=True,
                runtime_seconds=runtime,
            )
        finally:
            # Restore sys.argv
            sys.argv = original_argv
        
    except Exception as e:
        runtime = time.time() - start_time
        error = str(e)
        tb = traceback.format_exc()
        return StepResult(
            step_name=step_name,
            success=False,
            runtime_seconds=runtime,
            error=error,
            traceback=tb,
        )


def run_fast() -> OrchestratorRun:
    """
    Run fast cadence (lightweight policy stack).
    
    Steps:
    1. policy_refresh
    2. shadow_exploit_lane
    3. exploit_lane_gate_test
    """
    start_time = time.time()
    ts = datetime.now(timezone.utc).isoformat()
    
    # Phase 5H.4: Count total steps dynamically
    # We'll build the step list and use its length for display
    steps: List[StepResult] = []
    
    # Phase 5H.4: Track step number dynamically
    step_num = 0
    
    def _print_step(step_name: str, total_steps: int) -> None:
        """Print step with dynamic step number."""
        nonlocal step_num
        step_num += 1
        print(f"  [{step_num}/{total_steps}] Running {step_name}...")
    
    # Estimate total steps (will be updated as we go)
    # FAST mode has: policy_refresh, syntax_check, probe_lane_gate, probe_lane, promotion_gate,
    # shadow_exploit_lane, shadow_exploit_scorer, quarantine, recovery_ramp, recovery_lane,
    # recovery_ramp_v2, recovery_lane_v2, recovery_assist, micro_core_ramp, exploit_arming,
    # exploit_lane_runner, exploit_micro_lane, exploit_lane_gate_test = 18 steps
    ESTIMATED_TOTAL_STEPS = 18
    
    print(f"[orchestrator {ts}] Starting FAST mode...")
    
    # Step 1: Policy refresh
    _print_step("policy_refresh", ESTIMATED_TOTAL_STEPS)
    result = _run_step("policy_refresh", "tools.policy_refresh", "run_policy_refresh")
    steps.append(result)
    if result.success:
        print(f"  ✓ policy_refresh completed ({result.runtime_seconds:.2f}s)")
    else:
        print(f"  ✗ policy_refresh failed: {result.error}")
    
    # Step 1.5: Exploit stack syntax check (guardrail)
    _print_step("exploit_stack_syntax_check", ESTIMATED_TOTAL_STEPS)
    try:
        from tools.run_exploit_stack_syntax_check import check_syntax
        import time as time_module
        check_start_time = time_module.time()
        all_passed, errors = check_syntax()
        check_runtime = time_module.time() - check_start_time
        
        if all_passed:
            print(f"  ✓ exploit_stack_syntax_check: PASS ({check_runtime:.2f}s)")
            exploit_stack_healthy = True
        else:
            print(f"  ⚠️  WARN: exploit_stack_syntax_check: FAIL ({check_runtime:.2f}s)")
            for rel_path, error_msg in errors:
                print(f"     ✗ {rel_path}: {error_msg[:100]}")
            exploit_stack_healthy = False
            
            # Write health status
            try:
                from engine_alpha.core.paths import REPORTS
                health_path = REPORTS / "ops" / "exploit_stack_health.json"
                health_path.parent.mkdir(parents=True, exist_ok=True)
                import json
                health_data = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "healthy": False,
                    "errors": [{"file": rel_path, "error": error_msg} for rel_path, error_msg in errors],
                }
                with health_path.open("w", encoding="utf-8") as f:
                    json.dump(health_data, f, indent=2)
                print(f"     Health status written to: {health_path}")
            except Exception:
                pass
        
        steps.append(StepResult(
            step_name="exploit_stack_syntax_check",
            success=True,  # Non-fatal, just a warning
            runtime_seconds=check_runtime,
            error=None,
        ))
    except Exception as e:
        print(f"  ✗ exploit_stack_syntax_check failed: {str(e)}")
        exploit_stack_healthy = False
        steps.append(StepResult(
            step_name="exploit_stack_syntax_check",
            success=False,
            runtime_seconds=0.0,
            error=str(e),
        ))
    
    # Step 1.6: Probe lane gate (evaluate auto-enablement)
    _print_step("probe_lane_gate", ESTIMATED_TOTAL_STEPS)
    try:
        from engine_alpha.loop.probe_lane_gate import evaluate_probe_lane_enablement
        gate_start_time = time.time()
        gate_result = evaluate_probe_lane_enablement()
        gate_runtime = time.time() - gate_start_time
        
        decision = gate_result.get("decision", "unknown")
        reason = gate_result.get("reason", "")
        enabled = gate_result.get("enabled", False)
        
        if enabled:
            print(f"  ✓ probe_lane_gate: ENABLED ({reason}) ({gate_runtime:.2f}s)")
        else:
            print(f"  • probe_lane_gate: {decision.upper()} ({reason}) ({gate_runtime:.2f}s)")
        
        steps.append(StepResult(
            step_name="probe_lane_gate",
            success=True,
            runtime_seconds=gate_runtime,
            error=None,
        ))
    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        print(f"  ✗ probe_lane_gate failed: {str(e)}")
        steps.append(StepResult(
            step_name="probe_lane_gate",
            success=False,
            runtime_seconds=0.0,
            error=str(e),
        ))
    
    # Step 1.6: Probe lane (micro-live exploration during halt)
    _print_step("probe_lane", ESTIMATED_TOTAL_STEPS)
    try:
        from engine_alpha.loop.probe_lane import run_probe_lane
        probe_start_time = time.time()
        probe_result = run_probe_lane()
        probe_runtime = time.time() - probe_start_time
        
        # Log probe result
        action = probe_result.get("action", "unknown")
        reason = probe_result.get("reason", "")
        if action == "opened":
            print(f"  ✓ probe_lane opened: {probe_result.get('selected_symbol', '?')} ({probe_runtime:.2f}s)")
        elif action == "blocked":
            print(f"  ⚠ probe_lane blocked: {reason} ({probe_runtime:.2f}s)")
        else:
            print(f"  • probe_lane: {action} ({probe_runtime:.2f}s)")
        
        steps.append(StepResult(
            step_name="probe_lane",
            success=True,
            runtime_seconds=probe_runtime,
            error=None,
        ))
    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        # Log to error file
        try:
            from engine_alpha.core.paths import REPORTS
            error_path = REPORTS / "loop" / "probe_lane_errors.jsonl"
            error_path.parent.mkdir(parents=True, exist_ok=True)
            import json
            error_data = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "error_type": type(e).__name__,
                "error_message": str(e),
                "traceback": error_traceback,
                "context": "orchestrator_probe_lane",
            }
            with error_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(error_data) + "\n")
        except Exception:
            pass
        
        print(f"  ✗ probe_lane failed: {str(e)}")
        steps.append(StepResult(
            step_name="probe_lane",
            success=False,
            runtime_seconds=0.0,
            error=str(e),
        ))
    
    # Step 1.7: Promotion gate (Probe → Exploit promotion)
    _print_step("promotion_gate", ESTIMATED_TOTAL_STEPS)
    try:
        from engine_alpha.loop.promotion_gate import evaluate_promotion_gate
        promotion_start_time = time.time()
        promotion_result = evaluate_promotion_gate()
        promotion_runtime = time.time() - promotion_start_time
        
        mode = promotion_result.get("mode", "DISABLED")
        decision = promotion_result.get("decision", "hold")
        reason = promotion_result.get("reason", "")
        
        if mode == "EXPLOIT_ENABLED":
            print(f"  ✓ promotion_gate: EXPLOIT_ENABLED ({reason}) ({promotion_runtime:.2f}s)")
        elif mode == "PROBE_ONLY":
            print(f"  • promotion_gate: PROBE_ONLY ({reason}) ({promotion_runtime:.2f}s)")
        else:
            print(f"  • promotion_gate: DISABLED ({reason}) ({promotion_runtime:.2f}s)")
        
        steps.append(StepResult(
            step_name="promotion_gate",
            success=True,
            runtime_seconds=promotion_runtime,
            error=None,
        ))
    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        print(f"  ✗ promotion_gate failed: {str(e)}")
        steps.append(StepResult(
            step_name="promotion_gate",
            success=False,
            runtime_seconds=0.0,
            error=str(e),
        ))
    
    # Step 1.8: Model A compliance check (non-fatal)
    try:
        from tools.run_model_a_compliance import check_compliance
        import json
        from pathlib import Path
        
        is_compliant, allowed, forbidden = check_compliance()
        if not is_compliant:
            print(f"  ⚠️  WARN: Model A compliance violation detected")
            print(f"     Forbidden timers: {', '.join(forbidden)}")
            
            # Write warning file
            ops_dir = Path("reports/ops")
            ops_dir.mkdir(parents=True, exist_ok=True)
            warning_path = ops_dir / "model_a_warnings.json"
            warning_data = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "compliant": False,
                "forbidden_timers": forbidden,
                "allowed_timers": allowed,
            }
            with warning_path.open("w", encoding="utf-8") as f:
                json.dump(warning_data, f, indent=2)
            print(f"     Warning written to: {warning_path}")
    except Exception as e:
        # Non-fatal - don't break orchestrator if compliance check fails
        pass
    
    # Step 6: Shadow exploit lane (evaluates ALL eligible symbols and emits events)
    _print_step("shadow_exploit_lane", ESTIMATED_TOTAL_STEPS)
    result = _run_step("shadow_exploit_lane", "tools.run_shadow_exploit_lane", "main")
    steps.append(result)
    if result.success:
        print(f"  ✓ shadow_exploit_lane completed ({result.runtime_seconds:.2f}s)")
    else:
        print(f"  ✗ shadow_exploit_lane failed: {result.error}")
    
    # Step 7: Shadow exploit scorer (Phase 5b)
    _print_step("shadow_exploit_scorer", ESTIMATED_TOTAL_STEPS)
    result = _run_step("shadow_exploit_scorer", "tools.run_shadow_exploit_score", "main")
    steps.append(result)
    if result.success:
        print(f"  ✓ shadow_exploit_scorer completed ({result.runtime_seconds:.2f}s)")
    else:
        print(f"  ✗ shadow_exploit_scorer failed: {result.error}")
    
    # Step 8: Quarantine builder (Phase 5g) - must run before exploit_arming
    _print_step("quarantine", ESTIMATED_TOTAL_STEPS)
    result = _run_step("quarantine", "tools.run_quarantine", "main")
    steps.append(result)
    if result.success:
        print(f"  ✓ quarantine completed ({result.runtime_seconds:.2f}s)")
    else:
        print(f"  ✗ quarantine failed: {result.error}")
    
    # Step 9: Recovery ramp (Phase 5H) - evaluates recovery conditions
    _print_step("recovery_ramp", ESTIMATED_TOTAL_STEPS)
    result = _run_step("recovery_ramp", "tools.run_recovery_ramp", "main")
    steps.append(result)
    if result.success:
        print(f"  ✓ recovery_ramp completed ({result.runtime_seconds:.2f}s)")
    else:
        print(f"  ✗ recovery_ramp failed: {result.error}")
    
    # Step 10: Recovery lane (Phase 5H) - micro-trading during recovery
    _print_step("recovery_lane", ESTIMATED_TOTAL_STEPS)
    result = _run_step("recovery_lane", "tools.run_recovery_lane", "main")
    steps.append(result)
    if result.success:
        print(f"  ✓ recovery_lane completed ({result.runtime_seconds:.2f}s)")
    else:
        print(f"  ✗ recovery_lane failed: {result.error}")
    
    # Step 11: Recovery ramp v2 (Phase 5H.2) - per-symbol recovery ramp
    _print_step("recovery_ramp_v2", ESTIMATED_TOTAL_STEPS)
    result = _run_step("recovery_ramp_v2", "tools.run_recovery_ramp_v2", "main")
    steps.append(result)
    if result.success:
        print(f"  ✓ recovery_ramp_v2 completed ({result.runtime_seconds:.2f}s)")
    else:
        print(f"  ✗ recovery_ramp_v2 failed: {result.error}")
    
    # Step 12: Recovery lane v2 (Phase 5H.2) - per-symbol micro recovery
    _print_step("recovery_lane_v2", ESTIMATED_TOTAL_STEPS)
    result = _run_step("recovery_lane_v2", "tools.run_recovery_lane_v2", "main")
    steps.append(result)
    if result.success:
        print(f"  ✓ recovery_lane_v2 completed ({result.runtime_seconds:.2f}s)")
    else:
        print(f"  ✗ recovery_lane_v2 failed: {result.error}")
    
    # Step 12.5: Recovery lane v2 status (optional, non-fatal)
    try:
        from tools.run_recovery_lane_v2_status import main as status_main
        status_start_time = time.time()
        status_main()
        status_runtime = time.time() - status_start_time
        # Non-fatal - just prints status, don't add to steps
    except Exception:
        pass  # Ignore errors in status tool
    
    # Step 13: Recovery assist (Phase 5H.4) - evaluates recovery assist conditions
    _print_step("recovery_assist", ESTIMATED_TOTAL_STEPS)
    try:
        import sys
        sys.path.insert(0, str(ROOT))
        from engine_alpha.risk.recovery_assist import evaluate_recovery_assist
        assist_start_time = time.time()
        assist_result = evaluate_recovery_assist()
        assist_runtime = time.time() - assist_start_time
        
        assist_enabled = assist_result.get("assist_enabled", False)
        reason = assist_result.get("reason", "")
        
        if assist_enabled:
            print(f"  ✓ recovery_assist: ENABLED ({reason}) ({assist_runtime:.2f}s)")
        else:
            print(f"  • recovery_assist: DISABLED ({reason}) ({assist_runtime:.2f}s)")
        
        steps.append(StepResult(
            step_name="recovery_assist",
            success=True,
            runtime_seconds=assist_runtime,
            error=None,
        ))
    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        print(f"  ✗ recovery_assist failed: {str(e)}")
        steps.append(StepResult(
            step_name="recovery_assist",
            success=False,
            runtime_seconds=0.0,
            error=str(e),
        ))
    
    # Step 14: Micro core ramp (Phase 5H.4) - micro-core trading during halt when assist enabled
    _print_step("micro_core_ramp", ESTIMATED_TOTAL_STEPS)
    try:
        import sys
        sys.path.insert(0, str(ROOT))
        from engine_alpha.loop.micro_core_ramp import run_micro_core_ramp
        ramp_start_time = time.time()
        ramp_result = run_micro_core_ramp()
        ramp_runtime = time.time() - ramp_start_time
        
        action = ramp_result.get("action", "unknown")
        reason = ramp_result.get("reason", "")
        symbol = ramp_result.get("symbol", "")
        
        if action == "opened":
            print(f"  ✓ micro_core_ramp opened: {symbol} ({ramp_runtime:.2f}s)")
        elif action == "closed":
            print(f"  ✓ micro_core_ramp closed: {symbol} ({reason}) ({ramp_runtime:.2f}s)")
        else:
            print(f"  • micro_core_ramp: {action} ({reason}) ({ramp_runtime:.2f}s)")
        
        steps.append(StepResult(
            step_name="micro_core_ramp",
            success=True,
            runtime_seconds=ramp_runtime,
            error=None,
        ))
    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        print(f"  ✗ micro_core_ramp failed: {str(e)}")
        steps.append(StepResult(
            step_name="micro_core_ramp",
            success=False,
            runtime_seconds=0.0,
            error=str(e),
        ))
    
    # Step 15: Exploit arming (Phase 5d) - must run before exploit_lane_runner
    _print_step("exploit_arming", ESTIMATED_TOTAL_STEPS)
    result = _run_step("exploit_arming", "tools.run_exploit_arming", "main")
    steps.append(result)
    if result.success:
        print(f"  ✓ exploit_arming completed ({result.runtime_seconds:.2f}s)")
    else:
        print(f"  ✗ exploit_arming failed: {result.error}")
    
    # Skip exploit execution steps if syntax check failed
    if not exploit_stack_healthy:
        print("  ⚠️  SKIP: exploit_lane_runner (syntax check failed)")
        print("  ⚠️  SKIP: exploit_micro_lane (syntax check failed)")
        steps.append(StepResult(
            step_name="exploit_lane_runner",
            success=False,
            runtime_seconds=0.0,
            error="skipped_due_to_syntax_error",
        ))
        steps.append(StepResult(
            step_name="exploit_micro_lane",
            success=False,
            runtime_seconds=0.0,
            error="skipped_due_to_syntax_error",
        ))
    else:
        # Step 16: Exploit lane runner (micro-paper exploit) - Phase 5c
        _print_step("exploit_lane_runner", ESTIMATED_TOTAL_STEPS)
        result = _run_step("exploit_lane_runner", "tools.run_exploit_lane_runner", "main")
        steps.append(result)
        if result.success:
            print(f"  ✓ exploit_lane_runner completed ({result.runtime_seconds:.2f}s)")
        else:
            print(f"  ✗ exploit_lane_runner failed: {result.error}")
        
        # Step 17: Exploit micro lane (legacy, kept for compatibility)
        _print_step("exploit_micro_lane", ESTIMATED_TOTAL_STEPS)
        result = _run_step("exploit_micro_lane", "tools.run_exploit_micro_lane", "main")
        steps.append(result)
        if result.success:
            print(f"  ✓ exploit_micro_lane completed ({result.runtime_seconds:.2f}s)")
        else:
            print(f"  ✗ exploit_micro_lane failed: {result.error}")
    
    # Step 18: Exploit lane gate test (always runs, diagnostic only)
    _print_step("exploit_lane_gate_test", ESTIMATED_TOTAL_STEPS)
    result = _run_step("exploit_lane_gate_test", "tools.run_exploit_lane_gate_test", "main")
    steps.append(result)
    if result.success:
        print(f"  ✓ exploit_lane_gate_test completed ({result.runtime_seconds:.2f}s)")
    else:
        print(f"  ✗ exploit_lane_gate_test failed: {result.error}")
    
    total_runtime = time.time() - start_time
    success = all(s.success for s in steps)
    
    run = OrchestratorRun(
        ts=ts,
        mode="fast",
        steps=steps,
        total_runtime_seconds=total_runtime,
        success=success,
    )
    
    _log_run(run)
    _update_state("fast", run)
    
    print(f"[orchestrator] FAST mode complete: {len([s for s in steps if s.success])}/{len(steps)} steps succeeded ({total_runtime:.2f}s)")
    
    return run


def run_slow() -> OrchestratorRun:
    """
    Run slow cadence (intraday heavy stack).
    
    Steps:
    1. drift_scan
    2. execution_quality_scan
    3. policy_refresh (to absorb updates)
    """
    start_time = time.time()
    ts = datetime.now(timezone.utc).isoformat()
    
    print(f"[orchestrator {ts}] Starting SLOW mode...")
    
    steps: List[StepResult] = []
    
    # Step 1: Drift scan
    print("  [1/3] Running drift_scan...")
    result = _run_step("drift_scan", "tools.run_drift_scan", "main")
    steps.append(result)
    if result.success:
        print(f"  ✓ drift_scan completed ({result.runtime_seconds:.2f}s)")
    else:
        print(f"  ✗ drift_scan failed: {result.error}")
    
    # Step 2: Execution quality scan
    print("  [2/3] Running execution_quality_scan...")
    result = _run_step("execution_quality_scan", "tools.run_execution_quality_scan", "main")
    steps.append(result)
    if result.success:
        print(f"  ✓ execution_quality_scan completed ({result.runtime_seconds:.2f}s)")
    else:
        print(f"  ✗ execution_quality_scan failed: {result.error}")
    
    # Step 3: Policy refresh (to absorb drift/exec updates)
    print("  [3/3] Running policy_refresh...")
    result = _run_step("policy_refresh", "tools.policy_refresh", "run_policy_refresh")
    steps.append(result)
    if result.success:
        print(f"  ✓ policy_refresh completed ({result.runtime_seconds:.2f}s)")
    else:
        print(f"  ✗ policy_refresh failed: {result.error}")
    
    total_runtime = time.time() - start_time
    success = all(s.success for s in steps)
    
    run = OrchestratorRun(
        ts=ts,
        mode="slow",
        steps=steps,
        total_runtime_seconds=total_runtime,
        success=success,
    )
    
    _log_run(run)
    _update_state("slow", run)
    
    print(f"[orchestrator] SLOW mode complete: {len([s for s in steps if s.success])}/{len(steps)} steps succeeded ({total_runtime:.2f}s)")
    
    return run


def run_nightly() -> OrchestratorRun:
    """
    Run nightly cadence (full research cycle).
    
    Steps:
    1. nightly_research_cycle
    2. hindsight_cycle full
    3. shadow_exploit_scorer
    4. shadow_promotion_gate
    5. quarantine (Phase 5g)
    6. thaw_audit
    7. exploit_param_mutator (proposal-only)
    """
    start_time = time.time()
    ts = datetime.now(timezone.utc).isoformat()
    
    print(f"[orchestrator {ts}] Starting NIGHTLY mode...")
    
    steps: List[StepResult] = []
    
    # Step 1: Nightly research cycle
    print("  [1/7] Running nightly_research_cycle...")
    result = _run_step("nightly_research_cycle", "tools.nightly_research_cycle", "main")
    steps.append(result)
    if result.success:
        print(f"  ✓ nightly_research_cycle completed ({result.runtime_seconds:.2f}s)")
    else:
        print(f"  ✗ nightly_research_cycle failed: {result.error}")
    
    # Step 2: Hindsight cycle (full)
    print("  [2/7] Running hindsight_cycle (full)...")
    # hindsight_cycle.main() takes mode as command-line arg
    result = _run_step("hindsight_cycle", "tools.hindsight_cycle", "main", args=["full"])
    steps.append(result)
    if result.success:
        print(f"  ✓ hindsight_cycle completed ({result.runtime_seconds:.2f}s)")
    else:
        print(f"  ✗ hindsight_cycle failed: {result.error}")
    
    # Step 3: Shadow exploit scorer (Phase 5b)
    print("  [3/7] Running shadow_exploit_scorer...")
    result = _run_step("shadow_exploit_scorer", "tools.run_shadow_exploit_score", "main")
    steps.append(result)
    if result.success:
        print(f"  ✓ shadow_exploit_scorer completed ({result.runtime_seconds:.2f}s)")
    else:
        print(f"  ✗ shadow_exploit_scorer failed: {result.error}")
    
    # Step 4: Shadow promotion gate (Phase 5b)
    print("  [4/7] Running shadow_promotion_gate...")
    result = _run_step("shadow_promotion_gate", "tools.run_shadow_promotion_gate", "main")
    steps.append(result)
    if result.success:
        print(f"  ✓ shadow_promotion_gate completed ({result.runtime_seconds:.2f}s)")
    else:
        print(f"  ✗ shadow_promotion_gate failed: {result.error}")
    
    # Step 5: Quarantine (Phase 5g) - after nightly research
    print("  [5/7] Running quarantine...")
    result = _run_step("quarantine", "tools.run_quarantine", "main")
    steps.append(result)
    if result.success:
        print(f"  ✓ quarantine completed ({result.runtime_seconds:.2f}s)")
    else:
        print(f"  ✗ quarantine failed: {result.error}")
    
    # Step 6: Thaw audit
    print("  [6/7] Running thaw_audit...")
    result = _run_step("thaw_audit", "tools.thaw_audit", "main")
    steps.append(result)
    if result.success:
        print(f"  ✓ thaw_audit completed ({result.runtime_seconds:.2f}s)")
    else:
        print(f"  ✗ thaw_audit failed: {result.error}")
    
    # Step 7: Exploit parameter mutator (proposal-only)
    print("  [7/7] Running exploit_param_mutator...")
    try:
        from engine_alpha.evolve.exploit_param_mutator import generate_proposals
        import time as time_module
        start_time = time_module.time()
        generate_proposals()
        runtime = time_module.time() - start_time
        result = StepResult(
            step_name="exploit_param_mutator",
            success=True,
            runtime_seconds=runtime,
            error=None,
        )
    except Exception as e:
        result = StepResult(
            step_name="exploit_param_mutator",
            success=False,
            runtime_seconds=0.0,
            error=str(e),
        )
    steps.append(result)
    if result.success:
        print(f"  ✓ exploit_param_mutator completed ({result.runtime_seconds:.2f}s)")
    else:
        print(f"  ✗ exploit_param_mutator failed: {result.error}")
    
    total_runtime = time.time() - start_time
    success = all(s.success for s in steps)
    
    run = OrchestratorRun(
        ts=ts,
        mode="nightly",
        steps=steps,
        total_runtime_seconds=total_runtime,
        success=success,
    )
    
    _log_run(run)
    _update_state("nightly", run)
    
    print(f"[orchestrator] NIGHTLY mode complete: {len([s for s in steps if s.success])}/{len(steps)} steps succeeded ({total_runtime:.2f}s)")
    
    return run


def run_policy_refresh_only() -> OrchestratorRun:
    """
    Run policy refresh only (lightweight mode).
    
    This is an alias mode that just runs policy_refresh step.
    """
    start_time = time.time()
    ts = datetime.now(timezone.utc).isoformat()
    steps: List[StepResult] = []
    
    print(f"[orchestrator {ts}] Starting POLICY_REFRESH mode...")
    
    # Step 1: Policy refresh
    print(f"  [1/1] Running policy_refresh...")
    result = _run_step("policy_refresh", "tools.policy_refresh", "run_policy_refresh")
    steps.append(result)
    if result.success:
        print(f"  ✓ policy_refresh completed ({result.runtime_seconds:.2f}s)")
    else:
        print(f"  ✗ policy_refresh failed: {result.error}")
    
    total_runtime = time.time() - start_time
    run = OrchestratorRun(
        ts=ts,
        mode="policy_refresh",
        steps=steps,
        total_runtime_seconds=total_runtime,
        success=all(s.success for s in steps),
    )
    
    _log_run(run)
    _update_state("policy_refresh", run)
    
    print(f"[orchestrator] POLICY_REFRESH mode complete: {len([s for s in steps if s.success])}/{len(steps)} steps succeeded ({total_runtime:.2f}s)")
    
    return run


def main() -> int:
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python3 -m tools.chloe_orchestrator <mode>")
        print("Modes: fast, slow, nightly, policy_refresh")
        return 1
    
    mode = sys.argv[1].lower()
    
    if mode == "fast":
        run = run_fast()
    elif mode == "slow":
        run = run_slow()
    elif mode == "nightly":
        run = run_nightly()
    elif mode == "policy_refresh":
        run = run_policy_refresh_only()
    else:
        print(f"ERROR: Unknown mode '{mode}'. Use: fast, slow, nightly, policy_refresh")
        return 1
    
    return 0 if run.success else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.exit(0)

