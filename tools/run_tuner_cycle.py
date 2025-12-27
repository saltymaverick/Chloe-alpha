"""
Run the full tuner cycle: reflection → tuner input → (stub or GPT) tuner output.

This orchestrates:
1. Run reflection cycle (builds reflection_input & reflection_output)
2. Build tuner input (from reflection files)
3. Build tuner output - uses GPT if USE_GPT_TUNER=true, else stub
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from tools import run_reflection_cycle
from tools import build_tuner_input

ROOT = Path(__file__).resolve().parents[1]
GPT_REPORT_DIR = ROOT / "reports" / "gpt"
RESEARCH_DIR = ROOT / "reports" / "research"
TUNER_INPUT_PATH = GPT_REPORT_DIR / "tuner_input.json"
TUNER_OUTPUT_PATH = GPT_REPORT_DIR / "tuner_output.json"
SELF_EVAL_PATH = RESEARCH_DIR / "tuning_self_eval.json"
DREAM_SUMMARY_PATH = GPT_REPORT_DIR / "dream_summary.json"

# Sample-size thresholds
MIN_EXPL_FOR_TUNING = 10  # Minimum exploration closes required for tuning


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def load_self_eval_summary() -> Dict[str, Dict[str, int]]:
    """Load tuning self-eval summary for gating proposals."""
    if not SELF_EVAL_PATH.exists():
        return {}
    try:
        data = json.loads(SELF_EVAL_PATH.read_text())
        return data.get("summary", {})
    except Exception:
        return {}


def build_stub_tuner_output(tuner_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a stub tuner output file.
    In the future, GPT Tuner will consume tuner_input and produce this.
    For now, we create safe "no-op" or minimal suggestions.
    """

    symbols = tuner_input.get("symbols", {})
    tiers = tuner_input.get("tiers", {})
    engine_mode = tuner_input.get("engine_mode", "PAPER")

    proposals: Dict[str, Dict[str, Any]] = {}

    for sym, stats in symbols.items():
        tier = stats.get("tier", "tier2")
        exp_pf = stats.get("exp_pf")
        exp_trades = stats.get("exp_trades", 0)

        # Default no-op
        proposals[sym] = {
            "conf_min_delta": 0.0,
            "exploration_cap_delta": 0,
            "notes": [],
        }

        # Simple stub logic:
        # tier1 → consider tiny loosening if enough sample
        if tier == "tier1" and isinstance(exp_pf, (int, float)) and exp_pf is not None and exp_trades >= 5:
            proposals[sym]["conf_min_delta"] = -0.02
            proposals[sym]["notes"].append("Stub: symbol is tier1 with enough exploration sample; slightly loosen confidence.")
        # tier3 → consider tiny tightening if enough sample
        elif tier == "tier3" and isinstance(exp_pf, (int, float)) and exp_pf is not None and exp_trades >= 5:
            proposals[sym]["conf_min_delta"] = +0.02
            proposals[sym]["exploration_cap_delta"] = -1
            proposals[sym]["notes"].append("Stub: symbol is tier3 with enough exploration sample; slightly tighten confidence and reduce exploration cap.")
        else:
            proposals[sym]["notes"].append("Stub: no change; awaiting more data or neutral tier.")

    now = datetime.now(timezone.utc).isoformat()
    tuner_output = {
        "generated_at": now,
        "engine_mode": engine_mode,
        "tuning_proposals": proposals,
        "notes": [
            "This is a stub tuner output. In future, GPT Tuner will write this file",
            "The engine (or you) will decide which proposals to apply.",
            "All deltas here are tiny and safe by design."
        ],
    }

    return tuner_output


