import json, math, os, re
from datetime import datetime, timezone, timedelta
from dateutil import parser

from engine_alpha.reflect.promotion_filters import (
    is_promo_sample_close,
    get_promotion_filter_metadata,
)
from engine_alpha.reflect.promotion_gates import (
    get_promotion_gate_spec,
    get_promotion_gate_metadata,
)

TRADES = "reports/trades.jsonl"
OUT = "reports/gpt/promotion_advice.json"
DREAM_SUMMARY = "reports/gpt/dream_summary.json"
QUARANTINE = "reports/risk/quarantine.json"

SYMBOL_RE = re.compile(r"\b[A-Z0-9]{2,12}USDT\b")

LOOKBACK_DAYS = 7
LOOKBACK_HOURS = 24

# Promotion gates - sourced from promotion_gates.py
spec = get_promotion_gate_spec()
PROMOTE_MIN_N = spec.min_exploration_closes_7d
PROMOTE_PF = spec.min_exploration_pf
PROMOTE_WR = spec.min_win_rate
PROMOTE_MAX_DD = spec.max_drawdown_multiple * 0.005 * 6  # Rough approximation
PROMOTE_PF_DELTA = 0.10

DEMOTE_PF = 0.95
DEMOTE_MAX_DD = 0.03

def now_utc():
    return datetime.now(timezone.utc)

def iso(dt):
    return dt.astimezone(timezone.utc).isoformat()

def is_close(e):
    t = (e.get("type") or e.get("event") or "").lower()
    return t in ("close", "exit")

def parse_ts(e):
    ts = e.get("ts") or e.get("timestamp") or e.get("time")
    if not ts:
        return None
    return parser.isoparse(ts.replace("Z", "+00:00"))

def pct(e):
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

def lane_of(e):
    # explicit lane definitions
    tk = (e.get("trade_kind") or "").lower()
    strat = (e.get("strategy") or "").lower()

    if strat == "recovery_v2" or tk == "recovery_v2":
        return "recovery"
    if tk == "exploration":
        return "exploration"
    if tk == "normal" and strat != "recovery_v2":
        return "core"
    return None

def profit_factor(returns):
    # returns in pct units (e.g. 0.5 for +0.5%)
    gp = sum(r for r in returns if r > 0)
    gl = -sum(r for r in returns if r < 0)
    if gp == 0 and gl == 0:
        return 1.0
    if gl == 0:
        return float("inf")
    return gp / gl

def max_drawdown(returns):
    # simple cumulative returns drawdown
    cum = 0.0
    peak = 0.0
    mdd = 0.0
    for r in returns:
        cum += r
        peak = max(peak, cum)
        dd = peak - cum
        mdd = max(mdd, dd)
    return mdd

def win_rate(returns):
    if not returns:
        return None
    wins = sum(1 for r in returns if r > 0)
    return wins / len(returns)

def avg_return(returns):
    if not returns:
        return None
    return sum(returns) / len(returns)

def regime_mix(events):
    # returns % by regime string if present
    counts = {}
    total = 0
    for e in events:
        reg = e.get("regime")
        if not reg:
            continue
        counts[reg] = counts.get(reg, 0) + 1
        total += 1
    if total == 0:
        return {}
    return {k: v / total for k, v in sorted(counts.items(), key=lambda x: -x[1])}

def load_json(path, default):
    try:
        return json.load(open(path))
    except Exception:
        return default

def extract_bad_symbols_from_dream(dream):
    bad = set()
    patterns = (dream.get("patterns") or []) + (dream.get("warnings") or [])
    for s in patterns:
        for m in SYMBOL_RE.findall(s):
            bad.add(m)
    return sorted(bad)

def extract_bad_regimes_from_dream(dream):
    regs = set()
    hay = " ".join((dream.get("patterns") or []) + (dream.get("warnings") or [])).lower()
    for r in ("chop", "trend_down", "trend_up", "high_vol"):
        if r in hay:
            regs.add(r)
    return sorted(regs)

def compute_metrics(events):
    rs = [pct(e) for e in events]
    rs = [r for r in rs if r is not None]
    return {
        "n_closes": len(rs),
        "pf": profit_factor(rs),
        "win_rate": win_rate(rs),
        "avg_return": avg_return(rs),
        "max_drawdown": max_drawdown(rs),
        "regime_mix": regime_mix(events),
    }

