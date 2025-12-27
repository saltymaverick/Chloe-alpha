from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine_alpha.core.paths import REPORTS, CONFIG
from engine_alpha.core.gpt_client import query_gpt
from engine_alpha.overseer.staleness_analyst import (
    STALENESS_REPORT_PATH,
    build_staleness_report,
)

SCORECARD_PATH = REPORTS / "scorecards" / "asset_scorecards.json"
OVERSEER_PATH = REPORTS / "research" / "overseer_report.json"
TRADING_ENABLEMENT_PATH = CONFIG / "trading_enablement.json"
ACTIVITY_REFLECTIONS_PATH = REPORTS / "research" / "activity_reflections.jsonl"
SIGNAL_CONTEXT_PATH = REPORTS / "research" / "signal_context.json"
GATE_CONTEXT_PATH = REPORTS / "research" / "gate_context.json"
MARKET_STATE_PATH = REPORTS / "research" / "market_state_summary.json"


def _safe_load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = path.read_text().strip()
        return json.loads(data) if data else {}
    except Exception:
        return {}


def _load_staleness_report() -> Dict[str, Any]:
    data = _safe_load_json(STALENESS_REPORT_PATH)
    if data:
        return data
    # Try building a fresh report if missing
    try:
        return build_staleness_report()
    except Exception:
        return {}


def build_activity_context() -> Dict[str, Any]:
    staleness = _load_staleness_report()
    scorecards_raw = _safe_load_json(SCORECARD_PATH)
    overseer = _safe_load_json(OVERSEER_PATH)
    trading = _safe_load_json(TRADING_ENABLEMENT_PATH)
    signal_context = _safe_load_json(SIGNAL_CONTEXT_PATH)
    gate_context = _safe_load_json(GATE_CONTEXT_PATH)
    market_state = _safe_load_json(MARKET_STATE_PATH)

    scorecards = {
        row.get("symbol", "").upper(): row
        for row in scorecards_raw.get("assets", [])
        if row.get("symbol")
    }
    enabled_assets = [sym.upper() for sym in trading.get("enabled_for_trading", [])]

    context = {
        "phase": trading.get("phase", "unknown"),
        "enabled_assets": enabled_assets,
        "staleness": staleness,
        "scorecards": scorecards,
        "overseer": overseer.get("assets", {}),
        "signal_context": signal_context,
        "gate_context": gate_context,
        "market_state": market_state.get("assets", {}),
    }
    return context


def _summarize_asset(symbol: str, context: Dict[str, Any]) -> str:
    sym = symbol.upper()
    staleness_assets = context.get("staleness", {}).get("assets", {})
    signal_assets = context.get("signal_context", {}).get("assets", {})
    gate_assets = context.get("gate_context", {}).get("assets", {})

    info = staleness_assets.get(sym, {})
    hours = info.get("hours_since_last_trade")
    if hours is None:
        last_phrase = "no trades recorded"
    else:
        days = round(hours / 24.0, 2)
        last_phrase = f"{hours:.1f}h (~{days}d) since last trade"
    pf = info.get("pf")
    pf_str = "—" if pf is None else f"{pf:.2f}"
    feed = info.get("feed_state", "unknown")
    classification = info.get("classification", "unknown")
    suggestion = info.get("suggestion", "wait_and_observe")
    return (
        f"{symbol}: {last_phrase}, feed={feed}, PF={pf_str}, "
        f"classification={classification}, suggestion={suggestion}"
    )

    sig_info = signal_assets.get(sym, {})
    reg_counts = sig_info.get("regime_counts", {})
    if reg_counts:
        top_regime = max(reg_counts, key=reg_counts.get)
        base += f", regimes≈{top_regime}"
    avg_conf = sig_info.get("avg_conf")
    if isinstance(avg_conf, (int, float)):
        base += f", avg_conf={avg_conf:.2f}"
    avg_edge = sig_info.get("avg_edge")
    if isinstance(avg_edge, (int, float)):
        base += f", avg_edge={avg_edge:.3f}"

    gate_info = gate_assets.get(sym, {})
    gate_counts = gate_info.get("gate_counts", {})
    if gate_counts:
        top_gate = max(gate_counts, key=gate_counts.get)
        base += f", gates:{top_gate} x{gate_counts.get(top_gate)}"
    last_gate = gate_info.get("last_block", {}).get("gate_stage")
    if last_gate:
        base += f" (last={last_gate})"

    return base


