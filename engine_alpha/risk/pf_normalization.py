"""
PF Normalization Engine (Phase 4e)
----------------------------------

Paper-only module that converts inflated exploration PFs into
more realistic estimated PFs based on PF validity.

Reads:
  - reports/research/are_snapshot.json
  - reports/risk/pf_validity.json

Outputs:
  - reports/risk/pf_normalized.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


ARE_PATH = Path("reports/research/are_snapshot.json")
VALIDITY_PATH = Path("reports/risk/pf_validity.json")
OUT_PATH = Path("reports/risk/pf_normalized.json")


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
class PFNormalized:
    symbol: str
    short_exp_pf_raw: Optional[float]
    short_exp_pf_norm: Optional[float]
    long_exp_pf_raw: Optional[float]
    long_exp_pf_norm: Optional[float]
    validity_score: float
    slippage_factor: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _normalize_pf(raw: Optional[float], validity: float, slippage_factor: float) -> Optional[float]:
    if raw is None:
        return None
    excess = raw - 1.0
    # compress excess PF by validity and slippage factor
    return 1.0 + excess * max(0.0, min(1.0, validity * slippage_factor))


def compute_pf_normalized(slippage_factor: float = 0.4) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)

    are = _load_json(ARE_PATH)
    validity = _load_json(VALIDITY_PATH)

    are_syms = are.get("symbols") or {}
    val_syms = validity.get("symbols") or {}

    result: Dict[str, PFNormalized] = {}

    for sym, info in are_syms.items():
        if not isinstance(sym, str) or not sym.endswith("USDT") or not sym.isupper():
            continue

        # Try top-level keys first (as per user spec)
        short_raw = info.get("short_exp_pf")
        long_raw = info.get("long_exp_pf")
        
        # Fallback to nested structure (actual ARE snapshot format)
        if short_raw is None:
            short_entry = info.get("short") or {}
            short_raw = short_entry.get("exp_pf")
        if long_raw is None:
            long_entry = info.get("long") or {}
            long_raw = long_entry.get("exp_pf")

        try:
            short_val = float(short_raw) if short_raw not in (None, "—", "Infinity", float("inf")) else None
        except Exception:
            short_val = None
        try:
            long_val = float(long_raw) if long_raw not in (None, "—", "Infinity", float("inf")) else None
        except Exception:
            long_val = None

        v_entry = val_syms.get(sym) or {}
        v_score = v_entry.get("validity_score", 0.0)
        try:
            v_score = float(v_score)
        except Exception:
            v_score = 0.0

        short_norm = _normalize_pf(short_val, v_score, slippage_factor)
        long_norm = _normalize_pf(long_val, v_score, slippage_factor)

        result[sym] = PFNormalized(
            symbol=sym,
            short_exp_pf_raw=short_val,
            short_exp_pf_norm=short_norm,
            long_exp_pf_raw=long_val,
            long_exp_pf_norm=long_norm,
            validity_score=round(v_score, 3),
            slippage_factor=slippage_factor,
        )

    snapshot = {
        "meta": {
            "engine": "pf_normalization_v1",
            "version": "1.0.0",
            "generated_at": _fmt_ts(now),
            "advisory_only": True,
            "slippage_factor": slippage_factor,
        },
        "symbols": {sym: v.to_dict() for sym, v in result.items()},
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, sort_keys=True)

    return snapshot


__all__ = ["compute_pf_normalized", "OUT_PATH"]
