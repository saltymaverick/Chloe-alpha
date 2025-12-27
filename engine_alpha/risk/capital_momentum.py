"""
Capital Momentum Engine (Phase 4c)
----------------------------------

Paper-only capital momentum smoother for Chloe Alpha.

Reads:
  - reports/risk/capital_plan.json

Outputs:
  - reports/risk/capital_momentum.json
  - reports/risk/capital_momentum_history.jsonl

For each symbol, computes:
  - raw_weight       : latest weight from capital_plan
  - prev_smoothed    : previous smoothed weight (if any)
  - smoothed_weight  : EWMA-smoothed weight
  - delta            : abs(smoothed_weight - prev_smoothed)
  - churn_tag        : "stable" / "ramping_up" / "ramping_down" / "choppy"

This is ADVISORY ONLY and PAPER-SAFE.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, List


CAPITAL_PLAN_PATH = Path("reports/risk/capital_plan.json")
MOMENTUM_SNAPSHOT_PATH = Path("reports/risk/capital_momentum.json")
MOMENTUM_HISTORY_PATH = Path("reports/risk/capital_momentum_history.jsonl")


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _fmt_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


@dataclass
class MomentumEntry:
    symbol: str
    raw_weight: float
    prev_smoothed: float
    smoothed_weight: float
    delta: float
    churn_tag: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _load_prev_snapshot() -> Dict[str, Any]:
    return _load_json(MOMENTUM_SNAPSHOT_PATH)


def _append_history(entries: List[Dict[str, Any]]) -> None:
    try:
        MOMENTUM_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with MOMENTUM_HISTORY_PATH.open("a", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
    except Exception:
        # history is advisory; failure is non-fatal
        return


def compute_capital_momentum(alpha: float = 0.3) -> Dict[str, Any]:
    """
    Compute capital momentum snapshot.

    alpha: EWMA smoothing factor in (0,1], higher = faster react.
           0.3 is a good default for "not too twitchy" on 5-min cadence.
    """
    now = datetime.now(timezone.utc)

    plan = _load_json(CAPITAL_PLAN_PATH)
    symbols_plan = plan.get("symbols") or {}
    if not symbols_plan:
        snapshot = {
            "meta": {
                "engine": "capital_momentum_v1",
                "version": "1.0.0",
                "generated_at": _fmt_ts(now),
                "advisory_only": True,
                "note": "No capital plan available; momentum empty.",
            },
            "symbols": {},
        }
        MOMENTUM_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with MOMENTUM_SNAPSHOT_PATH.open("w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, sort_keys=True)
        return snapshot

    prev = _load_prev_snapshot()
    prev_syms = prev.get("symbols") or {}

    entries: Dict[str, MomentumEntry] = {}
    history_entries: List[Dict[str, Any]] = []

    for sym, info in symbols_plan.items():
        if not isinstance(sym, str):
            continue
        if not sym.endswith("USDT") or not sym.isupper():
            continue

        try:
            raw_w = float(info.get("weight", 0.0))
        except Exception:
            raw_w = 0.0

        prev_info = prev_syms.get(sym) or {}
        try:
            prev_smoothed = float(prev_info.get("smoothed_weight", raw_w))
        except Exception:
            prev_smoothed = raw_w

        # EWMA smoothing
        smoothed = (1.0 - alpha) * prev_smoothed + alpha * raw_w

        delta = abs(smoothed - prev_smoothed)

        # Churn tagging:
        #  - small delta → stable
        #  - increasing significantly → ramping_up
        #  - decreasing significantly → ramping_down
        #  - frequent sign-flip type behavior → "choppy" (approximated via magnitude threshold)
        up = smoothed > prev_smoothed
        big_move = delta >= 0.05  # 5% shift in allocation is notable on 5-min cadence

        if delta < 0.01:
            churn_tag = "stable"
        elif up and big_move:
            churn_tag = "ramping_up"
        elif (not up) and big_move:
            churn_tag = "ramping_down"
        else:
            churn_tag = "choppy"

        entries[sym] = MomentumEntry(
            symbol=sym,
            raw_weight=raw_w,
            prev_smoothed=prev_smoothed,
            smoothed_weight=smoothed,
            delta=delta,
            churn_tag=churn_tag,
        )

        history_entries.append({
            "ts": _fmt_ts(now),
            "symbol": sym,
            "raw_weight": raw_w,
            "prev_smoothed": prev_smoothed,
            "smoothed_weight": smoothed,
            "delta": delta,
            "churn_tag": churn_tag,
        })

    # Write snapshot
    snapshot = {
        "meta": {
            "engine": "capital_momentum_v1",
            "version": "1.0.0",
            "generated_at": _fmt_ts(now),
            "advisory_only": True,
            "alpha": alpha,
        },
        "symbols": {sym: e.to_dict() for sym, e in sorted(entries.items())},
    }

    MOMENTUM_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MOMENTUM_SNAPSHOT_PATH.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, sort_keys=True)

    # Append history
    _append_history(history_entries)

    return snapshot


__all__ = ["compute_capital_momentum", "MOMENTUM_SNAPSHOT_PATH", "MOMENTUM_HISTORY_PATH"]

