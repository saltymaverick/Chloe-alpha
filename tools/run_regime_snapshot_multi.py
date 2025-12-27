#!/usr/bin/env python3
"""
Per-symbol Regime Snapshot Writer
---------------------------------

Reads config/asset_registry.json and writes:
- reports/regime_snapshot.json (anchor/global)
- reports/regimes/regime_snapshot_<SYMBOL>.json (per symbol)
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.core.paths import REPORTS, CONFIG
from engine_alpha.data.live_prices import get_live_ohlcv
from engine_alpha.core.regime import classify_regime_simple, compute_regime_metrics


ASSET_REGISTRY_PATH = CONFIG / "asset_registry.json"
REGIMES_DIR = REPORTS / "regimes"


def _now():
    return datetime.now(timezone.utc)


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _tf_to_seconds(tf: str) -> int:
    tf = tf.lower().strip()
    if tf.endswith("m"):
        try:
            return int(tf[:-1]) * 60
        except Exception:
            return 900
    if tf.endswith("h"):
        try:
            return int(tf[:-1]) * 3600
        except Exception:
            return 3600
    if tf.endswith("d"):
        try:
            return int(tf[:-1]) * 86400
        except Exception:
            return 86400
    return 900


def _compute_regime(symbol: str, timeframe: str) -> Dict[str, Any]:
    ts = _now()
    try:
        rows, meta = get_live_ohlcv(symbol, timeframe, limit=200)
        if not rows or len(rows) < 20:
            return {
                "generated_at": ts.isoformat(),
                "source": "insufficient_data",
                "symbol": symbol,
                "timeframe": timeframe,
                "regime": "unknown",
                "confidence": 0.0,
                "features": {
                    "atr_ratio": None,
                    "trend_score": None,
                    "chop_score": None,
                    "bb_squeeze": None,
                },
                "meta": {
                    "ohlcv_source": meta.get("source") if isinstance(meta, dict) else None,
                    "ohlcv_age_s": meta.get("age_seconds") if isinstance(meta, dict) else None,
                    "n_bars": len(rows) if rows else 0,
                },
            }

        closes = [float(r.get("close", 0)) for r in rows if r.get("close") is not None]
        highs = [float(r.get("high", 0)) for r in rows if r.get("high") is not None] if rows and rows[0].get("high") is not None else None
        lows = [float(r.get("low", 0)) for r in rows if r.get("low") is not None] if rows and rows[0].get("low") is not None else None

        regime = classify_regime_simple(closes, highs, lows)
        metrics = compute_regime_metrics(rows)

        # Basic confidence: combine slope/vol metrics
        slope_abs = abs(metrics.get("slope", 0.0))
        vol_exp = metrics.get("vol_expansion", 1.0)
        atr_pct = metrics.get("atr_pct", 0.0)
        confidence = min(1.0, max(0.05, slope_abs * 5 + atr_pct * 10 + max(0.0, vol_exp - 1.0) * 0.2))

        # Compute OHLCV age
        ohlcv_age_s = None
        if isinstance(meta, dict):
            ohlcv_age_s = meta.get("age_seconds")
        tf_sec = _tf_to_seconds(timeframe)
        stale = False
        if isinstance(ohlcv_age_s, (int, float)):
            if ohlcv_age_s > 2 * tf_sec:
                stale = True
        if stale:
            regime = "unknown"
            confidence = 0.0

        return {
            "generated_at": ts.isoformat(),
            "source": "ohlcv_classifier",
            "symbol": symbol,
            "timeframe": timeframe,
            "regime": regime,
            "confidence": round(confidence, 3),
            "features": {
                "atr_ratio": round(metrics.get("atr_pct", 0.0), 6),
                "trend_score": round(metrics.get("slope", 0.0), 6),
                "chop_score": round(max(0.0, 1.0 - abs(metrics.get("slope", 0.0)))),  # simple proxy
                "bb_squeeze": round(1.0 / max(1e-6, metrics.get("vol_expansion", 1.0)), 6),
            },
            "meta": {
                "ohlcv_source": meta.get("source") if isinstance(meta, dict) else None,
                "ohlcv_age_s": ohlcv_age_s,
                "n_bars": len(rows) if rows else 0,
                "stale": stale,
            },
        }
    except Exception as e:
        return {
            "generated_at": ts.isoformat(),
            "source": f"error: {e}",
            "symbol": symbol,
            "timeframe": timeframe,
            "regime": "unknown",
            "confidence": 0.0,
            "features": {
                "atr_ratio": None,
                "trend_score": None,
                "chop_score": None,
                "bb_squeeze": None,
            },
            "meta": {},
        }


def main() -> int:
    registry = _load_json(ASSET_REGISTRY_PATH)
    if not registry or not isinstance(registry, dict):
        print(f"asset_registry missing or invalid at {ASSET_REGISTRY_PATH}")
        return 1

    symbols: List[str] = registry.get("symbols") or []
    timeframe = registry.get("regime_timeframe") or registry.get("default_timeframe") or "15m"
    anchor = registry.get("regime_anchor_symbol") or "ETHUSDT"

    if not symbols:
        print("No symbols in asset_registry.json")
        return 1

    REGIMES_DIR.mkdir(parents=True, exist_ok=True)

    # Compute anchor first (also global)
    anchor_snap = _compute_regime(anchor, timeframe)
    anchor_path = REPORTS / "regime_snapshot.json"
    anchor_path.parent.mkdir(parents=True, exist_ok=True)
    anchor_snap["meta"] = anchor_snap.get("meta", {}) or {}
    anchor_snap["meta"]["anchor"] = True
    anchor_path.write_text(json.dumps(anchor_snap, indent=2))

    # Compute per-symbol
    for sym in symbols:
        snap = _compute_regime(sym, timeframe)
        out_path = REGIMES_DIR / f"regime_snapshot_{sym}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(snap, indent=2))

    print(f"Regime snapshots written for {len(symbols)} symbols; anchor={anchor}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