def main() -> None:
    # Step 1: Run reflection cycle (builds reflection_input & reflection_output)
    run_reflection_cycle.main()

    # Step 2: Build tuner input based on reflection files
    build_tuner_input.main()

    tuner_input = load_json(TUNER_INPUT_PATH)
    if not tuner_input:
        print(f"❌ Failed to load tuner_input.json at {TUNER_INPUT_PATH}")
        return

    # Attach dream context if available (advisory-only)
    try:
        dream_summary = load_json(DREAM_SUMMARY_PATH)
    except Exception:
        dream_summary = {}
    meta = tuner_input.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        tuner_input["meta"] = meta
    if dream_summary:
        tuner_input["dream_context"] = dream_summary
        meta["dream_context_loaded"] = True
    else:
        meta["dream_context_loaded"] = False

    # Step 3: Determine GPT mode and run accordingly
    use_gpt = os.getenv("USE_GPT_TUNER", "false").lower() == "true"
    use_v2 = os.getenv("USE_GPT_TUNER_V2", "false").lower() == "true"
    use_v4 = os.getenv("USE_GPT_TUNER_V4", "false").lower() == "true"
    force_v4 = os.getenv("FORCE_GPT_TUNER_V4", "false").lower() == "true"
    
    # ----- CASE 0: GPT DISABLED -----
    if not use_gpt:
        print("🧠 GPT Tuner disabled; using stub tuner.")
        tuner_output_raw = build_stub_tuner_output(tuner_input)
    
    # ----- CASE 1: FORCE MODE (v4 ONLY) -----
    elif force_v4 and use_v4:
        print("🧠 Using GPT Tuner v4 (FORCED)...")
        tuner_output_raw = _run_tuner_v4(tuner_input, force_mode=True)
    
    # ----- CASE 2: NORMAL MODE (v4 → v2 → v1 fallback) -----
    else:
        try:
            if use_v4:
                print("🧠 Using GPT Tuner v4...")
                tuner_output_raw = _run_tuner_v4(tuner_input, force_mode=False)
            elif use_v2:
                print("🧠 Using GPT Tuner v2...")
                tuner_output_raw = _run_tuner_v2(tuner_input)
            else:
                print("🧠 Using GPT Tuner v1...")
                tuner_output_raw = _run_tuner_v1(tuner_input)
        except Exception as exc:
            print(f"⚠️  [Tuner] Error in GPT v4/v2 path: {exc}")
            print("🧠 Falling back to GPT Tuner v1...")
            try:
                tuner_output_raw = _run_tuner_v1(tuner_input)
            except Exception as exc2:
                print(f"⚠️  [Tuner] Error in GPT v1 fallback: {exc2}")
                print("🧠 Falling back to stub tuner...")
                tuner_output_raw = build_stub_tuner_output(tuner_input)
    
    GPT_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Wrap output with proposals wrapper for schema compliance
    now = datetime.now(timezone.utc).isoformat()
    proposals = tuner_output_raw.get("tuning_proposals", tuner_output_raw.get("proposals", tuner_output_raw))
    
    # Load trade counts for sample-size gating
    from engine_alpha.research.trade_stats import load_trade_counts
    trade_counts = load_trade_counts()
    
    # Apply sample-size gating first (before self-eval gating)
    if isinstance(proposals, dict):
        for sym, props in proposals.items():
            if not isinstance(props, dict):
                continue
            
            counts = trade_counts.get(sym, {})
            expl = counts.get("exploration_closes", 0)
            
            # If we don't have enough exploration trades, freeze tuning deltas
            if expl < MIN_EXPL_FOR_TUNING:
                # Mark as insufficient sample, keep schema
                props["conf_min_delta"] = 0.0
                props["exploration_cap_delta"] = 0
                props["tuning_insufficient_sample"] = True
                if "notes" not in props:
                    props["notes"] = []
                if isinstance(props["notes"], list):
                    props["notes"].append(f"Insufficient sample: {expl} exploration closes < {MIN_EXPL_FOR_TUNING}")
                continue
    
    # Apply self-eval gating to proposals (after sample-size gate)
    self_eval_summary = load_self_eval_summary()
    if self_eval_summary and isinstance(proposals, dict):
        for sym, props in proposals.items():
            if not isinstance(props, dict):
                continue
            
            sym_eval = self_eval_summary.get(sym, {})
            improved = sym_eval.get("improved", 0)
            degraded = sym_eval.get("degraded", 0)
            
            # Freeze tuning if history is net harmful
            if (degraded >= 2 and improved == 0) or (degraded > improved):
                # Set deltas to 0 to freeze tuning
                props["conf_min_delta"] = 0.0
                props["exploration_cap_delta"] = 0
                # Add note about freezing
                if "notes" not in props:
                    props["notes"] = []
                if isinstance(props["notes"], list):
                    props["notes"].append(f"Tuning frozen due to self-eval: {improved} improved vs {degraded} degraded")
                props["tuning_frozen_due_to_self_eval"] = True
    
    wrapped = {
        "generated_at": now,
        "proposals": proposals,
    }
    
    TUNER_OUTPUT_PATH.write_text(
        json.dumps(wrapped, indent=2, sort_keys=True)
    )

    # Log tuning reasons after successful tuner output generation
    try:
        from engine_alpha.logging.tuning_reason_logger import append_tuning_reason_entry
        append_tuning_reason_entry()
    except Exception as exc:
        print(f"[TuningReasonLog] Failed to append tuning reason entry: {exc}")

    print(f"✅ Tuner cycle complete.")
    print(f"   Input : {TUNER_INPUT_PATH}")
    print(f"   Output: {TUNER_OUTPUT_PATH}")


