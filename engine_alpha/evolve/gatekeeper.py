"""
Gatekeeper - Decides whether automation is allowed to proceed.

The gatekeeper evaluates:
- System sanity status
- PF thresholds
- Risk constraints

All decisions are ADVISORY ONLY - no automatic actions.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
SYSTEM_REPORT_DIR = ROOT / "reports" / "system"
SANITY_REPORT_PATH = SYSTEM_REPORT_DIR / "sanity_report.json"
GATEKEEPER_REPORT_PATH = SYSTEM_REPORT_DIR / "gatekeeper_report.json"
GPT_REPORT_DIR = ROOT / "reports" / "gpt"
REFLECTION_INPUT_PATH = GPT_REPORT_DIR / "reflection_input.json"
CONFIG_DIR = ROOT / "config"
TUNING_RULES_PATH = CONFIG_DIR / "tuning_rules.yaml"


def safe_load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file safely."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def safe_load_yaml(path: Path) -> Dict[str, Any]:
    """Load YAML file safely."""
    if not path.exists():
        return {}
    try:
        import yaml
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


def load_sanity_report() -> Dict[str, Any]:
    """
    Load sanity report.
    
    Returns:
        Sanity report dict, or empty dict if missing
    """
    return safe_load_json(SANITY_REPORT_PATH)


def load_pf_summary() -> Dict[str, Dict[str, Any]]:
    """
    Load PF summary from reflection_input.json.
    
    Returns:
        Dict mapping symbol -> {exp_pf, exp_trades, norm_pf, norm_trades}
    """
    reflection_input = safe_load_json(REFLECTION_INPUT_PATH)
    symbols_data = reflection_input.get("symbols", {})
    
    pf_summary: Dict[str, Dict[str, Any]] = {}
    
    for symbol, data in symbols_data.items():
        pf_summary[symbol] = {
            "exp_pf": data.get("exploration_pf"),
            "exp_trades": data.get("exploration_trades", 0),
            "norm_pf": data.get("normal_pf"),
            "norm_trades": data.get("normal_trades", 0),
        }
    
    return pf_summary


def evaluate_gate_status() -> Dict[str, Any]:
    """
    Evaluate gate status based on sanity report and PF summary.
    
    Returns:
        Gate decision dict with:
            - sanity_ok: bool
            - pf_ok: bool
            - allow_automation: bool
            - reasons: List[str]
    """
    # Load sanity report
    sanity_report = load_sanity_report()
    
    # Check sanity status
    sanity_ok = False
    sanity_reasons: List[str] = []
    
    if not sanity_report:
        sanity_reasons.append("Sanity report missing - system may not be healthy")
    else:
        summary = sanity_report.get("summary", {})
        success = summary.get("success", False)
        
        if success:
            sanity_ok = True
            sanity_reasons.append("Sanity suite passed")
        else:
            errors = summary.get("errors", [])
            sanity_reasons.append(f"Sanity suite failed with {len(errors)} errors")
    
    # Check shadow mode
    shadow_mode = sanity_report.get("shadow_mode", {})
    shadow_enabled = shadow_mode.get("status", False)
    
    if not shadow_enabled:
        sanity_ok = False
        sanity_reasons.append("Shadow mode not enabled - safety check failed")
    
    # Load PF summary
    pf_summary = load_pf_summary()
    
    # Load thresholds from tuning_rules.yaml
    tuning_rules = safe_load_yaml(TUNING_RULES_PATH)
    
    # Default thresholds
    min_pf_for_automation = 1.0
    min_trades_for_automation = 5
    
    # Try to get thresholds from tuning_rules
    automation_section = tuning_rules.get("automation", {})
    if automation_section:
        min_pf_for_automation = automation_section.get("min_pf", min_pf_for_automation)
        min_trades_for_automation = automation_section.get("min_trades", min_trades_for_automation)
    
    # Evaluate PF status
    pf_ok = False
    pf_reasons: List[str] = []
    
    if not pf_summary:
        pf_reasons.append("PF summary missing - insufficient data")
    else:
        # Check Tier1 symbols (most important)
        tier1_symbols = []
        tier1_pf_ok = []
        
        # Get tiers from reflection_output if available
        reflection_output = safe_load_json(GPT_REPORT_DIR / "reflection_output.json")
        symbol_insights = reflection_output.get("symbol_insights", {})
        
        for symbol, data in symbol_insights.items():
            tier = data.get("tier", "tier2")
            if tier == "tier1":
                tier1_symbols.append(symbol)
        
        # If no tier1 symbols found, check all symbols
        if not tier1_symbols:
            tier1_symbols = list(pf_summary.keys())
        
        # Check PF for tier1 symbols
        for symbol in tier1_symbols:
            if symbol not in pf_summary:
                continue
            
            symbol_data = pf_summary[symbol]
            exp_pf = symbol_data.get("exp_pf")
            exp_trades = symbol_data.get("exp_trades", 0)
            
            if exp_pf is not None and exp_trades >= min_trades_for_automation:
                if exp_pf >= min_pf_for_automation:
                    tier1_pf_ok.append(symbol)
        
        if tier1_pf_ok:
            pf_ok = True
            pf_reasons.append(
                f"PF for Tier1 symbols above threshold ({min_pf_for_automation}) "
                f"and MinTrades ({min_trades_for_automation}) reached for {len(tier1_pf_ok)} symbols"
            )
        else:
            pf_reasons.append(
                f"Insufficient PF or trades for Tier1 symbols "
                f"(need PF>={min_pf_for_automation}, trades>={min_trades_for_automation})"
            )
    
    # Final decision
    allow_automation = sanity_ok and pf_ok
    
    # Combine reasons
    all_reasons = sanity_reasons + pf_reasons
    
    if allow_automation:
        all_reasons.append("All gates passed - automation allowed")
    else:
        all_reasons.append("One or more gates failed - automation blocked")
    
    return {
        "sanity_ok": sanity_ok,
        "pf_ok": pf_ok,
        "allow_automation": allow_automation,
        "reasons": all_reasons,
        "thresholds": {
            "min_pf": min_pf_for_automation,
            "min_trades": min_trades_for_automation,
        },
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


def save_gatekeeper_report(gate_status: Dict[str, Any]) -> Path:
    """
    Save gatekeeper report to JSON file.
    
    Args:
        gate_status: Gate status dict from evaluate_gate_status()
    
    Returns:
        Path to saved file
    """
    SYSTEM_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Normalize report shape - ensure it's always a dict
    if isinstance(gate_status, list):
        # Flatten list of entries into a single dict
        flattened = {}
        reasons = []
        for item in gate_status:
            if isinstance(item, dict):
                flattened.update(item)
            elif isinstance(item, str):
                reasons.append(item)
        if reasons:
            flattened.setdefault("reasons", []).extend(reasons)
        gate_status = flattened
    
    # Ensure required keys exist with safe defaults
    if not isinstance(gate_status, dict):
        gate_status = {}
    
    report = {
        "sanity_ok": bool(gate_status.get("sanity_ok", False)),
        "pf_ok": bool(gate_status.get("pf_ok", False)),
        "allow_automation": bool(gate_status.get("allow_automation", False)),
        "reasons": gate_status.get("reasons", []),
    }
    
    # Ensure reasons is always a list
    if not isinstance(report["reasons"], list):
        if isinstance(report["reasons"], str):
            report["reasons"] = [report["reasons"]]
        else:
            report["reasons"] = []
    
    # Preserve any additional keys (e.g., thresholds, evaluated_at)
    for key in ["thresholds", "evaluated_at"]:
        if key in gate_status:
            report[key] = gate_status[key]
    
    GATEKEEPER_REPORT_PATH.write_text(
        json.dumps(report, indent=2, sort_keys=True)
    )
    return GATEKEEPER_REPORT_PATH


