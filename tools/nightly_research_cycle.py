"""
Nightly Research Cycle - Phase 4
Runs all research/intelligence passes in sequence.

This orchestrates:
- ARE
- Reflection (v4-aware: uses tools.run_reflection_cycle.main())
- Tuner (v4-aware: uses tools.run_tuner_cycle.main())
- Dream
- Quality Scores
- Evolver
- Mutation Preview
- Memory Snapshot
- Meta-Reasoner
- Capital Overview (advisory)

All steps are wrapped in try/except to prevent one failure from crashing the cycle.

IMPORTANT: Reflection and Tuner steps call the v4-aware CLI tools which respect:
- USE_GPT_REFLECTION_V4, USE_GPT_TUNER_V4 (enable v4)
- FORCE_GPT_REFLECTION_V4, FORCE_GPT_TUNER_V4 (force v4, no fallback)
- USE_GPT_REFLECTION_V2, USE_GPT_TUNER_V2 (enable v2/v3 file-based prompts)

Set these environment variables before running to control GPT version selection.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List

ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "reports"
PIPELINE_DIR = REPORTS_DIR / "pipeline"
RESEARCH_SUMMARY_PATH = PIPELINE_DIR / "nightly_research_summary.json"


def run_step(step_name: str, module_name: str, function_name: str = "main", **kwargs) -> Dict[str, Any]:
    """
    Run a research step and return status.
    
    Args:
        step_name: Human-readable step name
        module_name: Python module path (e.g., "tools.run_are_cycle")
        function_name: Function to call (default: "main")
        **kwargs: Additional arguments to pass to the function
    
    Returns:
        Dict with "name", "status" ("OK" or "FAIL"), and optional "error"
    """
    try:
        # Import module
        module = __import__(module_name, fromlist=[function_name])
        func = getattr(module, function_name)
        
        # Call function with kwargs if provided
        if kwargs:
            result = func(**kwargs)
        else:
            result = func()
        
        # If function returns an int, treat 0 as success
        if isinstance(result, int):
            if result == 0:
                return {"name": step_name, "status": "OK"}
            else:
                return {"name": step_name, "status": "FAIL", "error": f"Returned exit code {result}"}
        
        # Otherwise assume success if no exception
        return {"name": step_name, "status": "OK"}
    
    except ImportError as e:
        return {"name": step_name, "status": "FAIL", "error": f"ImportError: {e}"}
    except AttributeError as e:
        return {"name": step_name, "status": "FAIL", "error": f"AttributeError: {e}"}
    except Exception as e:
        return {"name": step_name, "status": "FAIL", "error": f"{type(e).__name__}: {e}"}


def main() -> None:
    """Run all research steps and write summary."""
    print("NIGHTLY RESEARCH CYCLE")
    print("=" * 70)
    print()
    
    steps: List[Dict[str, Any]] = []
    notes: List[str] = []
    
    # Define all research steps
    # Phase 5 scans run early so Reflection/Tuner can use the data
    # NOTE: Reflection and Tuner steps call the v4-aware tools (tools.run_reflection_cycle.main()
    #       and tools.run_tuner_cycle.main()). These tools respect USE_GPT_REFLECTION_V4,
    #       USE_GPT_TUNER_V4, FORCE_GPT_REFLECTION_V4, and FORCE_GPT_TUNER_V4 environment
    #       variables. Ensure these are set before running the nightly cycle to use v4.
    research_steps = [
        ("ARE", "tools.run_are_cycle", "main"),
        ("MicrostructureScan", "tools.run_microstructure_scan", "main"),
        ("DriftScan", "tools.run_drift_scan", "main"),
        ("CorrelationScan", "tools.run_correlation_scan", "main"),
        ("AlphaBetaScan", "tools.run_alpha_beta_scan", "main"),
        ("ExecutionQuality", "tools.run_execution_quality_scan", "main"),
        ("NormalLaneOptimizer", "tools.run_normal_lane_optimizer", "main"),
        ("SymbolEdgeProfile", "tools.run_symbol_edge_profile", "main"),  # Added for PSOE
        ("LiquiditySweeps", "tools.run_liquidity_sweeps", "main"),  # Phase 12A: Liquidity Sweeps Engine
        ("VolumeImbalance", "tools.run_volume_imbalance_scan", "main"),  # Phase 12B: Volume Imbalance Engine
        ("MarketStructure", "tools.run_market_structure_scan", "main"),  # Phase 12D: Market Structure + Sessions
        ("BreakoutReliability", "tools.run_breakout_reliability_scan", "main"),  # Phase 1: Breakout Reliability Engine
        ("RegimeFusion", "engine_alpha.core.regime_fusion", "run_regime_fusion_for_universe"),  # Phase 2: Regime Awareness V2
        ("ConfidenceV2", "engine_alpha.core.confidence_v2", "run_confidence_v2_for_universe"),  # Phase 2: Confidence Engine V2
        ("PreCandleAttribution", "engine_alpha.reflect.pre_candle_attribution", "generate_attribution_report"),  # Phase 3: PCI attribution analysis
        ("Reflection", "tools.run_reflection_cycle", "main"),  # v4-aware: respects USE_GPT_REFLECTION_V4
        ("Tuner", "tools.run_tuner_cycle", "main"),  # v4-aware: respects USE_GPT_TUNER_V4
        ("Dream", "tools.run_dream_cycle", "main"),
        ("QualityScores", "tools.quality_scores", "main"),
        ("Evolver", "tools.run_evolver_cycle", "main"),
        ("MutationPreview", "tools.run_mutation_preview", "main"),
        ("MemorySnapshot", "tools.run_memory_snapshot", "main"),
        ("MetaReview", "tools.run_meta_review", "main"),
        ("VariantCycle", "tools.run_variant_cycle", "main"),
        ("PromotionEngine", "tools.run_promotion_engine", "main"),
        ("AutoRotation", "tools.run_auto_rotation", "main"),
        ("TuningSelfEval", "tools.run_tuning_self_eval", "main"), # Added for self-evaluation
        ("TuningAdvisor", "tools.run_tuning_advisor", "main"), # Added for Per-Symbol Tuning Advisor
        ("RiskSnapshot", "tools.run_risk_snapshot", "main"), # Added for Phase 9: Multi-Factor Risk Engine
        ("SCMState", "tools.run_scm_state", "main"), # Added for Phase 10: Sample Collection Mode
        ("CapitalOverview", "tools.capital_overview", "main"),
    ]
    
    # PF Time-Series + Capital Protection (ADVISORY ONLY)
    try:
        _run_pf_timeseries_and_capital_protection()
    except Exception as exc:  # noqa: BLE001
        logging.exception("PF time-series / capital protection step failed: %s", exc)
        notes.append(f"PF time-series / capital protection failed: {exc}")

    # Phase 3a: Exploration Policy V3 (ADVISORY ONLY)
    try:
        _run_exploration_policy_v3()
    except Exception as exc:  # noqa: BLE001
        logging.exception("Exploration Policy V3 step failed: %s", exc)
        notes.append(f"Exploration Policy V3 failed: {exc}")
    
    # Load symbols for Phase 2 steps
    try:
        from engine_alpha.core.symbol_registry import load_symbol_registry
        symbols = load_symbol_registry()
        if not symbols:
            # Fallback to defaults
            symbols = [
                "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "AVAXUSDT",
                "LINKUSDT", "DOTUSDT", "ADAUSDT", "ATOMUSDT", "XRPUSDT", "DOGEUSDT"
            ]
    except Exception:
        symbols = [
            "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "AVAXUSDT",
            "LINKUSDT", "DOTUSDT", "ADAUSDT", "ATOMUSDT", "XRPUSDT", "DOGEUSDT"
        ]
    
    timeframe = "15m"  # Default timeframe
    
    # Run each step
    for step_name, module_name, function_name in research_steps:
        print(f"Running {step_name}...")
        
        # Phase 2 steps need symbols and timeframe
        if step_name in ("RegimeFusion", "ConfidenceV2"):
            step_result = run_step(step_name, module_name, function_name, symbols=symbols, timeframe=timeframe)
        else:
            step_result = run_step(step_name, module_name, function_name)
        
        steps.append(step_result)
        
        if step_result["status"] == "OK":
            print(f"  [OK] {step_name}")
        else:
            error_msg = step_result.get("error", "Unknown error")
            print(f"  [FAIL] {step_name}: {error_msg}")
            notes.append(f"{step_name} failed: {error_msg}")
    
    print()
    
    # Build summary
    summary = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "steps": steps,
        "notes": notes if notes else [
            "All steps attempted; see logs for details if any failures."
        ],
    }
    
    # Write summary
    PIPELINE_DIR.mkdir(parents=True, exist_ok=True)
    RESEARCH_SUMMARY_PATH.write_text(json.dumps(summary, indent=2))
    
    print("=" * 70)
    print("RESEARCH CYCLE SUMMARY")
    print("=" * 70)
    
    ok_count = sum(1 for s in steps if s["status"] == "OK")
    fail_count = len(steps) - ok_count
    
    print(f"Steps completed: {ok_count}/{len(steps)}")
    if fail_count > 0:
        print(f"Steps failed: {fail_count}")
        print()
        print("Failed steps:")
        for step in steps:
            if step["status"] == "FAIL":
                print(f"  - {step['name']}: {step.get('error', 'Unknown error')}")
    else:
        print("✅ All steps completed successfully")
    
    print()
    print(f"Summary written to: {RESEARCH_SUMMARY_PATH}")
    print("=" * 70)


def _run_pf_timeseries_and_capital_protection() -> None:
    """
    Phase: PF Time-Series + Capital Protection

    Outputs:
      * reports/pf/pf_timeseries.json
      * reports/risk/capital_protection.json

    All outputs are ADVISORY-ONLY and PAPER-SAFE.
    """
    from engine_alpha.research.pf_timeseries import compute_pf_timeseries
    from engine_alpha.risk.capital_protection import run_capital_protection

    logging.info("Running PF Time-Series engine...")
    compute_pf_timeseries()
    logging.info("Running Capital Protection engine...")
    run_capital_protection()


def _run_exploration_policy_v3() -> None:
    """
    Phase 3a integration:
      * Exploration Policy V3 (symbol-level, advisory-only)

    Output:
      * reports/research/exploration_policy_v3.json

    This does not modify any configs or live behavior.
    """
    from engine_alpha.research.exploration_policy_v3 import compute_exploration_policy_v3

    logging.info("Running Exploration Policy V3 engine...")
    compute_exploration_policy_v3()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️  Research cycle interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Research cycle crashed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