def load_research_inputs() -> Dict[str, Any]:
    """
    Load all research inputs for v4.
    
    Returns:
        Dict with microstructure, drift, correlation, alpha_beta, are, memory, meta, symbol_registry
    """
    research_inputs: Dict[str, Any] = {}
    
    # Load microstructure snapshot
    microstructure_path = ROOT / "reports" / "research" / "microstructure_snapshot_15m.json"
    if microstructure_path.exists():
        try:
            micro_data = json.loads(microstructure_path.read_text())
            research_inputs["microstructure"] = micro_data.get("symbols", {})
        except Exception:
            research_inputs["microstructure"] = {}
    else:
        research_inputs["microstructure"] = {}
    
    # Load drift report
    drift_path = ROOT / "reports" / "research" / "drift_report.json"
    if drift_path.exists():
        try:
            drift_data = json.loads(drift_path.read_text())
            research_inputs["drift"] = drift_data.get("symbols", {})
        except Exception:
            research_inputs["drift"] = {}
    else:
        research_inputs["drift"] = {}
    
    # Load correlation matrix
    corr_path = ROOT / "reports" / "research" / "correlation_matrix.json"
    if corr_path.exists():
        try:
            corr_data = json.loads(corr_path.read_text())
            research_inputs["correlation"] = {
                "matrix": corr_data.get("matrix", {}),
                "symbols": corr_data.get("symbols", []),
            }
        except Exception:
            research_inputs["correlation"] = {}
    else:
        research_inputs["correlation"] = {}
    
    # Load alpha/beta decomposition
    ab_path = ROOT / "reports" / "research" / "alpha_beta.json"
    if ab_path.exists():
        try:
            ab_data = json.loads(ab_path.read_text())
            research_inputs["alpha_beta"] = ab_data.get("symbols", {})
        except Exception:
            research_inputs["alpha_beta"] = {}
    else:
        research_inputs["alpha_beta"] = {}
    
    # Load ARE snapshot
    are_path = ROOT / "reports" / "research" / "are_snapshot.json"
    if are_path.exists():
        try:
            are_data = json.loads(are_path.read_text())
            research_inputs["are"] = are_data.get("symbols", {})
        except Exception:
            research_inputs["are"] = {}
    else:
        research_inputs["are"] = {}
    
    # Load memory snapshots
    try:
        from engine_alpha.research.research_memory import load_recent_memory
        memory_entries = load_recent_memory(n=5)
        research_inputs["memory"] = memory_entries if memory_entries else []
    except Exception:
        research_inputs["memory"] = []
    
    # Load meta-reasoner report
    meta_path = ROOT / "reports" / "research" / "meta_reasoner_report.json"
    if meta_path.exists():
        try:
            meta_data = json.loads(meta_path.read_text())
            research_inputs["meta"] = meta_data
        except Exception:
            research_inputs["meta"] = {}
    else:
        research_inputs["meta"] = {}
    
    # Load symbol registry
    symbol_registry_path = ROOT / "config" / "symbols.yaml"
    if symbol_registry_path.exists():
        try:
            import yaml
            registry_data = yaml.safe_load(symbol_registry_path.read_text())
            research_inputs["symbol_registry"] = registry_data.get("symbols", [])
        except Exception:
            research_inputs["symbol_registry"] = []
    else:
        research_inputs["symbol_registry"] = []
    
    # Load execution quality
    execution_quality_path = ROOT / "reports" / "research" / "execution_quality.json"
    if execution_quality_path.exists():
        try:
            exec_quality_data = json.loads(execution_quality_path.read_text())
            research_inputs["execution_quality"] = exec_quality_data.get("data", {})
        except Exception:
            research_inputs["execution_quality"] = {}
    else:
        research_inputs["execution_quality"] = {}
    
    # Load symbol edge profiles (for PSOE)
    edge_profile_path = ROOT / "reports" / "research" / "symbol_edge_profile.json"
    if edge_profile_path.exists():
        try:
            edge_profile_data = json.loads(edge_profile_path.read_text())
            # Handle both formats: direct dict or wrapped with "profiles" key
            if "profiles" in edge_profile_data:
                research_inputs["symbol_edge_profiles"] = edge_profile_data.get("profiles", {})
            else:
                research_inputs["symbol_edge_profiles"] = edge_profile_data
        except Exception:
            research_inputs["symbol_edge_profiles"] = {}
    else:
        research_inputs["symbol_edge_profiles"] = {}
    
    # Phase 12: Load Advanced Structure Engine (ASE) data
    # Liquidity sweeps
    liq_sweeps_path = ROOT / "reports" / "research" / "liquidity_sweeps.json"
    if liq_sweeps_path.exists():
        try:
            liq_data = json.loads(liq_sweeps_path.read_text())
            research_inputs["liquidity_sweeps"] = liq_data.get("symbols", {})
        except Exception:
            research_inputs["liquidity_sweeps"] = {}
    else:
        research_inputs["liquidity_sweeps"] = {}
    
    # Volume imbalance
    vol_imb_path = ROOT / "reports" / "research" / "volume_imbalance.json"
    if vol_imb_path.exists():
        try:
            vi_data = json.loads(vol_imb_path.read_text())
            research_inputs["volume_imbalance"] = vi_data.get("symbols", {})
        except Exception:
            research_inputs["volume_imbalance"] = {}
    else:
        research_inputs["volume_imbalance"] = {}
    
    # Market structure
    mkt_struct_path = ROOT / "reports" / "research" / "market_structure.json"
    if mkt_struct_path.exists():
        try:
            ms_data = json.loads(mkt_struct_path.read_text())
            research_inputs["market_structure"] = ms_data.get("symbols", {})
        except Exception:
            research_inputs["market_structure"] = {}
    else:
        research_inputs["market_structure"] = {}
    
    return research_inputs


