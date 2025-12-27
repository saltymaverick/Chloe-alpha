from __future__ import annotations

import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from dateutil import parser

from engine_alpha.reflect.promotion_filters import (
    is_promo_sample_close,
    get_promotion_filter_metadata,
)
from engine_alpha.reflect.promotion_gates import (
    get_promotion_gate_spec,
    get_promotion_gate_metadata,
)

TRADES_PATH = Path("reports/trades.jsonl")
DREAM_SUMMARY_PATH = Path("reports/gpt/dream_summary.json")
TUNER_OUTPUT_PATH = Path("reports/gpt/tuner_output.json")
QUARANTINE_PATH = Path("reports/risk/quarantine.json")
RECOVERY_RAMP_PATH = Path("reports/risk/recovery_ramp.json")

SCORES_PATH = Path("reports/gpt/shadow_promotion_scores.json")
QUEUE_PATH = Path("reports/gpt/shadow_promotion_queue.json")
STATE_PATH = Path("reports/gpt/shadow_promotion_state.json")
LOG_PATH = Path("reports/gpt/shadow_promotion_log.jsonl")
PROMO_PATH = Path("reports/gpt/shadow_promotions.jsonl")

SYMBOL_RE = re.compile(r"\b[A-Z0-9]{2,12}USDT\b")

LOOKBACKS = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}
REGIME_SNAPSHOT_PATH = Path("reports/regime_snapshot.json")

# Candidate gates - sourced from promotion_gates.py
spec = get_promotion_gate_spec()
MIN_EXPL_7D = spec.min_exploration_closes_7d
WATCHLIST_MIN_N = spec.min_exploration_closes_7d // 2  # watchlist at half threshold
PF_MIN = spec.min_exploration_pf
PF_DELTA = 0.10
MDD_MAX = spec.max_drawdown_multiple * 0.005 * 6  # Rough approximation

# Proposal gates - sourced from promotion_gates.py
PROPOSAL_SCORE_MIN = 70
PROPOSAL_SHADOW_PF_MIN = spec.min_exploration_pf
PROPOSAL_EXPL_N_MIN = spec.min_exploration_closes_7d


def _now():
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _iter_trades():
    if not TRADES_PATH.exists():
        return
    with TRADES_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                yield json.loads(line)
            except Exception:
                continue


def _is_close(e: Dict[str, Any]) -> bool:
    t = (e.get("type") or e.get("event") or "").lower()
    return t in ("close", "exit")


