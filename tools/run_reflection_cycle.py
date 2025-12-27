"""
Run the full reflection cycle: snapshot → (stub or GPT) reflection output.

This orchestrates:
1. Build reflection snapshot (reflection_input.json)
2. Build reflection output (reflection_output.json) - uses GPT if USE_GPT_REFLECTION=true, else stub
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from tools import build_reflection_snapshot

ROOT = Path(__file__).resolve().parents[1]
GPT_REPORT_DIR = ROOT / "reports" / "gpt"
REFLECTION_INPUT_PATH = GPT_REPORT_DIR / "reflection_input.json"
REFLECTION_OUTPUT_PATH = GPT_REPORT_DIR / "reflection_output.json"


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def build_stub_reflection_output(reflection_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a stub reflection output file.
    In the future, GPT Reflection will consume reflection_input and produce this.
    For now, we create simple tier assignments based on PF.
    """
    symbols = reflection_input.get("symbols", {})
    
    tiers: Dict[str, list] = {
        "tier1": [],
        "tier2": [],
        "tier3": [],
    }
    
    symbol_insights: Dict[str, Dict[str, Any]] = {}
    
    for sym, stats in symbols.items():
        exp_pf = stats.get("exp_pf")
        exp_trades = stats.get("exp_trades", 0)
        norm_pf = stats.get("norm_pf")
        norm_trades = stats.get("norm_trades", 0)
        
        # Simple stub logic: assign tiers based on PF
        tier = "tier2"  # default neutral
        
        # Use exploration PF if available, else normal PF
        pf_to_use = exp_pf if exp_trades > 0 else norm_pf
        trades_to_use = exp_trades if exp_trades > 0 else norm_trades
        
        if isinstance(pf_to_use, (int, float)) and trades_to_use >= 3:
            if pf_to_use > 1.5:
                tier = "tier1"  # Strong performer
            elif pf_to_use < 0.8:
                tier = "tier3"  # Weak performer
            else:
                tier = "tier2"  # Neutral
        elif trades_to_use == 0:
            tier = "tier2"  # No data yet
        
        tiers[tier].append(sym)
        
        # Build insight
        comment = f"Stub reflection: {exp_trades} exploration trades, {norm_trades} normal trades"
        if isinstance(pf_to_use, (int, float)):
            comment += f", PF={pf_to_use:.2f}"
        
        symbol_insights[sym] = {
            "tier": tier,
            "comment": comment,
            "actions": ["continue_observation"] if tier == "tier2" else ["monitor_closely"],
        }
    
    now = datetime.now(timezone.utc).isoformat()
    
    return {
        "generated_at": now,
        "tiers": tiers,
        "symbol_insights": symbol_insights,
        "notes": [
            "This is a stub reflection output. In future, GPT Reflection will write this file.",
            "Tiers are assigned based on simple PF thresholds (stub logic).",
        ],
    }


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


