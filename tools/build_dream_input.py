"""
Build Dream/Replay input from reflection and tuner outputs.

Selects interesting trade scenarios for GPT Dream to replay and analyze.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
GPT_REPORT_DIR = ROOT / "reports" / "gpt"

REFLECTION_INPUT_PATH = GPT_REPORT_DIR / "reflection_input.json"
REFLECTION_OUTPUT_PATH = GPT_REPORT_DIR / "reflection_output.json"
TUNER_OUTPUT_PATH = GPT_REPORT_DIR / "tuner_output.json"
DREAM_INPUT_PATH = GPT_REPORT_DIR / "dream_input.json"


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def pick_scenarios(recent_trades: List[Dict[str, Any]], max_scenarios: int = 25) -> List[Dict[str, Any]]:
    """
    Pick interesting trades to replay:
      - a mix of worst losers and best winners
      - across exploration and normal
    """
    closes = [t for t in recent_trades if t.get("pct") is not None]

    # Split exploration vs normal
    expl_closes = [t for t in closes if t.get("trade_kind") == "exploration"]
    norm_closes = [t for t in closes if t.get("trade_kind") == "normal"]

    # Sort by pct ascending (worst to best)
    expl_sorted = sorted(expl_closes, key=lambda t: float(t["pct"]))
    norm_sorted = sorted(norm_closes, key=lambda t: float(t["pct"]))

    scenarios: List[Dict[str, Any]] = []

    # Take worst exploration losers
    scenarios.extend(expl_sorted[:10])

    # Take best exploration winners
    expl_sorted_desc = list(reversed(expl_sorted))
    scenarios.extend(expl_sorted_desc[:10])

    # Take a few normal trades (both good and bad) for context
    scenarios.extend(norm_sorted[:3])
    norm_sorted_desc = list(reversed(norm_sorted))
    scenarios.extend(norm_sorted_desc[:3])

    # Deduplicate while preserving order (by symbol+time)
    seen_keys = set()
    unique_scenarios: List[Dict[str, Any]] = []
    for t in scenarios:
        key = (t.get("symbol"), t.get("time"))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique_scenarios.append(t)

    return unique_scenarios[:max_scenarios]


def main() -> None:
    GPT_REPORT_DIR.mkdir(parents=True, exist_ok=True)

    reflection_input = load_json(REFLECTION_INPUT_PATH)
    reflection_output = load_json(REFLECTION_OUTPUT_PATH)
    tuner_output = load_json(TUNER_OUTPUT_PATH)

    if not reflection_input:
        print(f"❌ reflection_input.json missing or empty at {REFLECTION_INPUT_PATH}")
        return

    engine_mode = reflection_input.get("engine_mode", "PAPER")
    symbols_stats = reflection_input.get("symbols", {})
    recent_trades = reflection_input.get("recent_trades", [])
    gate_stats = reflection_input.get("gates", {})
    open_positions = reflection_input.get("open_positions", [])

    tiers = reflection_output.get("tiers", {})
    symbol_insights = reflection_output.get("symbol_insights", {})
    tuning_proposals = tuner_output.get("tuning_proposals", {})

    # Build per-symbol combined context for Dream
    dream_symbols: Dict[str, Dict[str, Any]] = {}
    for sym, stats in symbols_stats.items():
        # Handle both v1 format (dict with tier/comment/actions) and v2 format (list of insight strings)
        ref_info = symbol_insights.get(sym, {})
        
        # Determine tier and comment: check if ref_info is a list (v2) or dict (v1)
        if isinstance(ref_info, list):
            # v2 format: list of insight strings, tier comes from tiers dict
            tier = "tier2"  # default
            for tier_name, symbol_list in tiers.items():
                if sym in symbol_list:
                    tier = tier_name
                    break
            reflection_comment = " | ".join(ref_info) if ref_info else ""
            reflection_actions = []  # v2 doesn't provide actions
        elif isinstance(ref_info, dict):
            # v1 format: dict with tier/comment/actions
            tier = ref_info.get("tier", "tier2")
            reflection_comment = ref_info.get("comment", "")
            reflection_actions = ref_info.get("actions", [])
        else:
            # Fallback: try to get tier from tiers dict
            tier = "tier2"
            for tier_name, symbol_list in tiers.items():
                if sym in symbol_list:
                    tier = tier_name
                    break
            reflection_comment = ""
            reflection_actions = []
        
        gates = gate_stats.get(sym, {})
        proposals = tuning_proposals.get(sym, {})

        dream_symbols[sym] = {
            "tier": tier,
            "stats": stats,
            "gate_stats": gates,
            "reflection_comment": reflection_comment,
            "reflection_actions": reflection_actions,
            "tuning_proposals": proposals,
        }

    scenarios = pick_scenarios(recent_trades, max_scenarios=25)

    # Load microstructure data if available (for v4)
    microstructure_path = ROOT / "reports" / "research" / "microstructure_snapshot_15m.json"
    microstructure_data = {}
    if microstructure_path.exists():
        try:
            micro_snapshot = json.loads(microstructure_path.read_text())
            microstructure_data = micro_snapshot.get("symbols", {})
        except Exception:
            pass
    
    # Load other research inputs if available
    reflection_input_full = load_json(REFLECTION_INPUT_PATH)
    drift_data = reflection_input_full.get("drift", {})
    correlation_data = reflection_input_full.get("correlation", {})
    alpha_beta_data = reflection_input_full.get("alpha_beta", {})
    
    now = datetime.now(timezone.utc).isoformat()
    dream_input = {
        "generated_at": now,
        "engine_mode": engine_mode,
        "symbols": dream_symbols,
        "tiers": tiers,
        "open_positions": open_positions,
        "scenarios": scenarios,
        "notes": [
            "This file is the input for GPT Dream/Replay.",
            "Each scenario corresponds to one closed trade, with pct, kind, regime, and other metadata.",
            "GPT Dream should imagine how these trades might behave under proposed tuning changes.",
        ],
    }
    
    # Add research data if available (for v4)
    if microstructure_data:
        dream_input["microstructure"] = microstructure_data
    if drift_data:
        dream_input["drift"] = drift_data
    if correlation_data:
        dream_input["correlation"] = correlation_data
    if alpha_beta_data:
        dream_input["alpha_beta"] = alpha_beta_data

    DREAM_INPUT_PATH.write_text(json.dumps(dream_input, indent=2, sort_keys=True))
    print(f"✅ Dream input written to: {DREAM_INPUT_PATH}")
    print(f"   Selected {len(scenarios)} scenario trades for replay")


if __name__ == "__main__":
    main()


