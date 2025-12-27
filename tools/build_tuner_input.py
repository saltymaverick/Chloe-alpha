"""
Build tuner input from reflection input and output.

This merges raw stats, reflection insights, and gate behavior into
a single structured file that GPT Tuner will consume.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
GPT_REPORT_DIR = ROOT / "reports" / "gpt"
REFLECTION_INPUT_PATH = GPT_REPORT_DIR / "reflection_input.json"
REFLECTION_OUTPUT_PATH = GPT_REPORT_DIR / "reflection_output.json"
TUNER_INPUT_PATH = GPT_REPORT_DIR / "tuner_input.json"


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def main() -> None:
    GPT_REPORT_DIR.mkdir(parents=True, exist_ok=True)

    reflection_input = load_json(REFLECTION_INPUT_PATH)
    reflection_output = load_json(REFLECTION_OUTPUT_PATH)

    if not reflection_input:
        print(f"❌ reflection_input.json missing or empty at {REFLECTION_INPUT_PATH}")
        return

    # If reflection_output is missing, use an empty stub.
    if not reflection_output:
        print(f"⚠️ reflection_output.json missing or empty at {REFLECTION_OUTPUT_PATH}, using stub tiers.")
        reflection_output = {
            "tiers": {
                "tier1": [],
                "tier2": [],
                "tier3": [],
            },
            "symbol_insights": {}
        }

    symbols_stats = reflection_input.get("symbols", {})
    gate_stats = reflection_input.get("gates", {})
    open_positions = reflection_input.get("open_positions", [])
    engine_mode = reflection_input.get("engine_mode", os.environ.get("ENGINE_MODE", "PAPER"))

    tiers = reflection_output.get("tiers", {})
    sym_insights = reflection_output.get("symbol_insights", {})

    # Build per-symbol tuner view
    tuner_symbols: Dict[str, Dict[str, Any]] = {}

    for sym, stats in symbols_stats.items():
        # Reflection tier & insight
        # Handle both v1 format (dict with tier/comment/actions) and v2 format (list of insight strings)
        ref_info = sym_insights.get(sym, {})
        
        # Determine tier: check if ref_info is a list (v2) or dict (v1)
        if isinstance(ref_info, list):
            # v2 format: list of insight strings, tier comes from tiers dict
            tier = "tier2"  # default
            for tier_name, symbol_list in tiers.items():
                if sym in symbol_list:
                    tier = tier_name
                    break
            comment = " | ".join(ref_info) if ref_info else ""
            actions = []  # v2 doesn't provide actions
        elif isinstance(ref_info, dict):
            # v1 format: dict with tier/comment/actions
            tier = ref_info.get("tier", "tier2")
            comment = ref_info.get("comment", "")
            actions = ref_info.get("actions", [])
        else:
            # Fallback: try to get tier from tiers dict
            tier = "tier2"
            for tier_name, symbol_list in tiers.items():
                if sym in symbol_list:
                    tier = tier_name
                    break
            comment = ""
            actions = []

        gates = gate_stats.get(sym, {})
        
        # Load Phase 5 data (drift) if available
        drift_data = reflection_input.get("drift", {})
        symbol_drift = drift_data.get(sym, {}) if isinstance(drift_data, dict) else {}

        tuner_symbols[sym] = {
            "tier": tier,
            "reflection_comment": comment,
            "reflection_actions": actions,

            "exp_trades": stats.get("exp_trades", 0),
            "exp_pf": stats.get("exp_pf"),
            "norm_trades": stats.get("norm_trades", 0),
            "norm_pf": stats.get("norm_pf"),

            "bars": stats.get("bars", 0),
            "exploration_bars": stats.get("exploration_bars", 0),
            "can_open_bars": stats.get("can_open_bars", 0),

            "gate_stats": {
                "blocked_regime": gates.get("blocked_regime", 0),
                "blocked_confidence": gates.get("blocked_confidence", 0),
                "blocked_edge": gates.get("blocked_edge", 0),
                "allowed_exploration": gates.get("allowed_exploration", 0),
            },
        }
        
        # Add drift data if available
        if symbol_drift:
            tuner_symbols[sym]["drift"] = symbol_drift

    # Build a small view of current open positions so Tuner can reason about risk usage
    tuner_open_positions = open_positions

    # Load Phase 5 data (correlation, alpha/beta) if available
    correlation_data = reflection_input.get("correlation", {})
    alpha_beta_data = reflection_input.get("alpha_beta", {})
    
    # Load microstructure data if available
    microstructure_data = reflection_input.get("microstructure", {})
    
    now = datetime.now(timezone.utc).isoformat()
    tuner_input = {
        "generated_at": now,
        "engine_mode": engine_mode,
        "tiers": tiers,
        "symbols": tuner_symbols,
        "open_positions": tuner_open_positions,
        "notes": [
            "This file is the input for GPT Tuner.",
            "It combines raw statistics (exploration & normal PF), gate behavior, reflection tiers, and open positions.",
            "Tuner should propose SMALL, SAFE adjustments (deltas) per symbol & regime, not rewrite configs from scratch."
        ],
    }
    
    # Add Phase 5 data if available
    if correlation_data:
        tuner_input["correlation"] = correlation_data
    if alpha_beta_data:
        tuner_input["alpha_beta"] = alpha_beta_data
    
    # Add microstructure data if available
    if microstructure_data:
        tuner_input["microstructure"] = microstructure_data

    TUNER_INPUT_PATH.write_text(json.dumps(tuner_input, indent=2, sort_keys=True))
    print(f"✅ Tuner input written to: {TUNER_INPUT_PATH}")


if __name__ == "__main__":
    main()


