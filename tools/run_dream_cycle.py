"""
Run Dream/Replay cycle (stub output for now).

Orchestrates reflection + tuner cycles, builds dream input, and generates stub dream output.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List

from tools import run_tuner_cycle
from tools import build_dream_input
from engine_alpha.reflect.dream_guard import should_run_dream

ROOT = Path(__file__).resolve().parents[1]
GPT_REPORT_DIR = ROOT / "reports" / "gpt"
DREAM_INPUT_PATH = GPT_REPORT_DIR / "dream_input.json"
DREAM_OUTPUT_PATH = GPT_REPORT_DIR / "dream_output.json"
DREAM_SUMMARY_PATH = GPT_REPORT_DIR / "dream_summary.json"


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def build_stub_dream_output(dream_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stub Dream output.

    In the future, GPT Dream will:
      - read dream_input.json
      - reason about each scenario
      - propose qualitative insights (e.g., 'this trade was structurally flawed vs just unlucky')
      - suggest which proposals to trust.

    For now, we generate a simple classification:
      - mark scenarios as 'review', 'ok', 'questionable' based on pct and tier.
    """

    engine_mode = dream_input.get("engine_mode", "PAPER")
    symbols = dream_input.get("symbols", {})
    scenarios = dream_input.get("scenarios", [])

    scenario_reviews = []

    for sc in scenarios:
        sym = sc.get("symbol")
        pct = sc.get("pct")
        trade_kind = sc.get("trade_kind", "normal")
        regime = sc.get("regime")
        exit_reason = sc.get("exit_reason")

        sym_info = symbols.get(sym, {})
        tier = sym_info.get("tier", "tier2")

        label = "review"
        notes = []

        if pct is None:
            label = "unknown"
            notes.append("No pct available.")
        else:
            try:
                p = float(pct)
                if p < -0.01:
                    label = "bad"
                    notes.append("Trade lost more than 1%.")
                elif p > 0.01:
                    label = "good"
                    notes.append("Trade gained more than 1%.")
                else:
                    label = "flat"
                    notes.append("Small magnitude trade; likely noise.")
            except Exception:
                label = "unknown"
                notes.append("Could not parse pct as float.")

        notes.append(f"Tier at time of analysis: {tier}")
        notes.append(f"Trade kind: {trade_kind}")
        if regime:
            notes.append(f"Regime: {regime}")
        if exit_reason:
            notes.append(f"Exit reason: {exit_reason}")

        scenario_reviews.append({
            "symbol": sym,
            "time": sc.get("time"),
            "pct": pct,
            "trade_kind": trade_kind,
            "label": label,
            "notes": notes,
        })

    now = datetime.now(timezone.utc).isoformat()
    dream_output = {
        "generated_at": now,
        "engine_mode": engine_mode,
        "scenario_reviews": scenario_reviews,
        "notes": [
            "This is a stub Dream output. GPT Dream/Replay will eventually produce richer scenario-level analysis.",
            "Scenario labels (good/bad/flat) are based solely on pct thresholds and do not use advanced reasoning."
        ],
    }
    return dream_output


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
    
    return research_inputs


