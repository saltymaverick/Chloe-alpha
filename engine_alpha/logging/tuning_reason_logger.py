"""
Tuning Reason Logger - Explainable GPT Tuning Intelligence.

This module captures structured explanations of why GPT Tuner v4 makes its proposals,
based on PF, drift, microstructure, execution quality, tiers, Dream patterns,
auto-rotation recommendations, and meta-reasoner warnings.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from engine_alpha.core.paths import REPORTS

TUNER_OUTPUT_PATH = REPORTS / "gpt" / "tuner_output.json"
ARE_PATH = REPORTS / "research" / "are_snapshot.json"
DRIFT_PATH = REPORTS / "research" / "drift_report.json"
MICRO_PATH = REPORTS / "research" / "microstructure_snapshot_15m.json"
EXEC_PATH = REPORTS / "research" / "execution_quality.json"
REFLECTION_PATH = REPORTS / "gpt" / "reflection_output.json"
ROTATION_PATH = REPORTS / "research" / "auto_rotation_recs.json"
META_PATH = REPORTS / "research" / "meta_reasoner_report.json"
LOG_PATH = REPORTS / "gpt" / "tuning_reason_log.jsonl"


def _load_json_or_empty(path: Path) -> Dict[str, Any]:
    """Load JSON file or return empty dict if missing/invalid."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def build_tuning_reason_entry() -> Dict[str, Any]:
    """
    Build a single tuning reason entry capturing the current tuner output + context.
    
    This is called after tuner_output.json has been written.
    
    Returns:
        Dict with ts, symbols, global_notes, meta_issues
    """
    tuner_output = _load_json_or_empty(TUNER_OUTPUT_PATH)
    proposals = tuner_output.get("proposals", {})
    
    # Load all context data
    are = _load_json_or_empty(ARE_PATH)
    are_symbols = are.get("symbols", are)
    
    drift = _load_json_or_empty(DRIFT_PATH).get("symbols", {})
    micro = _load_json_or_empty(MICRO_PATH)
    # Handle both formats: direct dict or wrapped with "symbols" key
    if isinstance(micro, dict) and "symbols" in micro:
        micro_symbols = micro.get("symbols", {})
    else:
        micro_symbols = micro
    
    execq = _load_json_or_empty(EXEC_PATH)
    reflection = _load_json_or_empty(REFLECTION_PATH)
    
    # Extract tiers from reflection output
    tiers = {}
    for tier_name, syms in reflection.get("tiers", {}).items():
        if isinstance(syms, list):
            for s in syms:
                tiers[s] = tier_name
    
    rotation = _load_json_or_empty(ROTATION_PATH)
    meta = _load_json_or_empty(META_PATH)
    
    issues = meta.get("issues", [])
    
    ts = datetime.now(timezone.utc).isoformat()
    
    sym_reasons = {}
    
    for sym, props in proposals.items():
        reasons = []
        warnings = []
        
        tier = tiers.get(sym)
        drift_info = drift.get(sym, {})
        drift_status = drift_info.get("status", "unknown")
        
        are_stats = are_symbols.get(sym, {})
        short_pf = are_stats.get("short_exp_pf")
        long_pf = are_stats.get("long_exp_pf")
        
        micro_info = micro_symbols.get(sym, {})
        # Handle both formats: direct dict or wrapped with micro_regime/metrics
        if isinstance(micro_info, dict):
            if "micro_regime" in micro_info:
                micro_regime = micro_info.get("micro_regime", "unknown")
            elif "metrics" in micro_info:
                micro_regime = micro_info.get("metrics", {}).get("micro_regime", "unknown")
            else:
                # Try to find regime in any nested structure
                micro_regime = micro_info.get("micro_regime", "unknown")
        else:
            micro_regime = "unknown"
        
        exec_info = execq.get(sym, {})
        exec_label = "unknown"
        if exec_info and isinstance(exec_info, dict):
            # Pick one regime (any) - execution quality is per-regime
            for reg, info in exec_info.items():
                if isinstance(info, dict):
                    exec_label = info.get("label", "unknown")
                    if exec_label != "unknown":
                        break
        
        rot_info = rotation.get(sym, {})
        if isinstance(rot_info, dict):
            rot_decision = rot_info.get("rotation", "hold")
        else:
            rot_decision = "hold"
        
        # Add reasons based on each component
        if tier:
            reasons.append(f"Tier: {tier}")
        
        if short_pf not in (None, "—", "N/A"):
            try:
                short_pf_val = float(short_pf)
                reasons.append(f"Short-horizon PF: {short_pf_val:.2f}")
            except (ValueError, TypeError):
                pass
        
        if long_pf not in (None, "—", "N/A"):
            try:
                long_pf_val = float(long_pf)
                reasons.append(f"Long-horizon PF: {long_pf_val:.2f}")
            except (ValueError, TypeError):
                pass
        
        if drift_status != "unknown":
            reasons.append(f"Drift status: {drift_status}")
        
        if micro_regime != "unknown":
            reasons.append(f"Microstructure regime: {micro_regime}")
        
        if exec_label != "unknown":
            reasons.append(f"Execution quality: {exec_label}")
        
        if rot_decision != "hold":
            reasons.append(f"Rotation recommendation: {rot_decision}")
        
        # Check if symbol is in meta issues
        for issue in issues:
            issue_symbols = issue.get("symbols", [])
            if isinstance(issue_symbols, list) and sym in issue_symbols:
                issue_type = issue.get("type") or issue.get("id", "unknown")
                warnings.append(f"Meta issue: {issue_type}")
        
        sym_reasons[sym] = {
            "tier": tier,
            "drift": drift_status,
            "short_pf": short_pf,
            "long_pf": long_pf,
            "micro_regime": micro_regime,
            "exec_label": exec_label,
            "rotation": rot_decision,
            "proposal": props,
            "reasons": reasons,
            "warnings": warnings,
        }
    
    # Global commentary
    global_notes = []
    
    # Simple global summary
    tier1_syms = [s for s, t in tiers.items() if t == "tier1"]
    tier3_syms = [s for s, t in tiers.items() if t == "tier3"]
    
    if tier1_syms:
        global_notes.append(f"Tier1 symbols: {', '.join(sorted(tier1_syms))}")
    if tier3_syms:
        global_notes.append(f"Tier3 symbols: {', '.join(sorted(tier3_syms))}")
    
    return {
        "ts": ts,
        "symbols": sym_reasons,
        "global_notes": global_notes,
        "meta_issues": issues,
    }


def append_tuning_reason_entry() -> bool:
    """
    Build and append a tuning reason entry to the log file.
    
    Returns:
        True if successful, False otherwise
    """
    try:
        entry = build_tuning_reason_entry()
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        return True
    except Exception as exc:
        print(f"[TuningReasonLog] Failed to append tuning reason entry: {exc}")
        import traceback
        traceback.print_exc()
        return False


def load_last_tuning_reason() -> Optional[Dict[str, Any]]:
    """
    Load the most recent tuning reason entry from the log.
    
    Returns:
        Dict with tuning reason data or None if not available
    """
    if not LOG_PATH.exists():
        return None
    
    try:
        lines = LOG_PATH.read_text().strip().splitlines()
        if not lines:
            return None
        last = json.loads(lines[-1])
        return last
    except Exception:
        return None