def _run_reflection_v4(reflection_input: Dict[str, Any], force_mode: bool = False) -> Dict[str, Any]:
    """Run GPT Reflection v4. Raises on error if force_mode=True, returns None on validation failure if force_mode=False."""
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("OpenAI package not available")
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    
    model = os.getenv("GPT_REFLECTION_MODEL", "gpt-4o-mini")
    prompt_path = ROOT / "config" / "prompts" / "reflection_v4.txt"
    
    if not prompt_path.exists():
        raise FileNotFoundError(f"reflection_v4.txt not found at {prompt_path}")
    
    system_prompt = prompt_path.read_text().strip()
    
    # Load all research inputs for v4
    research_inputs = load_research_inputs()
    reflection_input_with_research = reflection_input.copy()
    reflection_input_with_research.update(research_inputs)
    
    client = OpenAI(api_key=api_key)
    user_prompt = json.dumps(reflection_input_with_research, indent=2)
    
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    
    content = response.choices[0].message.content
    gpt_output = json.loads(content)
    
    # Validate v4 structure - only fail on truly invalid JSON or missing required fields
    # Required: tiers (dict), symbol_insights (dict)
    # Optional: global_summary (will be synthesized if missing)
    valid = True
    errors = []
    
    if not isinstance(gpt_output, dict):
        valid = False
        errors.append("output is not a dict")
    else:
        # Check required fields
        tiers = gpt_output.get("tiers")
        if not isinstance(tiers, dict):
            valid = False
            errors.append("missing or invalid 'tiers'")
        
        symbol_insights = gpt_output.get("symbol_insights")
        if not isinstance(symbol_insights, dict):
            valid = False
            errors.append("missing or invalid 'symbol_insights'")
        
        # global_summary is OPTIONAL - always synthesize if missing or wrong type
        gs = gpt_output.get("global_summary")
        if not isinstance(gs, dict):
            gpt_output["global_summary"] = {"notes": [], "warnings": []}
        else:
            # Normalize global_summary structure
            if "notes" not in gs:
                gs["notes"] = []
            if "warnings" not in gs:
                gs["warnings"] = []
            if isinstance(gs["notes"], str):
                gs["notes"] = [gs["notes"]]
            if isinstance(gs["warnings"], str):
                gs["warnings"] = [gs["warnings"]]
    
    # Only fail if required fields are missing/invalid (not optional fields)
    if not valid:
        if force_mode:
            print(f"⚠️  [Reflection v4] Validation warnings (ignored due to FORCE): {', '.join(errors)}")
            print(f"   GPT output keys: {list(gpt_output.keys()) if isinstance(gpt_output, dict) else 'N/A'}")
        else:
            raise ValueError(f"GPT Reflection v4 validation failed: {', '.join(errors)}")
    
    now = datetime.now(timezone.utc).isoformat()
    tiers = gpt_output.get("tiers", {})
    symbol_insights = gpt_output.get("symbol_insights", {})
    
    return {
        "generated_at": now,
        "tiers": {
            "tier1": tiers.get("tier1", []),
            "tier2": tiers.get("tier2", []),
            "tier3": tiers.get("tier3", []),
        },
        "symbol_insights": symbol_insights,
        "global_summary": gpt_output.get("global_summary", {"notes": [], "warnings": []}),
        "notes": [
            "Generated by GPT Reflection v4",
            f"Model: {model}",
        ],
    }


def _run_reflection_v2(reflection_input: Dict[str, Any]) -> Dict[str, Any]:
    """Run GPT Reflection v2."""
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("OpenAI package not available")
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    
    model = os.getenv("GPT_REFLECTION_MODEL", "gpt-4o-mini")
    prompt_path = ROOT / "config" / "prompts" / "reflection_v2.txt"
    
    if not prompt_path.exists():
        raise FileNotFoundError(f"reflection_v2.txt not found at {prompt_path}")
    
    system_prompt = prompt_path.read_text().strip()
    
    client = OpenAI(api_key=api_key)
    user_prompt = json.dumps(reflection_input, indent=2)
    
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    
    content = response.choices[0].message.content
    gpt_output = json.loads(content)
    
    # Validate v2/v3 structure
    required_keys = ["tiers", "symbol_insights"]
    missing_keys = [key for key in required_keys if key not in gpt_output]
    if missing_keys:
        raise ValueError(f"GPT Reflection v2/v3 validation failed: missing keys {missing_keys}")
    
    tiers = gpt_output.get("tiers", {})
    if not isinstance(tiers, dict):
        raise ValueError("GPT Reflection v2/v3 validation failed: tiers is not a dict")
    
    symbol_insights = gpt_output.get("symbol_insights", {})
    if not isinstance(symbol_insights, dict):
        raise ValueError("GPT Reflection v3 validation failed: symbol_insights is not a dict")
    
    now = datetime.now(timezone.utc).isoformat()
    return {
        "generated_at": now,
        "tiers": {
            "tier1": tiers.get("tier1", []),
            "tier2": tiers.get("tier2", []),
            "tier3": tiers.get("tier3", []),
        },
        "symbol_insights": symbol_insights,
        "global_summary": gpt_output.get("global_summary", ""),
        "notes": [
            "Generated by GPT Reflection v3",
            f"Model: {model}",
        ],
    }


