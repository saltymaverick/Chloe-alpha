from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from engine_alpha.core.paths import CONFIG, REPORTS
from engine_alpha.risk.symbol_state import load_symbol_states

SCORES_PATH = REPORTS / "gpt" / "shadow_promotion_scores.json"
QUARANTINE_PATH = REPORTS / "risk" / "quarantine.json"
ENGINE_CONFIG_PATH = CONFIG / "engine_config.json"

OUT_STATE_PATH = REPORTS / "gpt" / "exploration_accelerator_state.json"
OUT_JSON_PATH = REPORTS / "gpt" / "exploration_accelerator.json"
OUT_LOG_PATH = REPORTS / "gpt" / "exploration_accelerator_log.jsonl"

TRADES_PATH = REPORTS / "trades.jsonl"

TTL_HOURS_DEFAULT = 24
COOLDOWN_MIN_SECONDS = 900
COOLDOWN_TARGET_SECONDS = 1200
CAP_DELTA = 1  # bounded to +1 by requirement


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def _append_log(entry: Dict[str, Any]) -> None:
    OUT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _is_promoted(symbol: str, engine_cfg: Dict[str, Any], now_dt: datetime) -> bool:
    promos = engine_cfg.get("core_promotions", {}) or {}
    promo = promos.get(symbol)
    if not promo or promo.get("enabled") is not True:
        return False
    expires_at = promo.get("expires_at")
    if expires_at:
        try:
            exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if now_dt > exp_dt:
                return False
        except Exception:
            return False
    return True


def _loss_streak_24h(symbol: str, now_dt: datetime) -> int:
    """Compute consecutive exploration losses in the last 24h, newest-first."""
    cutoff = now_dt - timedelta(hours=24)
    streak = 0
    try:
        with TRADES_PATH.open("r", encoding="utf-8") as f:
            for line in reversed(f.readlines()):
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if (e.get("type") or "").lower() != "close":
                    continue
                if e.get("symbol") != symbol:
                    continue
                if (e.get("trade_kind") or "").lower() != "exploration":
                    continue
                ts = e.get("ts")
                if not ts:
                    continue
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except Exception:
                    continue
                if dt < cutoff:
                    continue
                pct = e.get("pct") or e.get("pnl_pct")
                try:
                    pct_val = float(pct)
                except Exception:
                    pct_val = 0.0
                if pct_val < 0:
                    streak += 1
                else:
                    break  # streak broken by non-loss
    except Exception:
        return 0
    return streak


def _ttl_hours(engine_cfg: Dict[str, Any]) -> int:
    # allow optional override in config, else default
    try:
        return int(engine_cfg.get("exploration_accelerator_ttl_hours", TTL_HOURS_DEFAULT))
    except Exception:
        return TTL_HOURS_DEFAULT


def _load_quarantine() -> set:
    q = _read_json(QUARANTINE_PATH) or {}
    blocked = q.get("blocked_symbols") or []
    try:
        return set(str(s).upper() for s in blocked)
    except Exception:
        return set()


def _load_scores() -> Dict[str, Any]:
    data = _read_json(SCORES_PATH)
    return data if isinstance(data, dict) else {}


def _load_engine_config() -> Dict[str, Any]:
    cfg = _read_json(ENGINE_CONFIG_PATH)
    return cfg if isinstance(cfg, dict) else {}


def _save_engine_config(cfg: Dict[str, Any]) -> None:
    _write_json(ENGINE_CONFIG_PATH, cfg)


