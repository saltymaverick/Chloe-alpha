#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any

from engine_alpha.reflect.promotion_filters import (
    is_promo_sample_close,
    get_promotion_filter_metadata,
)
from engine_alpha.reflect.promotion_gates import (
    get_promotion_gate_spec,
    get_promotion_gate_metadata,
)

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
SYMBOL_STATES_PATH = REPORTS / "risk" / "symbol_states.json"
AUTO_PROMOS_PATH = REPORTS / "risk" / "auto_promotions.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _compute_canonical_exploration_samples(symbol: str) -> Dict[str, Any]:
    """
    Compute canonical promotion sample counts for exploration trades.
    Returns dict with 'n_7d', 'pf_7d', etc.
    """
    from dateutil import parser

    def _profit_factor(returns):
        """Simple profit factor calculation."""
        if not returns:
            return None
        gp = sum(r for r in returns if r > 0)
        gl = -sum(r for r in returns if r < 0)
        if gp == 0 and gl == 0:
            return 1.0
        if gl == 0:
            return float("inf")
        return gp / gl

    trades_path = Path("reports/trades.jsonl")
    if not trades_path.exists():
        return {"n_7d": 0, "pf_7d": None}

    now = datetime.now(timezone.utc)
    cutoff_7d = now - timedelta(days=7)

    returns = []
    n_7d = 0

    with trades_path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                trade = json.loads(line.strip())
            except Exception:
                continue

            if not is_promo_sample_close(trade, "exploration"):
                continue

            if trade.get("symbol") != symbol:
                continue

            ts_str = trade.get("ts")
            if not ts_str:
                continue

            try:
                ts = parser.isoparse(ts_str.replace("Z", "+00:00"))
            except Exception:
                continue

            if ts >= cutoff_7d:
                pct = trade.get("pct")
                if pct is not None:
                    try:
                        returns.append(float(pct))
                        n_7d += 1
                    except (ValueError, TypeError):
                        continue

    pf_7d = _profit_factor(returns)

    return {
        "n_7d": n_7d,
        "pf_7d": pf_7d,
        "returns_7d": returns,
    }


def build_auto_promotions(symbol_states: dict) -> Dict[str, Any]:
    promos_all: Dict[str, Any] = {}
    promos_active: Dict[str, Any] = {}
    symbols = (symbol_states.get("symbols") or {}) if isinstance(symbol_states, dict) else {}
    now = _now()
    expires_at = _iso(now + timedelta(hours=48))

    for sym, st in symbols.items():
        if not isinstance(st, dict):
            continue

            # Get canonical exploration sample metrics and gate spec
        exp_samples = _compute_canonical_exploration_samples(sym)
        spec = get_promotion_gate_spec()

        quarantined = bool(st.get("quarantined"))
        stance = st.get("stance")
        pf7 = st.get("pf_7d")  # Keep using symbol state PF (includes all trades)
        n7_exp = exp_samples["n_7d"]  # Use canonical exploration sample count
        pf7_exp = exp_samples["pf_7d"]  # Use canonical exploration PF
        pf30 = st.get("pf_30d")
        loss_streak_24h = st.get("metrics", {}).get("loss_streak_24h")

        eligible = (
            not quarantined
            and stance not in {"halt"}
            and pf7_exp is not None  # Require exploration PF >= gate threshold
            and pf7_exp >= spec.min_exploration_pf
            and n7_exp >= spec.min_exploration_closes_7d  # Require canonical exploration samples >= gate threshold
        )

        demote = (
            quarantined
            or (pf7_exp is not None and pf7_exp < 1.00)  # Demote if exploration PF < 1.00
            or (loss_streak_24h is not None and loss_streak_24h >= 2)
            or (pf30 is not None and pf30 < 1.00)
        )

        promo: Dict[str, Any] = {
            "enabled": False,
            "risk_mult_cap": spec.probation_risk_mult_cap,  # Use spec probation cap
            "max_positions": spec.probation_max_positions,  # Use spec probation positions
            "expires_at": expires_at,
        }

        if eligible and not demote:
            promo["enabled"] = True
            promo["reason"] = "auto_promo_exploration_samples"
            promos_active[sym] = promo.copy()
        else:
            trigger = "quarantine" if quarantined else "exploration_pf7d_lt_1.00" if (pf7_exp is not None and pf7_exp < 1.00) else "loss_streak_24h" if (loss_streak_24h is not None and loss_streak_24h >= 2) else "pf30d_lt_1.00" if (pf30 is not None and pf30 < 1.00) else "insufficient_exploration_samples" if n7_exp < 20 else "ineligible"
            promo["reason"] = f"auto_demote_{trigger}"

        promos_all[sym] = promo

    return {
        "generated_at": _iso(now),
        "active": promos_active,
        "all": promos_all,
        **get_promotion_filter_metadata(),
        **get_promotion_gate_metadata(),
    }


def main() -> int:
    states = _load_json(SYMBOL_STATES_PATH)
    promos = build_auto_promotions(states)
    AUTO_PROMOS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AUTO_PROMOS_PATH.open("w", encoding="utf-8") as f:
        json.dump(promos, f, indent=2, sort_keys=True)
    print(f"auto_promotions written to {AUTO_PROMOS_PATH}")
    print(f"active_count={len(promos.get('active', {}))} active={list(promos.get('active', {}).keys())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