def _run_tuner_v4(tuner_input: Dict[str, Any], force_mode: bool = False) -> Dict[str, Any]:
    """Run GPT Tuner v4. Raises on error if force_mode=True, returns None on validation failure if force_mode=False."""
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("OpenAI package not available")
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    
    model = os.getenv("GPT_TUNER_MODEL", "gpt-4o-mini")
    prompt_path = ROOT / "config" / "prompts" / "tuner_v4.txt"
    
    if not prompt_path.exists():
        raise FileNotFoundError(f"tuner_v4.txt not found at {prompt_path}")
    
    system_prompt = prompt_path.read_text().strip()
    
    # Load all research inputs for v4
    research_inputs = load_research_inputs()
    tuner_input_with_research = tuner_input.copy()
    tuner_input_with_research.update(research_inputs)
    
    client = OpenAI(api_key=api_key)
    user_prompt = json.dumps(tuner_input_with_research, indent=2)
    
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    
    content = response.choices[0].message.content
    gpt_output = json.loads(content)
    
    # v4 format: proposals key (not tuning_proposals), but be lenient
    # Accept either "proposals" or "tuning_proposals" for v4, normalize to "proposals"
    proposals = gpt_output.get("proposals")
    if proposals is None and "tuning_proposals" in gpt_output:
        proposals = gpt_output["tuning_proposals"]
        gpt_output["proposals"] = proposals
    
    # Only fail if proposals is completely missing or not a dict (required field)
    # Empty dict is acceptable - means no tuning proposals
    if proposals is None:
        if force_mode:
            print(f"⚠️  [Tuner v4] Validation warning (ignored due to FORCE): missing proposals/tuning_proposals key")
            print(f"   GPT output keys: {list(gpt_output.keys())}")
            proposals = {}
            gpt_output["proposals"] = proposals
        else:
            raise ValueError("GPT Tuner v4 validation failed: missing proposals/tuning_proposals key")
    
    if not isinstance(proposals, dict):
        if force_mode:
            print(f"⚠️  [Tuner v4] Validation warning (ignored due to FORCE): proposals is not a dict, creating empty dict")
            proposals = {}
            gpt_output["proposals"] = proposals
        else:
            raise ValueError("GPT Tuner v4 validation failed: proposals is not a dict")
    
    # Validate bounds for v4: conf_min_delta ∈ [-0.02, +0.02], exploration_cap_delta ∈ [-1, +1]
    validated_proposals = {}
    for sym, proposal in proposals.items():
        if not isinstance(proposal, dict):
            print(f"⚠️  GPT Tuner v4: skipping {sym} - proposal is not a dict")
            continue
        
        conf_delta = proposal.get("conf_min_delta", 0.0)
        cap_delta = proposal.get("exploration_cap_delta", 0)
        
        try:
            conf_float = float(conf_delta)
            cap_int = int(cap_delta)
            
            # Clamp deltas to bounds
            conf_float = max(-0.02, min(0.02, conf_float))
            cap_int = max(-1, min(1, cap_int))
            
            proposal["conf_min_delta"] = conf_float
            proposal["exploration_cap_delta"] = cap_int
            
            validated_proposals[sym] = proposal
        except (ValueError, TypeError):
            print(f"⚠️  GPT Tuner v4: skipping {sym} - invalid delta types")
            continue
    
    # Empty proposals dict is acceptable (means no tuning changes needed)
    # Only fail if we expected proposals but got invalid structure
    # For now, allow empty dict - it just means no tuning proposals
    if not validated_proposals:
        # Empty proposals is fine - means no tuning needed
        validated_proposals = {}
    
    now = datetime.now(timezone.utc).isoformat()
    return {
        "generated_at": now,
        "engine_mode": tuner_input.get("engine_mode", "PAPER"),
        "proposals": validated_proposals,
        "notes": [
            "Generated by GPT Tuner v4",
            f"Model: {model}",
            "All proposals are advisory only - review before applying",
            "Deltas clamped to safe bounds: conf_min_delta [-0.02, 0.02], exploration_cap_delta [-1, 1]",
        ],
    }