def main():
    os.makedirs("reports/gpt", exist_ok=True)

    now = now_utc()
    cut_7d = now - timedelta(days=LOOKBACK_DAYS)
    cut_24h = now - timedelta(hours=LOOKBACK_HOURS)

    q = load_json(QUARANTINE, {})
    blocked = set(q.get("blocked_symbols") or [])

    dream_sum = load_json(DREAM_SUMMARY, None)
    dream_bad_symbols = set()
    dream_bad_regimes = set()
    if isinstance(dream_sum, dict):
        dream_bad_symbols = set(dream_sum.get("bad_symbols") or extract_bad_symbols_from_dream(dream_sum))
        dream_bad_regimes = set(dream_sum.get("bad_regimes") or extract_bad_regimes_from_dream(dream_sum))

    # collect events per symbol per lane per window
    per = {}  # per[symbol][lane]["7d"|"24h"] -> list(events)
    with open(TRADES) as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if not is_close(e):
                continue
            dt = parse_ts(e)
            if not dt:
                continue
            ln = lane_of(e)
            if ln not in ("core", "exploration"):
                continue  # exclude recovery from promotion scoring

            # Use canonical promotion sample filter for exploration
            if ln == "exploration" and not is_promo_sample_close(e, ln):
                continue

            sym = e.get("symbol")
            if not sym:
                continue

            bucket = None
            if dt >= cut_7d:
                bucket = "7d"
            if dt >= cut_24h:
                # also include in 24h bucket
                per.setdefault(sym, {}).setdefault(ln, {}).setdefault("24h", []).append(e)
            if bucket == "7d":
                per.setdefault(sym, {}).setdefault(ln, {}).setdefault("7d", []).append(e)

    out = {
        "generated_at": iso(now),
        "window": {"lookback_days": LOOKBACK_DAYS, "lookback_hours": LOOKBACK_HOURS},
        "global": {"notes": []},
        "symbols": {},
        **get_promotion_filter_metadata(),
        **get_promotion_gate_metadata(),
    }

    syms = sorted(set(per.keys()) | blocked)
    for sym in syms:
        rec = {"action": "hold", "confidence": 0.5, "reasons": []}

        if sym in blocked:
            rec["action"] = "blocked"
            rec["confidence"] = 1.0
            rec["reasons"].append("quarantined_blocked")
            out["symbols"][sym] = rec
            continue

        core_7d = (per.get(sym, {}).get("core", {}).get("7d") or [])
        exp_7d = (per.get(sym, {}).get("exploration", {}).get("7d") or [])
        core_24h = (per.get(sym, {}).get("core", {}).get("24h") or [])
        exp_24h = (per.get(sym, {}).get("exploration", {}).get("24h") or [])

        m_core = compute_metrics(core_7d)
        m_exp = compute_metrics(exp_7d)

        rec["core"] = {"7d": m_core, "24h": compute_metrics(core_24h)}
        rec["exploration"] = {"7d": m_exp, "24h": compute_metrics(exp_24h)}

        # delta fields (7d)
        pf_core = m_core["pf"]
        pf_exp = m_exp["pf"]
        wr_core = m_core["win_rate"] if m_core["win_rate"] is not None else 0.0
        wr_exp = m_exp["win_rate"] if m_exp["win_rate"] is not None else 0.0
        dd_core = m_core["max_drawdown"]
        dd_exp = m_exp["max_drawdown"]

        rec["delta"] = {
            "pf": (pf_exp - pf_core) if (math.isfinite(pf_exp) and math.isfinite(pf_core)) else None,
            "win_rate": wr_exp - wr_core,
            "dd": dd_exp - dd_core,
        }

        # dream context tags
        if sym in dream_bad_symbols:
            rec["reasons"].append("dream_warning")
            rec["confidence"] *= 0.7

        # promotion logic
        n_exp = m_exp["n_closes"]

        if n_exp < PROMOTE_MIN_N:
            rec["action"] = "hold"
            rec["reasons"].append(f"insufficient_exploration_sample<{PROMOTE_MIN_N}")
            rec["confidence"] = min(rec["confidence"], 0.6)
        else:
            promote = (
                pf_exp >= PROMOTE_PF and
                wr_exp >= PROMOTE_WR and
                dd_exp <= PROMOTE_MAX_DD and
                (pf_exp - pf_core) >= PROMOTE_PF_DELTA
            )
            demote = (
                pf_exp < DEMOTE_PF or
                dd_exp > DEMOTE_MAX_DD
            )

            if promote:
                rec["action"] = "promote_candidate"
                rec["reasons"].append("exploration_outperforms_core")
                rec["confidence"] = min(1.0, rec["confidence"] + 0.3)
            elif demote:
                rec["action"] = "demote_candidate"
                rec["reasons"].append("exploration_underperforms_or_high_dd")
                rec["confidence"] = min(rec["confidence"], 0.6)
            else:
                rec["action"] = "hold"
                rec["reasons"].append("no_clear_edge")

        out["symbols"][sym] = rec

    with open(OUT, "w") as f:
        json.dump(out, f, indent=2)

    print(f"Promotion advice written: {OUT}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