def _parse_ts(e: Dict[str, Any]) -> datetime | None:
    ts = e.get("ts") or e.get("timestamp") or e.get("time")
    if not ts:
        return None
    try:
        return parser.isoparse(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _pct(e: Dict[str, Any]) -> float | None:
    v = e.get("pct")
    if v is None:
        v = e.get("pnl_pct")
    if v is None:
        return None
    try:
        v = float(v)
        if not math.isfinite(v):
            return None
        return v
    except Exception:
        return None


def _lane(e: Dict[str, Any]) -> str | None:
    tk = (e.get("trade_kind") or "").lower()
    strat = (e.get("strategy") or "").lower()
    if strat == "recovery_v2" or tk == "recovery_v2":
        return "recovery"
    if tk == "exploration":
        return "exploration"
    if tk == "normal" and strat != "recovery_v2":
        return "core"
    return None


def _profit_factor(returns: List[float]) -> float | None:
    gp = sum(r for r in returns if r > 0)
    gl = -sum(r for r in returns if r < 0)
    if gp == 0 and gl == 0:
        return 1.0
    if gl == 0:
        return float("inf")
    return gp / gl


def _max_drawdown(returns: List[float]) -> float:
    cum = 0.0
    peak = 0.0
    mdd = 0.0
    for r in returns:
        cum += r
        peak = max(peak, cum)
        dd = peak - cum
        mdd = max(mdd, dd)
    return mdd


def _win_rate(returns: List[float]) -> float | None:
    if not returns:
        return None
    wins = sum(1 for r in returns if r > 0)
    return wins / len(returns)


def _avg_return(returns: List[float]) -> float | None:
    if not returns:
        return None
    return sum(returns) / len(returns)


def _mix(items: List[str]) -> Dict[str, float]:
    c = Counter(items)
    total = sum(c.values())
    return {k: v / total for k, v in c.most_common()} if total else {}


def _compute_metrics(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    rets: List[float] = []
    regimes: List[str] = []
    exits: List[str] = []
    for e in events:
        p = _pct(e)
        if p is None:
            continue
        rets.append(p)
        reg = e.get("regime")
        if isinstance(reg, str):
            regimes.append(reg.lower())
        er = e.get("exit_reason")
        if isinstance(er, str):
            exits.append(er.lower())
    n = len(rets)
    if n == 0:
        return {
            "n_closes": 0,
            "pf": 1.0,
            "win_rate": None,
            "avg_return": None,
            "max_drawdown": 0.0,
            "regime_mix": {},
            "exit_reason_mix": {},
        }
    return {
        "n_closes": n,
        "pf": _profit_factor(rets),
        "win_rate": _win_rate(rets),
        "avg_return": _avg_return(rets),
        "max_drawdown": _max_drawdown(rets),
        "regime_mix": _mix(regimes),
        "exit_reason_mix": _mix(exits),
    }


def _score_candidate(core_m: Dict[str, Any], exp_m: Dict[str, Any], dream_warn: bool, tuner_frozen: bool) -> Tuple[float, List[str]]:
    score = 0.0
    reasons: List[str] = []

    pf_c = core_m.get("pf")
    pf_e = exp_m.get("pf")
    wr_e = exp_m.get("win_rate")
    dd_e = exp_m.get("max_drawdown")
    n_e = exp_m.get("n_closes", 0)

    # PF advantage
    if isinstance(pf_c, (int, float)) and isinstance(pf_e, (int, float)) and pf_c > 0:
        adv = pf_e / max(pf_c, 1e-9)
        adv_score = min(40.0, 40.0 * adv / 2.0)  # cap at 2x advantage
        score += adv_score
        reasons.append(f"pf_advantage_{adv:.2f}")

    # Stability
    if wr_e is not None:
        score += min(20.0, 20.0 * wr_e)
    if dd_e is not None and dd_e >= 0:
        score += max(0.0, 20.0 * (0.04 - min(dd_e, 0.04)) / 0.04)  # lower dd -> higher score

    # Sample size (log scale)
    if n_e > 0:
        score += min(15.0, 5.0 * math.log1p(n_e))

    # Regime consistency (simple: penalize if ultra concentrated)
    reg_mix = exp_m.get("regime_mix") or {}
    top_reg = max(reg_mix.values()) if reg_mix else 0.0
    score += max(0.0, 15.0 * (1.0 - max(0.0, top_reg - 0.8) / 0.2))  # mild penalty if >80% one regime

    # Penalties
    if dream_warn:
        score -= 10.0
        reasons.append("dream_warning")
    if tuner_frozen:
        score -= 10.0
        reasons.append("tuning_frozen_due_to_self_eval")

    # Recent losses streak penalty is omitted for brevity; could be added with more data.

    return max(0.0, min(100.0, score)), reasons


def _shadow_pf_proxy(exp_events: List[Dict[str, Any]]) -> float | None:
    rets = []
    for e in exp_events:
        p = _pct(e)
        if p is None:
            continue
        # apply core friction penalty
        rets.append(p * 0.8)
    if not rets:
        return None
    return _profit_factor(rets)


def _load_flags_from_tuner() -> Dict[str, bool]:
    res: Dict[str, bool] = {}
    t = _load_json(TUNER_OUTPUT_PATH)
    if not isinstance(t, dict):
        return res
    proposals = t.get("proposals") or t.get("tuning_proposals") or {}
    if not isinstance(proposals, dict):
        return res
    for sym, props in proposals.items():
        if isinstance(props, dict) and props.get("tuning_frozen_due_to_self_eval"):
            res[str(sym).upper()] = True
    return res


def _is_quarantined(sym: str, quarantine: Dict[str, Any]) -> bool:
    if not isinstance(quarantine, dict):
        return False
    blocked = quarantine.get("blocked_symbols") or quarantine.get("blocked") or quarantine.get("symbols") or []
    if isinstance(blocked, dict):
        blocked = list(blocked.keys())
    return sym in set(str(s).upper() for s in blocked)


def main() -> None:
    now = _now()
    cutoffs = {k: now - delta for k, delta in LOOKBACKS.items()}

    dream = _load_json(DREAM_SUMMARY_PATH) or {}
    dream_bad_syms = set(s.upper() for s in dream.get("bad_symbols", []) if isinstance(s, str))
    dream_bad_regs = set(r.lower() for r in dream.get("bad_regimes", []) if isinstance(r, str))

    global_regime = None
    try:
        reg = _load_json(REGIME_SNAPSHOT_PATH)
        if isinstance(reg, dict):
            rg = reg.get("regime")
            if isinstance(rg, str):
                global_regime = rg.lower()
    except Exception:
        global_regime = None

    tuner_frozen = _load_flags_from_tuner()
    quarantine = _load_json(QUARANTINE_PATH) or {}

    # Collect events by symbol/lane/window
    buckets: Dict[str, Dict[str, Dict[str, List[Dict[str, Any]]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for e in _iter_trades() or []:
        if not _is_close(e):
            continue
        ts = _parse_ts(e)
        if ts is None:
            continue
        lane = _lane(e)
        if lane not in ("core", "exploration"):
            continue

        # Use canonical promotion sample filter for exploration
        if lane == "exploration" and not is_promo_sample_close(e, lane):
            continue

        sym = e.get("symbol")
        if not sym:
            continue
        sym_u = str(sym).upper()
        for win, cutoff in cutoffs.items():
            if ts >= cutoff:
                buckets[sym_u][lane][win].append(e)

    scores_out: Dict[str, Any] = {
        "generated_at": _iso(now),
        "windows": list(LOOKBACKS.keys()),
        "symbols": {},
    }
    queue: List[Dict[str, Any]] = []
    watchlist: List[Dict[str, Any]] = []

    for sym, lanes in buckets.items():
        core7 = _compute_metrics(lanes.get("core", {}).get("7d", []))
        exp7 = _compute_metrics(lanes.get("exploration", {}).get("7d", []))
        core24 = _compute_metrics(lanes.get("core", {}).get("24h", []))
        exp24 = _compute_metrics(lanes.get("exploration", {}).get("24h", []))
        core30 = _compute_metrics(lanes.get("core", {}).get("30d", []))
        exp30 = _compute_metrics(lanes.get("exploration", {}).get("30d", []))

        sym_entry = {
            "core": {"7d": core7, "24h": core24, "30d": core30},
            "exploration": {"7d": exp7, "24h": exp24, "30d": exp30},
        }

        # Regime mix / primary regime from exploration 7d
        reg_mix = exp7.get("regime_mix") or {}
        primary_regime = None
        if reg_mix:
            try:
                primary_regime = max(reg_mix.items(), key=lambda kv: kv[1])[0]
            except Exception:
                primary_regime = None
        sym_entry["regime_mix_7d"] = reg_mix
        sym_entry["primary_regime_7d"] = primary_regime
        sym_entry["global_regime_now"] = global_regime

        # Load symbol-specific current regime (if available)
        symbol_regime_now = None
        try:
            # Try uppercase filename (canonical)
            sym_reg_path = REGIMES_DIR / f"regime_snapshot_{sym}.json"
            if sym_reg_path.exists():
                sym_reg = _load_json(sym_reg_path)
                if isinstance(sym_reg, dict):
                    sr = sym_reg.get("regime")
                    if isinstance(sr, str):
                        symbol_regime_now = sr.lower()
            # Fallback: try lowercase filename
            if symbol_regime_now is None:
                sym_reg_path_lower = REGIMES_DIR / f"regime_snapshot_{sym.lower()}.json"
                if sym_reg_path_lower.exists():
                    sym_reg = _load_json(sym_reg_path_lower)
                    if isinstance(sym_reg, dict):
                        sr = sym_reg.get("regime")
                        if isinstance(sr, str):
                            symbol_regime_now = sr.lower()
            # Final fallback: use global regime if still None
            if symbol_regime_now is None and global_regime:
                symbol_regime_now = global_regime
        except Exception:
            symbol_regime_now = symbol_regime_now or global_regime
        sym_entry["symbol_regime_now"] = symbol_regime_now

        quarantined = _is_quarantined(sym, quarantine)
        dream_warn = sym in dream_bad_syms
        tuner_warn = sym in tuner_frozen

        score, score_reasons = _score_candidate(core7, exp7, dream_warn, tuner_warn)

        # Regime alignment penalty ladder:
        # 1) primary_regime_7d vs symbol_regime_now (strong penalty)
        # 2) symbol_regime_now vs global_regime_now (small penalty)
        regime_penalty = 0.0
        if primary_regime and symbol_regime_now:
            if primary_regime != symbol_regime_now:
                regime_penalty += 7.5  # stronger penalty for symbol mismatch
                score -= 7.5
                score_reasons.append(f"regime_mismatch_symbol(primary={primary_regime},symbol={symbol_regime_now})")
        if symbol_regime_now and global_regime and symbol_regime_now != global_regime:
            regime_penalty += 3.0  # small penalty for symbol vs global disagreement
            score -= 3.0
            score_reasons.append(f"regime_mismatch_global(symbol={symbol_regime_now},global={global_regime})")

        # eligibility gates
        n_expl = exp7["n_closes"]
        eligible = (
            n_expl >= MIN_EXPL_7D
            and isinstance(exp7["pf"], (int, float))
            and exp7["pf"] >= PF_MIN
            and isinstance(core7["pf"], (int, float))
            and (exp7["pf"] - core7["pf"]) >= PF_DELTA
            and exp7["max_drawdown"] is not None
            and exp7["max_drawdown"] <= MDD_MAX
            and not quarantined
        )

        watchlist_ok = (
            WATCHLIST_MIN_N <= n_expl < MIN_EXPL_7D
            and isinstance(exp7["pf"], (int, float))
            and exp7["pf"] >= PF_MIN
            and isinstance(core7["pf"], (int, float))
            and (exp7["pf"] - core7["pf"]) >= PF_DELTA
            and exp7["max_drawdown"] is not None
            and exp7["max_drawdown"] <= MDD_MAX
            and not quarantined
        )

        if dream_warn and isinstance(exp7.get("pf"), (int, float)) and exp7["pf"] < 1.0:
            eligible = False
            watchlist_ok = False

        sym_entry.update(
            {
                "score": score,
                "eligible": eligible,
                "quarantined": quarantined,
                "dream_warning": dream_warn,
                "tuner_frozen": tuner_warn,
                "reasons": score_reasons,
                "watchlist_eligible": watchlist_ok,
                "regime_alignment_penalty": regime_penalty if global_regime and primary_regime else 0.0,
            }
        )

        # shadow pf proxy
        shadow_pf = _shadow_pf_proxy(lanes.get("exploration", {}).get("7d", []))
        sym_entry["shadow_pf_proxy"] = shadow_pf

        # proposal readiness / countdown
        missing_n = max(0, PROPOSAL_EXPL_N_MIN - n_expl)
        missing_pfproxy = max(0.0, PROPOSAL_SHADOW_PF_MIN - (shadow_pf or 0.0)) if shadow_pf is not None else PROPOSAL_SHADOW_PF_MIN
        missing_score = max(0.0, PROPOSAL_SCORE_MIN - score)
        proposal_ready = (
            n_expl >= PROPOSAL_EXPL_N_MIN
            and shadow_pf is not None
            and shadow_pf >= PROPOSAL_SHADOW_PF_MIN
            and score >= PROPOSAL_SCORE_MIN
        )
        sym_entry["proposal_ready"] = proposal_ready
        sym_entry["proposal_missing"] = {
            "n_expl_7d": missing_n,
            "shadow_pf_proxy": missing_pfproxy,
            "score": missing_score,
        }

        # action decision for queue
        if eligible:
            queue.append(
                {
                    "symbol": sym,
                    "score": score,
                    "shadow_pf_proxy": shadow_pf,
                    "exploration_pf_7d": exp7["pf"],
                    "core_pf_7d": core7["pf"],
                    "n_expl_7d": exp7["n_closes"],
                    "reasons": score_reasons + (["dream_warning"] if dream_warn else []),
                    "proposal_ready": proposal_ready,
                    "proposal_missing": {
                        "n_expl_7d": missing_n,
                        "shadow_pf_proxy": missing_pfproxy,
                        "score": missing_score,
                    },
                }
            )
        elif watchlist_ok:
            watchlist.append(
                {
                    "symbol": sym,
                    "score": score,
                    "shadow_pf_proxy": shadow_pf,
                    "exploration_pf_7d": exp7["pf"],
                    "core_pf_7d": core7["pf"],
                    "n_expl_7d": exp7["n_closes"],
                    "reasons": (score_reasons + ["watchlist_only", f"insufficient_sample<{MIN_EXPL_7D}"])
                    + (["dream_warning"] if dream_warn else []),
                }
            )

        scores_out["symbols"][sym] = sym_entry

    # rank queue
    queue_sorted = sorted(queue, key=lambda x: (-x["score"], -(x.get("shadow_pf_proxy") or 0)))
    queue_top = queue_sorted[:3]

    watchlist_sorted = sorted(watchlist, key=lambda x: (-x["score"], -(x.get("shadow_pf_proxy") or 0)))
    watchlist_top = watchlist_sorted[:5]

    queue_out = {
        "generated_at": _iso(now),
        "candidates": queue_top,
        "watchlist": watchlist_top,
        "total_candidates": len(queue_sorted),
        "total_watchlist": len(watchlist_sorted),
        **get_promotion_filter_metadata(),
        **get_promotion_gate_metadata(),
    }

    # log state
    state = {
        "generated_at": _iso(now),
        "last_queue_size": len(queue_sorted),
    }

    # Promotion proposal (write, but still advisory)
    proposals_written = 0
    if queue_sorted:
        PROMO_PATH.parent.mkdir(parents=True, exist_ok=True)
    for item in queue_sorted:
        sym = item["symbol"]
        if (
            item["score"] >= PROPOSAL_SCORE_MIN
            and (item.get("n_expl_7d") or 0) >= PROPOSAL_EXPL_N_MIN
            and item.get("shadow_pf_proxy") is not None
            and item["shadow_pf_proxy"] >= PROPOSAL_SHADOW_PF_MIN
        ):
            proposal = {
                "ts": _iso(now),
                "symbol": sym,
                "score": item["score"],
                "shadow_pf_proxy": item["shadow_pf_proxy"],
                "recommended_action": "promote_candidate",
                "suggested_bounds": {"risk_mult_cap": 0.25, "max_positions": 1},
                "reasons": item.get("reasons", []),
            }
            with PROMO_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(proposal) + "\n")
            proposals_written += 1

    # Write artifacts
    SCORES_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCORES_PATH.write_text(json.dumps(scores_out, indent=2, sort_keys=True))
    QUEUE_PATH.write_text(json.dumps(queue_out, indent=2, sort_keys=True))
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True))

    # log audit
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "ts": _iso(now),
        "queue_size": len(queue_sorted),
                    "proposals": proposals_written,
                }
            )
            + "\n"
        )

    print(f"Shadow promotion queue written: {QUEUE_PATH} (candidates={len(queue_sorted)})")


if __name__ == "__main__":
    main()