def _run_tuner_v2(tuner_input: Dict[str, Any]) -> Dict[str, Any]:
    """Run GPT Tuner v2."""
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("OpenAI package not available")
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    
    model = os.getenv("GPT_TUNER_MODEL", "gpt-4o-mini")
    prompt_path = ROOT / "config" / "prompts" / "tuner_v2.txt"
    
    if not prompt_path.exists():
        raise FileNotFoundError(f"tuner_v2.txt not found at {prompt_path}")
    
    system_prompt = prompt_path.read_text().strip()
    
    client = OpenAI(api_key=api_key)
    user_prompt = json.dumps(tuner_input, indent=2)
    
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    
    content = response.choices[0].message.content
    gpt_output = json.loads(content)
    
    # v2/v3 format: tuning_proposals key
    if "tuning_proposals" not in gpt_output:
        raise ValueError("GPT Tuner v2/v3 validation failed: missing tuning_proposals key")
    
    tuning_proposals = gpt_output.get("tuning_proposals", {})
    if not isinstance(tuning_proposals, dict):
        raise ValueError("GPT Tuner v2/v3 validation failed: tuning_proposals is not a dict")
    
    # Validate bounds for v2/v3: conf_min_delta ∈ [-0.03, +0.03], exploration_cap_delta ∈ [-2, +2]
    for sym, proposal in tuning_proposals.items():
        if not isinstance(proposal, dict):
            raise ValueError(f"GPT Tuner v2/v3 validation failed: proposal for {sym} is not a dict")
        
        conf_delta = proposal.get("conf_min_delta", 0.0)
        cap_delta = proposal.get("exploration_cap_delta", 0)
        
        try:
            conf_float = float(conf_delta)
            cap_int = int(cap_delta)
            
            if conf_float < -0.03 or conf_float > 0.03:
                proposal["conf_min_delta"] = max(-0.03, min(0.03, conf_float))
            
            if cap_int < -2 or cap_int > 2:
                proposal["exploration_cap_delta"] = max(-2, min(2, cap_int))
        except (ValueError, TypeError):
            raise ValueError(f"GPT Tuner v2/v3 validation failed: {sym} has invalid delta types")
    
    now = datetime.now(timezone.utc).isoformat()
    return {
        "generated_at": now,
        "engine_mode": tuner_input.get("engine_mode", "PAPER"),
        "tuning_proposals": tuning_proposals,
        "notes": [
            "Generated by GPT Tuner v2",
            f"Model: {model}",
            "All proposals are advisory only - review before applying",
        ],
    }


