from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine_alpha.core.paths import REPORTS, CONFIG
from engine_alpha.core.gpt_client import query_gpt

REFLECTION_LOG = REPORTS / "research" / "activity_reflections.jsonl"
META_LOG = REPORTS / "research" / "activity_meta_reflections.jsonl"
STALENESS_PATH = REPORTS / "research" / "staleness_overseer.json"
SCORECARD_PATH = REPORTS / "scorecards" / "asset_scorecards.json"
OVERSEER_PATH = REPORTS / "research" / "overseer_report.json"
TRADING_ENABLEMENT_PATH = CONFIG / "trading_enablement.json"
SIGNAL_CONTEXT_PATH = REPORTS / "research" / "signal_context.json"
GATE_CONTEXT_PATH = REPORTS / "research" / "gate_context.json"
HINDSIGHT_PATH = REPORTS / "research" / "hindsight_reviews.jsonl"

MAX_REFLECTION_HISTORY = 7


def _safe_load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = path.read_text().strip()
        return json.loads(data) if data else {}
    except Exception:
        return {}


def _load_recent_activity_reflections(limit: int = MAX_REFLECTION_HISTORY) -> List[Dict[str, Any]]:
    if not REFLECTION_LOG.exists():
        return []
    try:
        lines = REFLECTION_LOG.read_text().splitlines()
    except Exception:
        return []
    reflections: List[Dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            reflections.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return reflections


def build_meta_context() -> Dict[str, Any]:
    trading = _safe_load_json(TRADING_ENABLEMENT_PATH)
    staleness = _safe_load_json(STALENESS_PATH)
    scorecards_raw = _safe_load_json(SCORECARD_PATH)
    overseer = _safe_load_json(OVERSEER_PATH)
    reflections = _load_recent_activity_reflections()
    signal_context = _safe_load_json(SIGNAL_CONTEXT_PATH)
    gate_context = _safe_load_json(GATE_CONTEXT_PATH)

    hindsight_reviews: List[Dict[str, Any]] = []
    if Path(HINDSIGHT_PATH).exists():
        try:
            lines = Path(HINDSIGHT_PATH).read_text().splitlines()
            for line in lines[-20:]:
                try:
                    hindsight_reviews.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except Exception:
            pass

    scorecards = {
        row.get("symbol", "").upper(): row
        for row in scorecards_raw.get("assets", [])
        if row.get("symbol")
    }

    context = {
        "phase": trading.get("phase", "unknown"),
        "enabled_assets": trading.get("enabled_for_trading", []),
        "recent_activity_reflections": reflections,
        "staleness_snapshot": staleness,
        "scorecards": scorecards,
        "overseer_assets": overseer.get("assets", {}),
        "signal_context": signal_context,
        "gate_context": gate_context,
        "hindsight_reviews": hindsight_reviews,
    }
    return context


def build_meta_prompt(context: Dict[str, Any]) -> str:
    reflections = context.get("recent_activity_reflections", [])
    enabled = context.get("enabled_assets", [])
    staleness_assets = context.get("staleness_snapshot", {}).get("assets", {})
    signal_context = context.get("signal_context", {}).get("assets", {})
    gate_context = context.get("gate_context", {}).get("assets", {})
    hindsight_reviews = context.get("hindsight_reviews", [])

    lines: List[str] = []
    lines.append("You are Chloe's temporal meta-reflection engine.")
    lines.append("Analyze your own activity & staleness patterns over multiple days.")
    lines.append(
        "Identify why assets stayed quiet or active, whether prior reflections were accurate, "
        "and what strategic focus you recommend for the next few days."
    )
    lines.append(f"Current phase: {context.get('phase', 'unknown')}")
    lines.append(f"Trading-enabled assets: {', '.join(enabled) if enabled else 'None'}")
    lines.append("")
    lines.append("Recent activity reflections:")
    if reflections:
        for ref in reflections:
            ts = ref.get("ts", "?")
            text = ref.get("reflection", "").strip().replace("\n", " ")
            lines.append(f"- {ts}: {text[:240]}{'...' if len(text) > 240 else ''}")
    else:
        lines.append("- (no prior reflections available)")

    if staleness_assets:
        lines.append("")
        lines.append("Current staleness snapshot (key assets):")
        for sym, info in staleness_assets.items():
            hours = info.get("hours_since_last_trade")
            status = "unknown" if hours is None else f"{hours:.1f}h idle"
            feed = info.get("feed_state", "unknown")
            classification = info.get("classification", "unknown")
            lines.append(f"- {sym}: {status}, feed={feed}, classification={classification}")

    if signal_context:
        lines.append("")
        lines.append("Recent signal context (selected assets):")
        for sym in enabled[:6]:
            ctx = signal_context.get(sym.upper())
            if not ctx:
                continue
            avg_conf = ctx.get("avg_conf")
            avg_edge = ctx.get("avg_edge")
            dominant_regime = None
            regimes = ctx.get("regime_counts", {})
            if regimes:
                dominant_regime = max(regimes, key=regimes.get)
            snippet = f"{sym}: avg_conf={avg_conf:.2f} avg_edge={avg_edge:.3f}" if isinstance(avg_conf, (int, float)) and isinstance(avg_edge, (int, float)) else f"{sym}: telemetry sparse"
            if dominant_regime:
                snippet += f", regimes≈{dominant_regime}"
            lines.append(f"- {snippet}")

    if gate_context:
        lines.append("")
        lines.append("Gate behavior snapshot (selected assets):")
        for sym in enabled[:6]:
            gates = gate_context.get(sym.upper())
            if not gates:
                continue
            gate_counts = gates.get("gate_counts", {})
            if gate_counts:
                top_gate = max(gate_counts, key=gate_counts.get)
                lines.append(f"- {sym}: dominant gate={top_gate} (counts={gate_counts})")

    if hindsight_reviews:
        lines.append("")
        lines.append("Recent hindsight coach notes:")
        for review in hindsight_reviews[-3:]:
            sym = review.get("symbol")
            pnl = review.get("pnl_pct")
            entry_eval = review.get("review", {}).get("entry_eval", {}).get("grade")
            exit_eval = review.get("review", {}).get("exit_eval", {}).get("grade")
            lines.append(f"- {sym}: pnl={pnl}, entry={entry_eval}, exit={exit_eval}")

    lines.append("")
    lines.append("Your tasks:")
    lines.append("1. Summarize how activity evolved over the last few reflections.")
    lines.append("2. Call out assets that remain idle despite healthy PF/feeds.")
    lines.append("3. Call out assets that were busy but underperforming.")
    lines.append("4. Highlight whether previous recommendations were followed or still pending.")
    lines.append("5. Suggest priorities for the next few days (watch, relax, fix feed, leave strict).")
    lines.append("Keep it concise (<300 words) and concrete.")

    return "\n".join(lines)


def _call_chloe(prompt_dict: Dict[str, Any]) -> Optional[str]:
    try:
        from engine_alpha.core.chloe_core import think

        result = think(prompt_dict)
        if isinstance(result, str):
            return result
        return json.dumps(result, indent=2)
    except Exception:
        pass

    try:
        task = prompt_dict.get("task", "")
        context_blob = json.dumps(prompt_dict.get("context", {}), indent=2)
        prompt = f"{task}\n\nContext:\n{context_blob}"
        response = query_gpt(prompt, "activity_meta_reflection")
        if not response:
            return None
        return response.get("text") or json.dumps(response, indent=2)
    except Exception:
        return None


def _fallback_meta_summary(context: Dict[str, Any]) -> str:
    reflections = context.get("recent_activity_reflections", [])
    staleness_assets = context.get("staleness_snapshot", {}).get("assets", {})
    lines = ["GPT unavailable. Summary based on recent reflections and staleness data:"]
    if reflections:
        last = reflections[-1]
        lines.append(f"- Latest reflection hint: {last.get('reflection', '')[:200]}")
    if staleness_assets:
        quiet = [
            sym
            for sym, info in staleness_assets.items()
            if info.get("classification") in ("maybe_too_strict", "low_activity_edge_ok")
        ]
        if quiet:
            lines.append(f"- Assets still quiet: {', '.join(quiet)}")
    return "\n".join(lines)


def _append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(record) + "\n")


def run_meta_reflection(use_gpt: bool = True) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    context = build_meta_context()
    prompt_text = build_meta_prompt(context)
    prompt_payload = {
        "role": "activity_meta_reflection",
        "task": prompt_text,
        "context": context,
    }

    reflection_text: Optional[str] = None
    if use_gpt:
        reflection_text = _call_chloe(prompt_payload)
    if not reflection_text:
        reflection_text = _fallback_meta_summary(context)

    record = {
        "ts": now.isoformat(),
        "phase": context.get("phase"),
        "reflection": reflection_text,
        "raw_context_summary": {
            "num_activity_reflections": len(context.get("recent_activity_reflections", [])),
            "enabled_assets": context.get("enabled_assets", []),
        },
    }
    _append_jsonl(META_LOG, record)
    return record


__all__ = [
    "build_meta_context",
    "build_meta_prompt",
    "run_meta_reflection",
]

