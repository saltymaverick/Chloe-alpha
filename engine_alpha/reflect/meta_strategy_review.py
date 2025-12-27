"""
Meta-strategy self-critique pass for Ops Mode Plus.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import List

ROOT_DIR = Path(__file__).resolve().parents[2]
REPORTS_DIR = ROOT_DIR / "reports"
RESEARCH_DIR = REPORTS_DIR / "research"


def _tail_jsonl(path: Path, n: int = 3) -> List[dict]:
    if not path.exists():
        return []
    lines = path.read_text().strip().splitlines()
    output: List[dict] = []
    for line in lines[-n:]:
        try:
            output.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return output


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _regime_state(drift_report: dict, regime: str) -> str:
    states = []
    for symbol_data in drift_report.get("symbols", {}).values():
        entry = symbol_data.get(regime)
        if entry and "state" in entry:
            states.append(entry["state"])
    if not states:
        return "unknown"
    state_counts = Counter(states)
    return state_counts.most_common(1)[0][0]


def run_meta_strategy_review(
    reflections_path: Path = RESEARCH_DIR / "meta_strategy_reflections.jsonl",
    asset_scorecards_path: Path = REPORTS_DIR / "scorecards" / "asset_scorecards.json",
    drift_report_path: Path = RESEARCH_DIR / "regime_drift_report.json",
    output_path: Path = RESEARCH_DIR / "meta_strategy_review.jsonl",
    trading_enablement_path: Path = ROOT_DIR / "config" / "trading_enablement.json",
) -> Path | None:
    reflections = _tail_jsonl(reflections_path, n=3)
    if not reflections:
        return None

    asset_scores = _load_json(asset_scorecards_path).get("assets", [])
    asset_map = {row["symbol"]: row for row in asset_scores}
    drift_report = _load_json(drift_report_path)
    trading_cfg = _load_json(trading_enablement_path)
    trading_enabled = [s.upper() for s in trading_cfg.get("enabled_for_trading", [])]

    records = []
    for ref in reflections:
        raw_text = ""
        if isinstance(ref.get("reflection"), dict):
            raw_text = ref["reflection"].get("raw_text", "")
        elif isinstance(ref.get("reflection"), str):
            raw_text = ref["reflection"]

        assessment = "neutral"
        note = "Insufficient evidence."

        if "high vol" in raw_text.lower() or "high_vol" in raw_text.lower():
            state = _regime_state(drift_report, "high_vol")
            if state == "strengthening":
                assessment = "helpful"
                note = "High volatility edge strengthening per drift monitor."
            elif state == "weakening":
                assessment = "not_helpful"
                note = "High volatility edge weakening despite recommendation."

        elif "trend" in raw_text.lower():
            state = _regime_state(drift_report, "trend_up")
            if state == "weakening":
                assessment = "helpful"
                note = "Trend regimes remain weak; avoiding them was prudent."
            elif state == "strengthening":
                assessment = "not_helpful"
                note = "Trend regimes improving; recommendation may need revisiting."

        elif trading_enabled:
            symbol = trading_enabled[0]
            pf_val = asset_map.get(symbol, {}).get("pf")
            if isinstance(pf_val, (int, float)) and pf_val >= 1.0:
                assessment = "helpful"
                note = f"{symbol} PF improved to {pf_val:.2f}."
            elif isinstance(pf_val, (int, float)):
                assessment = "neutral"
                note = f"{symbol} PF currently {pf_val:.2f}."

        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "reflection_ts": ref.get("ts"),
            "assessment": assessment,
            "notes": note,
        }
        records.append(record)

    if not records:
        return None

    with output_path.open("a") as handle:
        for entry in records:
            handle.write(json.dumps(entry) + "\n")

    return output_path

