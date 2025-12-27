"""
Live-Candidate Scanner (Phase 4b)
---------------------------------

Paper-only engine that evaluates which symbols would be eligible
for live trading *if* Chloe were allowed to go live.

It:
  - Applies strict hard filters (PF stability, drift, ExecQL, policy, tier, risk)
  - Computes a readiness score in [0, 1]
  - Logs readiness history to enforce persistence
  - Writes current snapshot to reports/risk/live_candidates.json

Inputs:
  - reports/pf/pf_timeseries.json
  - reports/research/execution_quality.json
  - reports/research/drift_report.json
  - reports/research/exploration_policy_v3.json
  - reports/risk/risk_snapshot.json
  - reports/risk/capital_plan.json

Outputs:
  - reports/risk/live_candidates.json
  - reports/risk/live_candidates_history.jsonl

ADVISORY ONLY. Does NOT place trades or modify configs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, List


PF_TS_PATH = Path("reports/pf/pf_timeseries.json")
EXECQL_PATH = Path("reports/research/execution_quality.json")
DRIFT_PATH = Path("reports/research/drift_report.json")
POLICY_PATH = Path("reports/research/exploration_policy_v3.json")
RISK_SNAPSHOT_PATH = Path("reports/risk/risk_snapshot.json")
CAPITAL_PLAN_PATH = Path("reports/risk/capital_plan.json")

SNAPSHOT_PATH = Path("reports/risk/live_candidates.json")
HISTORY_PATH = Path("reports/risk/live_candidates_history.jsonl")


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


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _get_pf_for_symbol(pf_ts: Dict[str, Any], symbol: str) -> tuple[Optional[float], Optional[float]]:
    symbols = pf_ts.get("symbols") or {}
    entry = symbols.get(symbol) or {}
    pf7 = None
    pf30 = None
    win7 = entry.get("7d") or {}
    win30 = entry.get("30d") or {}
    try:
        pf7 = float(win7.get("pf")) if win7.get("pf") is not None else None
    except Exception:
        pf7 = None
    try:
        pf30 = float(win30.get("pf")) if win30.get("pf") is not None else None
    except Exception:
        pf30 = None
    return pf7, pf30


def _get_execql_for_symbol(execql: Dict[str, Any], symbol: str) -> Optional[str]:
    # Handle execution_quality.json format: {"data": {symbol: {...}}}
    data = execql.get("data")
    if isinstance(data, dict):
        entry = data.get(symbol) or {}
        summary = entry.get("summary", {})
        if isinstance(summary, dict):
            return summary.get("overall_label")
        return entry.get("overall_label") or entry.get("label")
    
    symbols = execql.get("symbols") or execql
    entry: Dict[str, Any] = {}
    if isinstance(symbols, dict):
        entry = symbols.get(symbol) or {}
    elif isinstance(symbols, list):
        for item in symbols:
            if isinstance(item, dict) and item.get("symbol") == symbol:
                entry = item
                break
    return entry.get("overall_label") or entry.get("label") or entry.get("overall")


def _get_drift_for_symbol(drift: Dict[str, Any], symbol: str) -> Optional[str]:
    symbols = drift.get("symbols") or {}
    entry = symbols.get(symbol) or {}
    return entry.get("status")


def _get_policy_for_symbol(policy: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    return (policy.get("symbols") or {}).get(symbol, {})


def _get_blocked_for_symbol(risk: Dict[str, Any], symbol: str) -> bool:
    symbols = risk.get("symbols") or risk
    entry: Dict[str, Any] = {}
    if isinstance(symbols, dict):
        entry = symbols.get(symbol) or {}
    elif isinstance(symbols, list):
        for item in symbols:
            if isinstance(item, dict) and item.get("symbol") == symbol:
                entry = item
                break
    blocked = entry.get("blocked")
    if isinstance(blocked, bool):
        return blocked
    if isinstance(blocked, str):
        return blocked.lower() == "yes"
    return False


def _get_weight_for_symbol(capital_plan: Dict[str, Any], symbol: str) -> float:
    symbols = capital_plan.get("symbols") or {}
    entry = symbols.get(symbol) or {}
    try:
        return float(entry.get("weight", 0.0))
    except Exception:
        return 0.0


def _drift_score(status: Optional[str]) -> float:
    if status == "improving":
        return 1.0
    if status == "neutral":
        return 0.6
    if status == "degrading":
        return 0.0
    return 0.5


def _exec_score(label: Optional[str]) -> float:
    if label == "friendly":
        return 1.0
    if label == "neutral":
        return 0.6
    if label == "hostile":
        return 0.0
    return 0.5


def _policy_score(level: Optional[str]) -> float:
    if level == "full":
        return 1.0
    if level == "reduced":
        return 0.7
    if level == "blocked":
        return 0.0
    return 0.6


@dataclass
class LiveCandidate:
    symbol: str
    tier: Optional[str]
    pf_7d: Optional[float]
    pf_30d: Optional[float]
    drift: Optional[str]
    execql: Optional[str]
    policy_level: Optional[str]
    blocked: bool
    weight: float
    hard_pass: bool
    score: float
    ready_now: bool
    live_ready: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _load_history() -> List[Dict[str, Any]]:
    if not HISTORY_PATH.exists():
        return []
    try:
        with HISTORY_PATH.open("r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except Exception:
        return []


def _append_history(entries: List[Dict[str, Any]]) -> None:
    try:
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with HISTORY_PATH.open("a", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
    except Exception:
        # history is advisory; failure is non-fatal
        return


def compute_live_candidates() -> Dict[str, Any]:
    now = datetime.now(timezone.utc)

    pf_ts = _load_json(PF_TS_PATH)
    execql = _load_json(EXECQL_PATH)
    drift = _load_json(DRIFT_PATH)
    policy = _load_json(POLICY_PATH)
    risk = _load_json(RISK_SNAPSHOT_PATH)
    capital_plan = _load_json(CAPITAL_PLAN_PATH)
    
    # Phase 5f: Load capital protection for recovery-aware persistence
    capital_protection = _load_json(Path("reports/risk/capital_protection.json"))
    capital_mode = None
    if capital_protection:
        global_mode = capital_protection.get("global", {})
        capital_mode = global_mode.get("mode") or capital_protection.get("mode")
    
    # Ensure capital_mode is set (default to "normal" if missing)
    if capital_mode is None:
        capital_mode = "normal"

    symbol_set = set()
    symbol_set.update((pf_ts.get("symbols") or {}).keys())
    symbol_set.update((policy.get("symbols") or {}).keys())

    candidates: Dict[str, LiveCandidate] = {}

    # Compute current snapshot
    for sym in symbol_set:
        if not isinstance(sym, str):
            continue
        if not sym.endswith("USDT") or not sym.isupper():
            continue

        pf7, pf30 = _get_pf_for_symbol(pf_ts, sym)
        pol = _get_policy_for_symbol(policy, sym)
        level = pol.get("level")
        tier = pol.get("tier")
        drift_status = _get_drift_for_symbol(drift, sym)
        exec_label = _get_execql_for_symbol(execql, sym)
        blocked = _get_blocked_for_symbol(risk, sym)
        weight = _get_weight_for_symbol(capital_plan, sym)

        # Hard filters
        hard_pass = True

        if pf30 is None or pf7 is None:
            hard_pass = False
        else:
            if pf30 < 1.05 or pf7 < 1.00:
                hard_pass = False

        if exec_label == "hostile":
            hard_pass = False

        if drift_status == "degrading":
            hard_pass = False

        if tier not in ("tier1", "tier2"):
            hard_pass = False

        if level == "blocked":
            hard_pass = False

        if blocked:
            hard_pass = False

        # Base scores (Phase 5f: policy-aware, not policy-punitive)
        pf30_stab = 0.0 if pf30 is None else _clamp(pf30 / 1.10, 0.0, 1.0)
        pf7_mom = 0.0 if pf7 is None else _clamp(pf7 / 1.05, 0.0, 1.0)
        drift_sc = _drift_score(drift_status)
        exec_sc = _exec_score(exec_label)
        weight_sc = _clamp(weight * 5.0, 0.0, 1.0)
        
        # Phase 5f: Policy penalty multiplier (not component score)
        # policy=blocked → hard blocker (already handled above)
        # policy=reduced → penalty multiplier 0.85
        # policy=full → no penalty (1.0)
        if level == "blocked":
            policy_penalty = 0.0  # Hard blocker (shouldn't reach here)
        elif level == "reduced":
            policy_penalty = 0.85  # Apply as penalty, not blocker
        else:  # full or None
            policy_penalty = 1.0
        
        # Compute base score without policy component
        base_score = (
            0.40 * pf30_stab
            + 0.20 * pf7_mom
            + 0.15 * drift_sc
            + 0.10 * exec_sc
            + 0.15 * weight_sc  # Increased weight_sc to compensate for removed policy_sc
        )
        
        # Apply policy penalty as multiplier
        score = base_score * policy_penalty

        # Ready-now threshold (strict)
        ready_now = hard_pass and score >= 0.75

        candidates[sym] = LiveCandidate(
            symbol=sym,
            tier=tier,
            pf_7d=pf7,
            pf_30d=pf30,
            drift=drift_status,
            execql=exec_label,
            policy_level=level,
            blocked=blocked,
            weight=weight,
            hard_pass=hard_pass,
            score=score,
            ready_now=ready_now,
            live_ready=False,  # filled after history analysis
        )

    # Persistence analysis: look back 24h
    history = _load_history()
    cutoff = now - timedelta(hours=24)

    # Append current snapshot to history
    history_entries = []
    for sym, lc in candidates.items():
        history_entries.append(
            {
                "ts": _fmt_ts(now),
                "symbol": sym,
                "score": lc.score,
                "hard_pass": lc.hard_pass,
            }
        )
    _append_history(history_entries)

    # Re-load history (including new entries)
    history = _load_history()
    per_symbol_hist: Dict[str, List[Dict[str, Any]]] = {}
    for entry in history:
        ts_str = entry.get("ts")
        sym = entry.get("symbol")
        if not ts_str or not sym:
            continue
        try:
            ts = datetime.fromisoformat(
                ts_str.replace("Z", "+00:00")
            ).astimezone(timezone.utc)
        except Exception:
            continue
        if ts < cutoff:
            continue
        per_symbol_hist.setdefault(sym, []).append(entry)

    # Determine live_ready based on persistence
    for sym, lc in candidates.items():
        hist = per_symbol_hist.get(sym, [])
        if not hist:
            lc.live_ready = False
            continue
        total = len(hist)
        above_075 = sum(1 for e in hist if (e.get("score") or 0.0) >= 0.75 and e.get("hard_pass"))
        min_score = min((e.get("score") or 0.0) for e in hist)
        ratio = above_075 / total if total > 0 else 0.0

        # Phase 5f: Recovery-aware persistence
        # During de_risk, cap persistence contribution but still allow accumulation
        if capital_mode == "de_risk":
            persistence_cap = 0.5
        else:
            persistence_cap = 1.0
        
        # Persistence rule:
        #   - at least 12 readings in 24h (~1 per 2h)
        #   - at least 80% of them with score >= 0.75 & hard_pass
        #   - minimum score >= 0.65
        raw_persistence_ok = (
            lc.hard_pass
            and lc.score >= 0.75
            and total >= 12
            and ratio >= 0.8
            and min_score >= 0.65
        )
        
        # Apply persistence cap (Phase 5f)
        effective_persistence = min(1.0 if raw_persistence_ok else 0.0, persistence_cap)
        lc.live_ready = effective_persistence >= (0.8 * persistence_cap)  # Scaled threshold

    snapshot = {
        "meta": {
            "engine": "live_candidate_scanner_v1",
            "version": "1.0.0",
            "generated_at": _fmt_ts(now),
            "advisory_only": True,
        },
        "symbols": {sym: lc.to_dict() for sym, lc in sorted(candidates.items())},
    }

    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SNAPSHOT_PATH.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, sort_keys=True)

    return snapshot


__all__ = ["compute_live_candidates", "SNAPSHOT_PATH", "HISTORY_PATH"]