def _run_tuner_v1(tuner_input: Dict[str, Any]) -> Dict[str, Any]:
    """Run GPT Tuner v1."""
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("OpenAI package not available")
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    
    model = os.getenv("GPT_TUNER_MODEL", "gpt-4o-mini")
    system_prompt = """You are Chloe's threshold tuner. Analyze symbol performance and propose small, conservative adjustments to confidence thresholds and exploration caps.

Return JSON with tuning_proposals dict keyed by symbol, each containing:
- conf_min_delta: float (small adjustment, typically -0.03 to +0.03)
- exploration_cap_delta: int (small adjustment, typically -2 to +2)
- notes: list of strings explaining the proposal

Be conservative - only propose changes when there's clear evidence. Default to 0.0 delta if uncertain."""
    
    client = OpenAI(api_key=api_key)
    user_prompt = json.dumps(tuner_input, indent=2)
    
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    
    content = response.choices[0].message.content
    gpt_output = json.loads(content)
    
    tuning_proposals = gpt_output.get("tuning_proposals", {})
    
    now = datetime.now(timezone.utc).isoformat()
    return {
        "generated_at": now,
        "engine_mode": tuner_input.get("engine_mode", "PAPER"),
        "tuning_proposals": tuning_proposals,
        "notes": [
            "Generated by GPT Tuner",
            f"Model: {model}",
            "All proposals are advisory only - review before applying",
        ],
    }


if __name__ == "__main__":
    main()


