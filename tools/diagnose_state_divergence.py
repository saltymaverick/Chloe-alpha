#!/usr/bin/env python3
"""
State divergence diagnostic.

Prints:
- Net open counts derived from trades.jsonl per lane (symbol_timeframe keys)
- Open positions from position_state.json (normalized)
- Open positions from recovery_lane_v2_state.json
- Detected mismatches with suspected causes

Safe to run any time; read-only.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

from engine_alpha.loop.position_manager import load_position_state

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
TRADES_PATH = REPORTS / "trades.jsonl"
RECOVERY_STATE_PATH = REPORTS / "loop" / "recovery_lane_v2_state.json"


def _lane_from_trade(event: Dict[str, Any]) -> str:
    trade_kind = (event.get("trade_kind") or event.get("strategy") or "").lower()
    if trade_kind == "recovery_v2":
        return "recovery_v2"
    if trade_kind == "exploration":
        return "exploration"
    return "core"


def _default_timeframe() -> str:
    try:
        cfg = json.loads((ROOT / "engine_alpha" / "config" / "engine_config.json").read_text())
        return cfg.get("timeframe", "15m")
    except Exception:
        return "15m"


def _trade_key(event: Dict[str, Any]) -> Tuple[str, str]:
    symbol = (event.get("symbol") or event.get("asset") or "UNKNOWN").upper()
    timeframe = (event.get("timeframe") or event.get("tf") or _default_timeframe()).lower()
    return symbol, timeframe


def load_trade_net_counts() -> Dict[str, Dict[str, int]]:
    net: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    anomalies = {"close_missing_timeframe": 0, "close_missing_pct": 0}

    if not TRADES_PATH.exists():
        return net, anomalies

    with TRADES_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except Exception:
                continue

            evt_type = (evt.get("type") or evt.get("action") or "").lower()
            lane = _lane_from_trade(evt)
            symbol, timeframe = _trade_key(evt)
            key = f"{symbol}_{timeframe}"

            if evt_type == "open":
                net[lane][key] += 1
            elif evt_type == "close":
                net[lane][key] -= 1
                if not evt.get("timeframe") and not evt.get("tf"):
                    anomalies["close_missing_timeframe"] += 1
                if "pct" not in evt:
                    anomalies["close_missing_pct"] += 1

    return net, anomalies


def load_recovery_positions() -> Dict[str, Dict[str, Any]]:
    if not RECOVERY_STATE_PATH.exists():
        return {}
    try:
        data = json.loads(RECOVERY_STATE_PATH.read_text())
    except Exception:
        return {}

    open_positions = {}
    for symbol, pos in (data.get("open_positions") or {}).items():
        if not isinstance(pos, dict):
            continue
        if pos.get("direction", 0) == 0:
            continue
        tf = "15m"
        key = f"{symbol.upper()}_{tf}"
        open_positions[key] = {
            "symbol": symbol.upper(),
            "timeframe": tf,
            "direction": pos.get("direction"),
            "trade_kind": pos.get("trade_kind", "recovery_v2"),
        }
    return open_positions


def summarize_positions_by_lane(position_state: Dict[str, Any]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    positions = position_state.get("positions") or {}
    out: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    for key, pos in positions.items():
        if not isinstance(pos, dict):
            continue
        trade_kind = pos.get("trade_kind", "normal")
        lane = "exploration" if trade_kind == "exploration" else ("recovery_v2" if trade_kind == "recovery_v2" else "core")
        out[lane][key] = pos
    return out


def find_mismatches(net_counts: Dict[str, Dict[str, int]], positions_by_lane: Dict[str, Dict[str, Dict[str, Any]]]) -> Dict[str, list]:
    mismatches: Dict[str, list] = defaultdict(list)
    lanes = set(net_counts.keys()) | set(positions_by_lane.keys())
    for lane in lanes:
        keys = set(net_counts.get(lane, {}).keys()) | set(positions_by_lane.get(lane, {}).keys())
        for key in sorted(keys):
            net = net_counts.get(lane, {}).get(key, 0)
            pos_exists = key in positions_by_lane.get(lane, {})
            expected = 1 if pos_exists else 0
            if net != expected:
                cause = "missing_close" if net > expected else "missing_open_or_stale_state"
                mismatches[lane].append({"key": key, "net_from_trades": net, "state_has_position": pos_exists, "suspected": cause})
    return mismatches


def main() -> int:
    print("=== Chloe State Divergence Diagnostic ===")
    print(f"Now: {datetime.now(timezone.utc).isoformat()}")

    net_counts, anomalies = load_trade_net_counts()
    print("\nNet open keys from trades.jsonl (open-minus-close):")
    if not net_counts:
        print("  trades.jsonl missing or empty")
    else:
        for lane, entries in net_counts.items():
            active = {k: v for k, v in entries.items() if v != 0}
            if not active:
                continue
            print(f"  {lane}:")
            for key, val in sorted(active.items()):
                print(f"    {key}: {val}")

    pos_state = load_position_state()
    positions_by_lane = summarize_positions_by_lane(pos_state)

    print("\nOpen positions from position_state.json:")
    for lane, entries in positions_by_lane.items():
        if not entries:
            continue
        print(f"  {lane}:")
        for key, pos in sorted(entries.items()):
            dir_val = pos.get("dir")
            entry_px = pos.get("entry_px")
            print(f"    {key}: dir={dir_val} entry_px={entry_px}")

    recovery_positions = load_recovery_positions()
    print("\nOpen positions from recovery_lane_v2_state.json:")
    if recovery_positions:
        for key, pos in sorted(recovery_positions.items()):
            print(f"  {key}: dir={pos.get('direction')} trade_kind={pos.get('trade_kind')}")
    else:
        print("  none")

    # Merge recovery positions into lane view for comparison
    if recovery_positions:
        positions_by_lane.setdefault("recovery_v2", {}).update(recovery_positions)

    mismatches = find_mismatches(net_counts, positions_by_lane)
    print("\nMismatches (trades vs state):")
    any_mismatch = False
    for lane, entries in mismatches.items():
        if not entries:
            continue
        any_mismatch = True
        print(f"  {lane}:")
        for item in entries:
            print(f"    {item['key']}: net={item['net_from_trades']} state_has={item['state_has_position']} suspected={item['suspected']}")
    if not any_mismatch:
        print("  none detected")

    print("\nAnomalies:")
    for k, v in anomalies.items():
        print(f"  {k}: {v}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