def _run_reflection_v1(reflection_input: Dict[str, Any]) -> Dict[str, Any]:
    """Run GPT Reflection v1."""
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("OpenAI package not available")
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    
    model = os.getenv("GPT_REFLECTION_MODEL", "gpt-4o-mini")
    system_prompt = """You are Chloe's trading performance analyst. Analyze the symbol performance data and return a structured JSON response with:
- tiers: dict with "tier1", "tier2", "tier3" keys, each containing a list of symbol strings
- symbol_insights: dict keyed by symbol, each with:
  - tier: "tier1", "tier2", or "tier3"
  - comment: brief analysis string
  - actions: list of action strings like ["continue_observation"] or ["monitor_closely"]
  
Tier assignment rules:
- tier1: Strong performers (PF > 1.2 with sufficient trades)
- tier2: Neutral/average performers or insufficient data
- tier3: Weak performers (PF < 0.9 with sufficient trades)

Return ONLY valid JSON, no markdown, no explanation."""
    
    client = OpenAI(api_key=api_key)
    user_prompt = json.dumps(reflection_input, indent=2)
    
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    
    content = response.choices[0].message.content
    gpt_output = json.loads(content)
    
    tiers = gpt_output.get("tiers", {})
    symbol_insights = gpt_output.get("symbol_insights", {})
    
    now = datetime.now(timezone.utc).isoformat()
    return {
        "generated_at": now,
        "tiers": {
            "tier1": tiers.get("tier1", []),
            "tier2": tiers.get("tier2", []),
            "tier3": tiers.get("tier3", []),
        },
        "symbol_insights": symbol_insights,
        "notes": [
            "Generated by GPT Reflection",
            f"Model: {model}",
        ],
    }


def main() -> None:
    GPT_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Step 1: Build reflection snapshot
    build_reflection_snapshot.main()
    
    # Step 2: Load reflection input
    reflection_input = load_json(REFLECTION_INPUT_PATH)
    if not reflection_input:
        print(f"❌ Failed to load reflection_input.json at {REFLECTION_INPUT_PATH}")
        return
    
    # Step 3: Determine GPT mode and run accordingly
    use_gpt = os.getenv("USE_GPT_REFLECTION", "false").lower() == "true"
    use_v2 = os.getenv("USE_GPT_REFLECTION_V2", "false").lower() == "true"
    use_v4 = os.getenv("USE_GPT_REFLECTION_V4", "false").lower() == "true"
    force_v4 = os.getenv("FORCE_GPT_REFLECTION_V4", "false").lower() == "true"
    
    # ----- CASE 0: GPT DISABLED -----
    if not use_gpt:
        print("🧠 GPT Reflection disabled; using stub reflection.")
        reflection_output = build_stub_reflection_output(reflection_input)
    
    # ----- CASE 1: FORCE MODE (v4 ONLY, NO FALLBACK) -----
    elif force_v4 and use_v4:
        print("🧠 Using GPT Reflection v4 (FORCED)...")
        reflection_output = _run_reflection_v4(reflection_input, force_mode=True)
    
    # ----- CASE 2: NORMAL MODE (v4 → v2 → v1 fallback) -----
    else:
        try:
            if use_v4:
                print("🧠 Using GPT Reflection v4...")
                reflection_output = _run_reflection_v4(reflection_input, force_mode=False)
            elif use_v2:
                print("🧠 Using GPT Reflection v2...")
                reflection_output = _run_reflection_v2(reflection_input)
            else:
                print("🧠 Using GPT Reflection v1...")
                reflection_output = _run_reflection_v1(reflection_input)
        except Exception as exc:
            print(f"⚠️  [Reflection] Error in GPT v4/v2 path: {exc}")
            print("🧠 Falling back to GPT Reflection v1...")
            try:
                reflection_output = _run_reflection_v1(reflection_input)
            except Exception as exc2:
                print(f"⚠️  [Reflection] Error in GPT v1 fallback: {exc2}")
                print("🧠 Falling back to stub reflection...")
                reflection_output = build_stub_reflection_output(reflection_input)
    
    REFLECTION_OUTPUT_PATH.write_text(json.dumps(reflection_output, indent=2, sort_keys=True))
    print(f"✅ Reflection output written to: {REFLECTION_OUTPUT_PATH}")
    print(f"   Tiers: tier1={len(reflection_output['tiers']['tier1'])}, "
          f"tier2={len(reflection_output['tiers']['tier2'])}, "
          f"tier3={len(reflection_output['tiers']['tier3'])}")


if __name__ == "__main__":
    main()


