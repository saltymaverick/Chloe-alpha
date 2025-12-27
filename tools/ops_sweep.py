#!/usr/bin/env python3
"""
One-shot operational sweep for Chloe (reports + reflections).
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from engine_alpha.core.paths import REPORTS
from engine_alpha.metrics.scorecard_builder import (
    build_asset_scorecards,
    build_strategy_scorecards,
)
from engine_alpha.overseer.market_state_summarizer import summarize_market_state
from engine_alpha.overseer.quant_overseer import build_overseer_report
from engine_alpha.overseer.staleness_analyst import build_staleness_report
from engine_alpha.reflect.activity_meta_reflection import run_meta_reflection
from engine_alpha.reflect.activity_reflection import run_activity_reflection


FOCUS_SYMBOLS: List[str] = [
    "ETHUSDT",
    "BTCUSDT",
    "SOLUSDT",
    "DOGEUSDT",
    "AVAXUSDT",
    "MATICUSDT",
    "ATOMUSDT",
    "BNBUSDT",
    "DOTUSDT",
    "ADAUSDT",
    "LINKUSDT",
    "XRPUSDT",
]

SCORECARD_DIR = REPORTS / "scorecards"
ASSET_SCORECARDS_PATH = SCORECARD_DIR / "asset_scorecards.json"
STRATEGY_SCORECARDS_PATH = SCORECARD_DIR / "strategy_scorecards.json"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        text = path.read_text().strip()
        return {} if not text else json.loads(text)
    except Exception:
        return {}


def _preview_lines(text: str, max_lines: int) -> Iterable[str]:
    lines = text.strip().splitlines()
    for line in lines[:max_lines]:
        yield line
    if len(lines) > max_lines:
        yield "..."


def _summarize_assets(assets: Dict[str, Dict[str, Any]]) -> None:
    enabled = [sym for sym, info in assets.items() if info.get("trading_enabled")]
    feed_counts = Counter(info.get("feed_state", "unknown") for info in assets.values())
    class_counts = Counter(info.get("classification", "unknown") for info in assets.values())

    print(f"  - Phase assets enabled : {', '.join(enabled) if enabled else 'None'}")
    if feed_counts:
        feed_str = ", ".join(f"{state}={count}" for state, count in sorted(feed_counts.items()))
        print(f"  - Feed states          : {feed_str}")
    if class_counts:
        class_str = ", ".join(f"{cls}={count}" for cls, count in sorted(class_counts.items()))
        print(f"  - Staleness classes    : {class_str}")

    focus_lines: List[str] = []
    for sym in FOCUS_SYMBOLS:
        info = assets.get(sym)
        if not info:
            continue
        feed = info.get("feed_state", "unknown")
        classify = info.get("classification", "unknown")
        hours = info.get("hours_since_last_trade")
        idle = f"{hours:.1f}h" if isinstance(hours, (int, float)) else "n/a"
        focus_lines.append(f"{sym}: feed={feed}, idle={idle}, class={classify}")
    if focus_lines:
        print("  - Key assets:")
        for line in focus_lines:
            print(f"      {line}")


def _summarize_market_state(summary: Dict[str, Any]) -> None:
    assets = summary.get("assets", {})
    if not assets:
        print("  - No market state entries.")
        return
    for sym in FOCUS_SYMBOLS:
        info = assets.get(sym)
        if not info:
            continue
        regime = info.get("regime", "unknown")
        feed = info.get("feed_state", "unknown")
        expect = info.get("expected_trade_frequency", info.get("expect_freq", "unknown"))
        comment = info.get("comment", "")
        snippet = comment[:80] + ("..." if len(comment) > 80 else "")
        print(f"  - {sym}: regime={regime}, feed={feed}, expect={expect}, note={snippet}")


def _summarize_scorecards() -> None:
    assets_payload = _load_json(ASSET_SCORECARDS_PATH).get("assets", [])
    if not assets_payload:
        print("  - No asset scorecards yet.")
    else:
        for row in assets_payload[:5]:
            pf_val = row.get("pf")
            if pf_val is None:
                pf_disp = "∞" if row.get("wins", 0) > 0 and row.get("losses", 0) == 0 else "—"
            else:
                pf_disp = f"{pf_val:.2f}"
            trades = row.get("total_trades", 0)
            print(f"  - {row.get('symbol')}: PF={pf_disp}, trades={trades}")


def _summarize_overseer(report: Dict[str, Any]) -> None:
    phase = report.get("phase")
    assets = report.get("assets", {})
    enabled = [sym for sym, info in assets.items() if info.get("trading_enabled")]
    top_urgent = (report.get("global", {}) or {}).get("top_urgent_assets", [])
    print(f"  - Phase               : {phase}")
    print(f"  - Trading enabled     : {', '.join(enabled) if enabled else 'None'}")
    if top_urgent:
        print(f"  - Top urgent assets   : {', '.join(top_urgent)}")


def main() -> None:
    print("CHLOE OPS SWEEP")
    print("===============")
    print(f"Timestamp: {_timestamp()}")
    print()

    # 1) Staleness
    print("➡ Staleness report...")
    try:
        stale_report = build_staleness_report()
        assets = stale_report.get("assets", {})
        print(f"  - Generated at        : {stale_report.get('generated_at', 'n/a')}")
        _summarize_assets(assets)
    except Exception as exc:
        print(f"  ⚠ Staleness analysis failed: {exc}")
    print()

    # 2) Market state
    print("➡ Market state summary (15m)...")
    try:
        ms_report = summarize_market_state(symbols=FOCUS_SYMBOLS, timeframe="15m")
        print(f"  - Generated at        : {ms_report.get('generated_at', 'n/a')}")
        _summarize_market_state(ms_report)
    except Exception as exc:
        print(f"  ⚠ Market state summary failed: {exc}")
    print()

    # 3) Scorecards
    print("➡ Scorecards refresh...")
    try:
        SCORECARD_DIR.mkdir(parents=True, exist_ok=True)
        build_asset_scorecards()
        build_strategy_scorecards()
        print("  - Scorecards refreshed; highlights:")
        _summarize_scorecards()
    except Exception as exc:
        print(f"  ⚠ Scorecard build failed (non-fatal): {exc}")
    print()

    # 4) Overseer report
    print("➡ Overseer report...")
    try:
        overseer = build_overseer_report()
        _summarize_overseer(overseer)
    except Exception as exc:
        print(f"  ⚠ Overseer report failed (non-fatal): {exc}")
    print()

    # 5) Activity reflection
    print("➡ Activity reflection (latest)...")
    try:
        activity = run_activity_reflection(use_gpt=True)
        ts = activity.get("ts", "n/a")
        print(f"  - Reflection timestamp: {ts}")
        reflection_text = activity.get("reflection", "")
        for line in _preview_lines(reflection_text, max_lines=10):
            print(f"    {line}")
    except Exception as exc:
        print(f"  ⚠ Activity reflection failed: {exc}")
    print()

    # 6) Meta activity reflection
    print("➡ Meta-activity reflection...")
    try:
        meta = run_meta_reflection(use_gpt=True)
        ts = meta.get("ts", "n/a")
        print(f"  - Meta timestamp      : {ts}")
        meta_text = meta.get("reflection", "")
        for line in _preview_lines(meta_text, max_lines=12):
            print(f"    {line}")
    except Exception as exc:
        print(f"  ⚠ Meta-activity reflection failed: {exc}")

    print("\nOPS SWEEP COMPLETE\n")


if __name__ == "__main__":
    main()