def _apply_or_refresh_override(
    symbol: str,
    now_dt: datetime,
    ttl_hours: int,
    overrides: Dict[str, Any],
    reason: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    created_at = overrides.get("created_at") or now_dt.isoformat()
    expires_at = (now_dt + timedelta(hours=ttl_hours)).isoformat()
    overrides.update(
        {
            "enabled": True,
            "exploration_cap_delta": CAP_DELTA,
            "cooldown_seconds": max(COOLDOWN_MIN_SECONDS, COOLDOWN_TARGET_SECONDS),
            "created_at": created_at,
            "expires_at": expires_at,
            "reason": reason,
            "source": "exploration_accelerator",
        }
    )
    log_entry = {
        "ts": now_dt.isoformat(),
        "symbol": symbol,
        "action": "apply",
        "reason": reason,
        "expires_at": expires_at,
    }
    _append_log(log_entry)
    return overrides, log_entry


def _rollback_override(symbol: str, overrides: Dict[str, Any], reason: str, now_dt: datetime) -> None:
    overrides["enabled"] = False
    overrides["rolled_back_at"] = now_dt.isoformat()
    overrides["rollback_reason"] = reason
    _append_log(
        {
            "ts": now_dt.isoformat(),
            "symbol": symbol,
            "action": "rollback",
            "reason": reason,
        }
    )


def _symbol_meets_activation(sym_entry: Dict[str, Any]) -> bool:
    exp7 = (sym_entry.get("exploration") or {}).get("7d") or {}
    pf7 = exp7.get("pf")
    mdd7 = exp7.get("max_drawdown")
    n7 = exp7.get("n_closes", 0)
    if not isinstance(pf7, (int, float)) or not isinstance(mdd7, (int, float)):
        return False
    return n7 >= 20 and pf7 >= 1.10 and mdd7 <= 0.025


def _symbol_pf24(sym_entry: Dict[str, Any]) -> Optional[float]:
    exp24 = (sym_entry.get("exploration") or {}).get("24h") or {}
    pf24 = exp24.get("pf")
    if isinstance(pf24, (int, float)):
        return pf24
    return None


def main() -> int:
    now_dt = _now()
    scores = _load_scores()
    if not scores or "symbols" not in scores:
        print("No scores available; skipping accelerator.")
        return 0

    quarantine = _load_quarantine()
    engine_cfg = _load_engine_config()
    overrides_map = engine_cfg.get("exploration_overrides") or {}
    ttl_hours = _ttl_hours(engine_cfg)
    symbol_states = load_symbol_states()
    symbol_policy_map = symbol_states.get("symbols") if isinstance(symbol_states, dict) else {}

    state = _read_json(OUT_STATE_PATH) or {}
    applied_symbols: List[str] = []

    symbols = scores.get("symbols", {})
    for sym, entry in symbols.items():
        sym_u = sym.upper()

        if sym_u in quarantine:
            if sym_u in overrides_map and overrides_map[sym_u].get("enabled"):
                _rollback_override(sym_u, overrides_map[sym_u], "quarantined", now_dt)
            continue

        if _is_promoted(sym_u, engine_cfg, now_dt):
            # Do not accelerate symbols already promoted
            continue

        # Respect symbol policy: allow_exploration must be true
        sym_policy = symbol_policy_map.get(sym_u, {}) if isinstance(symbol_policy_map, dict) else {}
        if not sym_policy.get("allow_exploration", False):
            continue

        # Activation check
        if not _symbol_meets_activation(entry):
            continue

        pf24 = _symbol_pf24(entry)
        loss_streak = _loss_streak_24h(sym_u, now_dt)

        override = overrides_map.get(sym_u, {})

        # Check rollback conditions for active overrides
        if override.get("enabled"):
            expired = False
            exp_at = override.get("expires_at")
            if exp_at:
                try:
                    exp_dt = datetime.fromisoformat(exp_at.replace("Z", "+00:00"))
                    expired = now_dt > exp_dt
                except Exception:
                    expired = False
            if expired or (pf24 is not None and pf24 < 0.95) or loss_streak >= 3:
                reason = "expired" if expired else ("pf24_below_0.95" if pf24 is not None and pf24 < 0.95 else "loss_streak_ge_3")
                _rollback_override(sym_u, override, reason, now_dt)
                overrides_map[sym_u] = override
                continue

        # Apply/refresh override
        updated, _ = _apply_or_refresh_override(
            sym_u,
            now_dt,
            ttl_hours,
            override,
            reason="near_promotion_accelerator",
        )
        overrides_map[sym_u] = updated
        applied_symbols.append(sym_u)

    # Remove expired overrides that were not refreshed
    for sym, override in list(overrides_map.items()):
        if not override.get("enabled"):
            continue
        exp_at = override.get("expires_at")
        expired = False
        if exp_at:
            try:
                exp_dt = datetime.fromisoformat(exp_at.replace("Z", "+00:00"))
                expired = now_dt > exp_dt
            except Exception:
                expired = False
        if expired and sym not in applied_symbols:
            _rollback_override(sym, override, "expired", now_dt)
            overrides_map[sym] = override

    engine_cfg["exploration_overrides"] = overrides_map
    _save_engine_config(engine_cfg)

    summary = {
        "generated_at": now_dt.isoformat(),
        "applied_symbols": applied_symbols,
        "ttl_hours": ttl_hours,
        "overrides": overrides_map,
    }
    _write_json(OUT_JSON_PATH, summary)
    _write_json(
        OUT_STATE_PATH,
        {
            "last_run": now_dt.isoformat(),
            "applied_symbols": applied_symbols,
        },
    )

    print(f"Exploration accelerator run complete. Applied={len(applied_symbols)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