def build_activity_prompt(context: Dict[str, Any]) -> str:
    enabled = context.get("enabled_assets", [])

    lines: List[str] = []
    lines.append("You are Chloe's quant reflection module.")
    lines.append("Explain recent trading activity/staleness per asset.")
    lines.append(
        "Differentiate between feed issues, chop/no-edge regimes, overly strict thresholds, "
        "or assets that are correctly idle."
    )
    lines.append(f"Current phase: {context.get('phase', 'unknown')}")
    lines.append(f"Enabled assets: {', '.join(enabled) if enabled else 'None'}")
    lines.append("")
    lines.append("Enabled asset summaries:")
    if enabled:
        for sym in enabled:
            lines.append(f"- { _summarize_asset(sym, context) }")
    else:
        lines.append("- None enabled right now.")

    disabled = [
        sym
        for sym in context.get("staleness", {}).get("assets", {}).keys()
        if sym not in enabled
    ]
    if disabled:
        lines.append("")
        lines.append("Key disabled assets & status:")
        for sym in disabled:
            lines.append(f"- { _summarize_asset(sym, context) }")

    lines.append("")
    lines.append(
        "Deliver a concise memo covering: "
        "(1) why each enabled asset is active or idle, "
        "(2) whether feeds or regimes are blocking trades, "
        "(3) any recommended adjustments (threshold tweaks, feed fixes, enabling/disabling), "
        "(4) which assets deserve attention next."
    )
    lines.append("Keep it under ~250 words. Use plain language, cite PF and staleness data.")

    return "\n".join(lines)


def _call_chloe(prompt_payload: Dict[str, Any]) -> Optional[str]:
    try:
        from engine_alpha.core.chloe_core import think

        result = think(prompt_payload)
        if isinstance(result, str):
            return result
        return json.dumps(result, indent=2)
    except Exception:
        pass

    # Fallback to direct GPT client
    try:
        task = prompt_payload.get("task", "")
        context_blob = json.dumps(prompt_payload.get("context", {}), indent=2)
        prompt = f"{task}\n\nContext:\n{context_blob}"
        response = query_gpt(prompt, "activity_reflection")
        if not response:
            return None
        return response.get("text") or json.dumps(response, indent=2)
    except Exception:
        return None


def _fallback_summary(context: Dict[str, Any]) -> str:
    enabled = context.get("enabled_assets", [])
    lines = ["GPT unavailable. Summary based on telemetry:"]
    assets = context.get("staleness", {}).get("assets", {})
    targets = enabled or list(assets.keys())
    if not targets:
        lines.append("- No asset telemetry available.")
        return "\n".join(lines)
    for sym in targets:
        lines.append(f"- {_summarize_asset(sym, context)}")
    return "\n".join(lines)


def _append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(record) + "\n")


def run_activity_reflection(use_gpt: bool = True) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    context = build_activity_context()
    prompt_text = build_activity_prompt(context)
    prompt_payload = {
        "role": "activity_reflection",
        "task": prompt_text,
        "context": context,
    }

    reflection_text: Optional[str] = None
    if use_gpt:
        reflection_text = _call_chloe(prompt_payload)
    if not reflection_text:
        reflection_text = _fallback_summary(context)

    record = {
        "ts": now.isoformat(),
        "phase": context.get("phase"),
        "enabled_assets": context.get("enabled_assets", []),
        "reflection": reflection_text,
        "prompt": prompt_text,
        "raw_context": {
            "staleness": context.get("staleness", {}).get("assets", {}),
            "scorecards": context.get("scorecards", {}),
            "signal_context": context.get("signal_context", {}).get("assets", {}),
            "gate_context": context.get("gate_context", {}).get("assets", {}),
        },
    }

    _append_jsonl(ACTIVITY_REFLECTIONS_PATH, record)
    return record


__all__ = [
    "build_activity_context",
    "build_activity_prompt",
    "run_activity_reflection",
]

