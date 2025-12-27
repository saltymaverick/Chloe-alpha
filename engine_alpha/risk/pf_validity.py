"""
PF Validity Engine (Phase 4d)
-----------------------------

Paper-only module that scores how trustworthy each symbol's PF is.

Reads:
  - reports/pf/pf_timeseries.json
  - reports/research/drift_report.json
  - reports/research/execution_quality.json

Outputs:
  - reports/risk/pf_validity.json

Each symbol gets:
  - validity_score in [0,1]
  - label: very_low / low / medium / high
  - components:
      sample_size_score
      stability_score
      drift_score
      exec_score
      consistency_score
  - reasons: list of textual flags
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


PF_TS_PATH = Path("reports/pf/pf_timeseries.json")
DRIFT_PATH = Path("reports/research/drift_report.json")
EXECQL_PATH = Path("reports/research/execution_quality.json")
OUT_PATH = Path("reports/risk/pf_validity.json")


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
class PFValidity:
    symbol: str
    validity_score: float
    label: str
    components: Dict[str, float]
    reasons: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _score_sample_size(trades: int) -> float:
    """
    0 at 0 trades, ~0.3 at ~10 trades, ~0.7 at ~50 trades, ~1.0 at 200+ trades.
    """
    if trades <= 0:
        return 0.0
    if trades >= 200:
        return 1.0
    return min(1.0, (trades / 200.0) ** 0.5)


def _score_stability(pf_7d: Optional[float], pf_30d: Optional[float]) -> float:
    """
    Stability based on similarity between PF_7D and PF_30D.
    If ratio ~1, stability high; diverging ratios reduce stability.
    """
    if pf_7d is None or pf_30d is None:
        return 0.0
    if pf_30d == 0:
        return 0.0
    ratio = pf_7d / pf_30d
    ratio = max(0.0, min(2.0, ratio))
    # best at 1.0, linear taper to 0 at 0 or 2
    return 1.0 - abs(ratio - 1.0) / 1.0


def _score_drift(status: Optional[str]) -> float:
    if status == "improving":
        return 1.0
    if status == "neutral":
        return 0.6
    if status == "degrading":
        return 0.1
    return 0.5


def _score_exec(label: Optional[str]) -> float:
    if label == "friendly":
        return 1.0
    if label == "neutral":
        return 0.7
    if label == "hostile":
        return 0.1
    return 0.5


def _score_consistency(pf_7d: Optional[float], pf_30d: Optional[float]) -> float:
    """
    Consistency between shorter and longer PF windows.
    We treat large discrepancies as low consistency.
    """
    if pf_7d is None or pf_30d is None:
        return 0.0
    diff = abs(pf_7d - pf_30d)
    # if diff is small relative to scale, consistency high
    scale = max(1.0, abs(pf_30d))
    rel = diff / scale
    if rel >= 1.0:
        return 0.0
    return 1.0 - rel


def _label_validity(score: float) -> str:
    if score >= 0.8:
        return "high"
    if score >= 0.6:
        return "medium"
    if score >= 0.4:
        return "low"
    return "very_low"


def compute_pf_validity() -> Dict[str, Any]:
    now = datetime.now(timezone.utc)

    pf_ts = _load_json(PF_TS_PATH)
    drift = _load_json(DRIFT_PATH)
    execql = _load_json(EXECQL_PATH)

    pf_syms = pf_ts.get("symbols") or {}
    drift_syms = drift.get("symbols") or {}
    exec_syms = execql.get("symbols") or execql

    def _pf_entry(sym: str) -> Dict[str, Any]:
        return pf_syms.get(sym) or {}

    def _get_pf(sym: str, win: str) -> Optional[float]:
        entry = _pf_entry(sym)
        w = entry.get(win) or {}
        pf = w.get("pf")
        try:
            return float(pf) if pf is not None else None
        except Exception:
            return None

    def _get_trades(sym: str) -> int:
        entry = _pf_entry(sym)
        t7 = (entry.get("7d") or {}).get("trades", 0)
        t30 = (entry.get("30d") or {}).get("trades", 0)
        try:
            return int(t7) + int(t30)
        except Exception:
            return 0

    def _drift_status(sym: str) -> Optional[str]:
        entry = drift_syms.get(sym) or {}
        return entry.get("status")

    def _exec_label(sym: str) -> Optional[str]:
        # Handle execution_quality.json format: {"data": {symbol: {...}}}
        data = execql.get("data")
        if isinstance(data, dict):
            entry = data.get(sym) or {}
            summary = entry.get("summary", {})
            if isinstance(summary, dict):
                return summary.get("overall_label")
            return entry.get("overall_label") or entry.get("label")
        
        if isinstance(exec_syms, dict):
            e = exec_syms.get(sym) or {}
        elif isinstance(exec_syms, list):
            e = {}
            for item in exec_syms:
                if isinstance(item, dict) and item.get("symbol") == sym:
                    e = item
                    break
        else:
            e = {}
        return e.get("overall_label") or e.get("label") or e.get("overall")

    result: Dict[str, PFValidity] = {}

    for sym in sorted(pf_syms.keys()):
        if not isinstance(sym, str) or not sym.endswith("USDT") or not sym.isupper():
            continue

        pf7 = _get_pf(sym, "7d")
        pf30 = _get_pf(sym, "30d")
        trades = _get_trades(sym)
        drift_status = _drift_status(sym)
        exec_label = _exec_label(sym)

        sample_score = _score_sample_size(trades)
        stability_score = _score_stability(pf7, pf30)
        drift_score = _score_drift(drift_status)
        exec_score = _score_exec(exec_label)
        consistency_score = _score_consistency(pf7, pf30)

        validity = (
            0.25 * sample_score +
            0.20 * stability_score +
            0.15 * exec_score +
            0.15 * drift_score +
            0.25 * consistency_score
        )

        reasons: List[str] = []
        if trades < 20:
            reasons.append("low_sample_size")
        elif trades < 100:
            reasons.append("moderate_sample_size")
        else:
            reasons.append("good_sample_size")

        if drift_status == "degrading":
            reasons.append("drift_degrading")
        elif drift_status == "improving":
            reasons.append("drift_improving")
        else:
            reasons.append("drift_neutral_or_unknown")

        if exec_label == "hostile":
            reasons.append("exec_hostile")
        elif exec_label == "friendly":
            reasons.append("exec_friendly")
        else:
            reasons.append("exec_neutral_or_unknown")

        if pf7 is None or pf30 is None:
            reasons.append("missing_pf_data")
        else:
            diff = abs(pf7 - pf30)
            if diff > max(0.5, 0.25 * abs(pf30)):
                reasons.append("pf_unstable")
            else:
                reasons.append("pf_stable")

        label = _label_validity(validity)

        result[sym] = PFValidity(
            symbol=sym,
            validity_score=round(validity, 3),
            label=label,
            components={
                "sample_size_score": round(sample_score, 3),
                "stability_score": round(stability_score, 3),
                "drift_score": round(drift_score, 3),
                "exec_score": round(exec_score, 3),
                "consistency_score": round(consistency_score, 3),
            },
            reasons=reasons,
        )

    snapshot = {
        "meta": {
            "engine": "pf_validity_v1",
            "version": "1.0.0",
            "generated_at": _fmt_ts(now),
            "advisory_only": True,
        },
        "symbols": {sym: v.to_dict() for sym, v in result.items()},
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, sort_keys=True)

    return snapshot


__all__ = ["compute_pf_validity", "OUT_PATH"]