def call_gpt_dream(dream_input: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Call GPT to generate dream output from dream input.
    Returns structured JSON matching dream_output format, or None on error.
    """
    use_gpt = os.getenv("USE_GPT_DREAM", "false").lower() == "true"
    use_v4 = os.getenv("USE_GPT_DREAM_V4", "false").lower() == "true"
    
    if not use_gpt:
        return None
    
    try:
        from openai import OpenAI
    except ImportError:
        print("⚠️  OpenAI package not available, using stub dream")
        return None
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("⚠️  OPENAI_API_KEY not set, using stub dream")
        return None
    
    # Get model from env or use default
    model = os.getenv("GPT_DREAM_MODEL", "gpt-4o-mini")
    
    try:
        client = OpenAI(api_key=api_key)
        
        # Load prompt based on version
        if use_v4:
            prompt_path = ROOT / "config" / "prompts" / "dream_v4.txt"
            if prompt_path.exists():
                system_prompt = prompt_path.read_text().strip()
                print("🧠 Using GPT Dream v4...")
                
                # Load all research inputs for v4
                research_inputs = load_research_inputs()
                dream_input.update(research_inputs)
            else:
                print(f"⚠️  dream_v4.txt not found at {prompt_path}, falling back to v2")
                use_v4 = False
        else:
            # Load v2 prompt
            prompt_path = ROOT / "config" / "prompts" / "dream_v2.txt"
            if prompt_path.exists():
                system_prompt = prompt_path.read_text().strip()
                print("🧠 Using GPT Dream v2...")
            else:
                print(f"⚠️  dream_v2.txt not found at {prompt_path}, using basic prompt")
                system_prompt = """You are Chloe's scenario analyst. Analyze trade scenarios and label them as "good", "bad", or "improve" with detailed notes."""
        
        user_prompt = json.dumps(dream_input, indent=2)
        
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
        
        # Validate structure based on version
        if use_v4:
            # Validate v4 structure: scenario_reviews and global_summary (dict with patterns/warnings)
            if "scenario_reviews" not in gpt_output:
                print(f"⚠️  GPT Dream v4 validation failed: missing scenario_reviews key, falling back to stub")
                return None
            
            scenario_reviews = gpt_output.get("scenario_reviews", [])
            if not isinstance(scenario_reviews, list):
                print(f"⚠️  GPT Dream v4 validation failed: scenario_reviews is not a list, falling back to stub")
                return None
            
            # Validate each review has required fields
            for review in scenario_reviews:
                if not isinstance(review, dict):
                    print(f"⚠️  GPT Dream v4 validation failed: review is not a dict, falling back to stub")
                    return None
                
                required_fields = ["symbol", "time", "label", "notes"]
                missing_fields = [field for field in required_fields if field not in review]
                if missing_fields:
                    print(f"⚠️  GPT Dream v4 validation failed: review missing fields {missing_fields}, falling back to stub")
                    return None
                
                # Validate label with alias: flat -> neutral
                label = review.get("label", "").lower()
                if label == "flat":
                    label = "neutral"  # flat -> neutral alias
                if label not in ["good", "bad", "improve", "neutral"]:
                    print(f"⚠️  GPT Dream v4 validation failed: invalid label '{label}', falling back to stub")
                    return None
                # normalize stored label
                review["label"] = label
            
            # Validate global_summary structure (v4: dict with patterns and warnings)
            global_summary = gpt_output.get("global_summary", {})
            if not isinstance(global_summary, dict):
                print(f"⚠️  GPT Dream v4 validation failed: global_summary is not a dict, falling back to stub")
                return None
            
            if "patterns" not in global_summary or "warnings" not in global_summary:
                print(f"⚠️  GPT Dream v4 validation failed: global_summary missing patterns/warnings, falling back to stub")
                return None
            
            now = datetime.now(timezone.utc).isoformat()
            dream_output = {
                "generated_at": now,
                "engine_mode": dream_input.get("engine_mode", "PAPER"),
                "scenario_reviews": scenario_reviews,
                "global_summary": global_summary,
                "notes": [
                    "Generated by GPT Dream v4",
                    f"Model: {model}",
                ],
            }
        else:
            # Validate v2/v3 structure: scenario_reviews and global_summary (string)
            if "scenario_reviews" not in gpt_output:
                print(f"⚠️  GPT Dream v2/v3 validation failed: missing scenario_reviews key, falling back to stub")
                return None
            
            scenario_reviews = gpt_output.get("scenario_reviews", [])
            if not isinstance(scenario_reviews, list):
                print(f"⚠️  GPT Dream v2/v3 validation failed: scenario_reviews is not a list, falling back to stub")
                return None
            
            # Validate each review has required fields
            for review in scenario_reviews:
                if not isinstance(review, dict):
                    print(f"⚠️  GPT Dream v2/v3 validation failed: review is not a dict, falling back to stub")
                    return None
                
                required_fields = ["symbol", "time", "label", "notes"]
                missing_fields = [field for field in required_fields if field not in review]
                if missing_fields:
                    print(f"⚠️  GPT Dream v2/v3 validation failed: review missing fields {missing_fields}, falling back to stub")
                    return None
                
                # Validate label with alias: flat -> neutral
                label = review.get("label", "").lower()
                if label == "flat":
                    label = "neutral"  # flat -> neutral alias
                if label not in ["good", "bad", "improve", "neutral"]:
                    print(f"⚠️  GPT Dream v2/v3 validation failed: invalid label '{label}', falling back to stub")
                    return None
                # normalize stored label
                review["label"] = label
            
            now = datetime.now(timezone.utc).isoformat()
            dream_output = {
                "generated_at": now,
                "engine_mode": dream_input.get("engine_mode", "PAPER"),
                "scenario_reviews": scenario_reviews,
                "global_summary": gpt_output.get("global_summary", ""),
                "notes": [
                    "Generated by GPT Dream v2",
                    f"Model: {model}",
                ],
            }
        
        return dream_output
        
    except Exception as e:
        print(f"⚠️  GPT dream failed: {e}, falling back to stub")
        import traceback
        traceback.print_exc()
        return None


def build_dream_summary(dream_output: Dict[str, Any], stub_reason: Optional[str] = None) -> Dict[str, Any]:
    """
    Produce a compact, machine-readable summary for downstream tuning (advisory-only).
    """
    reviews = dream_output.get("scenario_reviews", []) or []
    global_summary = dream_output.get("global_summary") or {}

    patterns = global_summary.get("patterns") if isinstance(global_summary, dict) else None
    warnings = global_summary.get("warnings") if isinstance(global_summary, dict) else None

    if not isinstance(patterns, list):
        patterns = []
    if not isinstance(warnings, list):
        warnings = []

    label_counts: Counter[str] = Counter()
    bad_symbols_set: List[str] = []
    bad_regimes_set: List[str] = []

    symbol_re = re.compile(r"[A-Z0-9]{2,10}USDT")
    regime_keywords = ("chop", "trend_down", "trend_up", "high_vol")

    def _dedupe_push(seq: List[str], val: str):
        if val and val not in seq:
            seq.append(val)

    # Extract from scenario reviews
    for r in reviews:
        label = str(r.get("label") or "").lower()
        label_counts[label] += 1

        # scan notes for symbols/regimes
        notes = r.get("notes") or []
        if isinstance(notes, list):
            for n in notes:
                if not isinstance(n, str):
                    continue
                for m in symbol_re.findall(n.upper()):
                    _dedupe_push(bad_symbols_set, m)
                lower_n = n.lower()
                for kw in regime_keywords:
                    if kw in lower_n:
                        _dedupe_push(bad_regimes_set, kw)

        # also scan symbol/regime fields when labeled bad/improve
        if label in ("bad", "improve"):
            sym = r.get("symbol")
            if sym and symbol_re.fullmatch(sym.upper()):
                _dedupe_push(bad_symbols_set, sym.upper())
            regime = r.get("regime")
            if isinstance(regime, str):
                low_regime = regime.lower()
                for kw in regime_keywords:
                    if kw in low_regime:
                        _dedupe_push(bad_regimes_set, kw)

    # Extract from patterns and warnings
    for entry in list(patterns) + list(warnings):
        if not isinstance(entry, str):
            continue
        for m in symbol_re.findall(entry.upper()):
            _dedupe_push(bad_symbols_set, m)
        lower_entry = entry.lower()
        for kw in regime_keywords:
            if kw in lower_entry:
                _dedupe_push(bad_regimes_set, kw)

    summary = {
        "generated_at": dream_output.get("generated_at", datetime.now(timezone.utc).isoformat()),
        "model": dream_output.get("model"),
        "bad_symbols": bad_symbols_set,
        "bad_regimes": bad_regimes_set,
        "patterns": patterns,
        "warnings": warnings,
        "scenario_count": len(reviews),
    }

    notes: List[str] = summary.setdefault("notes", [])
    notes.append("Advisory-only dream summary; no auto-apply.")
    if stub_reason:
        notes.append("stub_or_failed")

    return summary


def main() -> None:
    # Step 0: Guard — only run Dream when enough new closes are available
    allowed, _ = should_run_dream()
    if not allowed:
        return

    # Step 1: Optionally skip heavy pre-work if DREAM_ONLY is set (saves tokens)
    dream_only = os.getenv("DREAM_ONLY", "false").lower() == "true"
    if not dream_only:
        # Run tuner cycle (which also refreshes reflection & tuner files)
        run_tuner_cycle.main()

    # Step 2: Build Dream input
    build_dream_input.main()

    dream_input = load_json(DREAM_INPUT_PATH)
    if not dream_input:
        print(f"❌ Failed to load dream_input.json at {DREAM_INPUT_PATH}")
        return

    # Step 3: Try GPT Dream, fall back to stub
    dream_output = call_gpt_dream(dream_input)
    stub_reason: Optional[str] = None
    if dream_output is None:
        dream_output = build_stub_dream_output(dream_input)
        stub_reason = "stub_or_failed"
    
    GPT_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    DREAM_OUTPUT_PATH.write_text(json.dumps(dream_output, indent=2, sort_keys=True))

    # Write advisory summary for downstream consumers
    summary = build_dream_summary(dream_output, stub_reason=stub_reason)
    DREAM_SUMMARY_PATH.write_text(json.dumps(summary, indent=2, sort_keys=True))

    print("✅ Dream cycle complete.")
    print(f"   Input : {DREAM_INPUT_PATH}")
    print(f"   Output: {DREAM_OUTPUT_PATH}")
    print(f"   Reviewed {len(dream_output.get('scenario_reviews', []))} scenarios")
    print(f"   Summary: {DREAM_SUMMARY_PATH}")


if __name__ == "__main__":
    main()


