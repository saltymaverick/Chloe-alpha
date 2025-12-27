"""
Regime Awareness V2 – multi-source fusion with confidence & inertia.

PAPER-only, advisory-only.

This module:
  * Reads OHLCV from data/ohlcv/{symbol}_{timeframe}.csv
  * Builds several simple regime components (trend / volatility / chop)
  * Fuses them into a single regime label + confidence
  * Applies inertia against the previous snapshot to avoid flip-flopping
  * Writes reports/research/regime_fusion.json

Backwards-compatible: nobody is required to import this; it's pulled in
only by nightly_research_cycle and the intel dashboard.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Literal, Any

try:
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    pd = None

from engine_alpha.core.paths import REPORTS, DATA

RegimeLabel = Literal["trend_up", "trend_down", "chop", "volatile", "unknown"]


@dataclass
class RegimeComponent:
    name: str
    label: RegimeLabel
    confidence: float
    weight: float


@dataclass
class RegimeFusionSnapshot:
    symbol: str
    timeframe: str
    fused_label: RegimeLabel
    fused_confidence: float
    components: List[RegimeComponent]
    inertia_applied: float
    asof_iso: str
    version: str = "v2.1"
    health: Dict[str, Any] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "fused_label": self.fused_label,
            "fused_confidence": self.fused_confidence,
            "components": [asdict(c) for c in self.components],
            "inertia_applied": self.inertia_applied,
            "asof_iso": self.asof_iso,
            "version": self.version,
            "health": self.health or {},
        }


REPORT_PATH = REPORTS / "research" / "regime_fusion.json"


def _load_previous_snapshot() -> Dict[str, Dict[str, Any]]:
    if not REPORT_PATH.exists():
        return {}
    try:
        with REPORT_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        # Handle versioned format
        if "symbols" in data:
            return data.get("symbols", {})
        return data
    except Exception:
        return {}


def _save_snapshot(symbol_snapshots: Dict[str, Dict[str, Any]]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": "v2.1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "health": {
            "status": "ok",
            "reasons": [],
        },
        "symbols": symbol_snapshots,
    }
    with REPORT_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)


def _load_ohlcv(symbol: str, timeframe: str, lookback: int = 500):
    """
    Load OHLCV CSV from data/ohlcv/{symbol}_{timeframe}.csv.
    Expected columns: timestamp, open, high, low, close, volume
    """
    if pd is None:
        raise RuntimeError("pandas is required for regime_fusion_v2 but is not installed")

    path = DATA / "ohlcv" / f"{symbol}_{timeframe}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing OHLCV file: {path}")

    df = pd.read_csv(path)
    if "close" not in df.columns:
        raise ValueError(f"OHLCV file {path} missing 'close' column")

    if len(df) > lookback:
        df = df.iloc[-lookback:]
    return df


def _ema(series, span: int):
    return series.ewm(span=span, adjust=False).mean()


def _trend_component(df) -> RegimeComponent:
    close = df["close"].astype(float)
    fast = _ema(close, 20)
    slow = _ema(close, 100)
    delta = (fast.iloc[-1] - slow.iloc[-1]) / max(abs(slow.iloc[-1]), 1e-8)

    if delta > 0.015:
        label: RegimeLabel = "trend_up"
        conf = min(1.0, max(0.6, delta / 0.03))
    elif delta < -0.015:
        label = "trend_down"
        conf = min(1.0, max(0.6, abs(delta) / 0.03))
    else:
        label = "chop"
        conf = 0.4

    return RegimeComponent(
        name="trend",
        label=label,
        confidence=float(round(conf, 3)),
        weight=0.5,
    )


def _volatility_component(df) -> RegimeComponent:
    close = df["close"].astype(float)
    returns = close.pct_change().dropna()
    if returns.empty:
        return RegimeComponent("volatility", "unknown", 0.0, 0.25)

    vol = float(returns.rolling(20).std().iloc[-1])

    if vol > 0.035:
        label: RegimeLabel = "volatile"
        conf = min(1.0, vol / 0.05)
    elif vol < 0.01:
        label = "chop"
        conf = 0.6
    else:
        label = "trend_up" if returns.iloc[-1] > 0 else "trend_down"
        conf = 0.5

    return RegimeComponent(
        name="volatility",
        label=label,
        confidence=float(round(conf, 3)),
        weight=0.25,
    )


def _chop_component(df) -> RegimeComponent:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    true_range = (high - low).abs()
    atr = true_range.rolling(20).mean()
    if atr.isna().all():
        return RegimeComponent("chop", "unknown", 0.0, 0.25)

    atr_latest = float(atr.iloc[-1])
    range_latest = float((high.iloc[-20:] - low.iloc[-20:]).mean())
    if range_latest <= 0:
        return RegimeComponent("chop", "unknown", 0.0, 0.25)

    chop_ratio = atr_latest / range_latest

    if chop_ratio < 0.35:
        label: RegimeLabel = "trend_up" if close.iloc[-1] >= close.iloc[-5] else "trend_down"
        conf = 0.55
    elif chop_ratio > 0.7:
        label = "chop"
        conf = 0.8
    else:
        label = "chop"
        conf = 0.5

    return RegimeComponent(
        name="chop",
        label=label,
        confidence=float(round(conf, 3)),
        weight=0.25,
    )


def fuse_components(
    symbol: str,
    timeframe: str,
    components: List[RegimeComponent],
    prev_snapshot: Optional[Dict[str, Any]] = None,
    inertia: float = 0.6,
) -> RegimeFusionSnapshot:
    """
    Fuse regime components into a single label/confidence, applying inertia.

    inertia: 0.0 = no inertia, 1.0 = fully stick to previous label.
    """
    health: Dict[str, Any] = {"status": "ok", "reasons": []}

    # Weighted score per label
    scores: Dict[RegimeLabel, float] = {
        "trend_up": 0.0,
        "trend_down": 0.0,
        "chop": 0.0,
        "volatile": 0.0,
        "unknown": 0.0,
    }

    for c in components:
        scores[c.label] += c.weight * c.confidence

    fused_label: RegimeLabel = max(scores.items(), key=lambda kv: kv[1])[0]
    fused_conf = scores[fused_label]

    if prev_snapshot is not None:
        prev_label: RegimeLabel = prev_snapshot.get("fused_label", "unknown")  # type: ignore
        prev_conf: float = float(prev_snapshot.get("fused_confidence", 0.0))

        if prev_label == fused_label:
            fused_conf = inertia * prev_conf + (1.0 - inertia) * fused_conf
        else:
            fused_conf = inertia * prev_conf * 0.5 + (1.0 - inertia) * fused_conf

        fused_conf = float(max(0.0, min(1.0, fused_conf)))

    snapshot = RegimeFusionSnapshot(
        symbol=symbol,
        timeframe=timeframe,
        fused_label=fused_label,
        fused_confidence=float(round(fused_conf, 3)),
        components=components,
        inertia_applied=float(inertia),
        asof_iso=datetime.now(timezone.utc).isoformat(),
        health=health,
    )
    return snapshot


def run_regime_fusion_for_universe(
    symbols: List[str],
    timeframe: str = "15m",
    lookback: int = 500,
    inertia: float = 0.6,
) -> Dict[str, Dict[str, Any]]:
    """
    Main entrypoint for NIGHTLY research cycle.

    Returns the snapshot dict per symbol and writes them to REPORT_PATH.
    """
    prev = _load_previous_snapshot()
    results: Dict[str, Dict[str, Any]] = {}
    issues: List[str] = []

    for symbol in symbols:
        key = f"{symbol}:{timeframe}"
        prev_snapshot = prev.get(key)

        try:
            df = _load_ohlcv(symbol, timeframe, lookback=lookback)
        except Exception as exc:
            issues.append(f"{symbol} load_failed: {exc}")
            results[key] = RegimeFusionSnapshot(
                symbol=symbol,
                timeframe=timeframe,
                fused_label="unknown",
                fused_confidence=0.0,
                components=[],
                inertia_applied=0.0,
                asof_iso=datetime.now(timezone.utc).isoformat(),
                health={"status": "error", "reasons": [str(exc)]},
            ).to_dict()
            continue

        components = [
            _trend_component(df),
            _volatility_component(df),
            _chop_component(df),
        ]
        snapshot = fuse_components(
            symbol=symbol,
            timeframe=timeframe,
            components=components,
            prev_snapshot=prev_snapshot,
            inertia=inertia,
        )
        results[key] = snapshot.to_dict()

    # Update global health for file
    meta_health_status = "ok" if not issues else "degraded"
    _save_snapshot(results)

    # Rewrite meta.health with aggregated issues
    try:
        with REPORT_PATH.open("r+", encoding="utf-8") as f:
            data = json.load(f)
            data["health"]["status"] = meta_health_status
            data["health"]["reasons"] = issues
            f.seek(0)
            json.dump(data, f, indent=2, sort_keys=True)
            f.truncate()
    except Exception:
        # If this fails, we still have a usable per-symbol snapshot
        pass

    return results


__all__ = [
    "RegimeLabel",
    "RegimeComponent",
    "RegimeFusionSnapshot",
    "run_regime_fusion_for_universe",
    "REPORT_PATH",
]

