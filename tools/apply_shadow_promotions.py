from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

STATE_PATH = Path("reports/gpt/shadow_promotion_apply_state.json")
PROPOSALS_PATH = Path("reports/gpt/shadow_promotions.jsonl")
APPLIED_LOG_PATH = Path("reports/gpt/shadow_promotion_applied.jsonl")
ENGINE_CONFIG_PATH = Path("config/engine_config.json")
RECOVERY_RAMP_PATH = Path("reports/risk/recovery_ramp.json")
QUARANTINE_PATH = Path("reports/risk/quarantine.json")
CAPITAL_PROTECTION_PATH = Path("reports/risk/capital_protection.json")

PROMO_TTL_HOURS = 48
APPLY_COOLDOWN_HOURS = 1  # max 1 promotion per hour


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def _load_state() -> Dict[str, Any]:
    return _load_json(STATE_PATH, {"last_line": -1, "last_processed_ts": None, "last_applied_at": None})


def _save_state(state: Dict[str, Any]) -> None:
    _write_json(STATE_PATH, state)


def _load_engine_config() -> Dict[str, Any]:
    cfg = _load_json(ENGINE_CONFIG_PATH, {})
    if not isinstance(cfg, dict):
        cfg = {}
    cfg.setdefault("core_promotions", {})
    return cfg


def _save_engine_config(cfg: Dict[str, Any]) -> None:
    _write_json(ENGINE_CONFIG_PATH, cfg)


def _gates_pass() -> bool:
    rr = _load_json(RECOVERY_RAMP_PATH, {})
    gates = rr.get("gates") or {}
    if not all(gates.values()) if isinstance(gates, dict) else False:
        return False
    hysteresis = rr.get("hysteresis") or {}
    needed = rr.get("needed_ok_ticks") or hysteresis.get("needed_ok_ticks") or hysteresis.get("needed") or 0
    ok = hysteresis.get("ok_ticks") or 0
    if needed and ok < needed:
        return False
    return True


def _capital_mode_normal() -> bool:
    cap = _load_json(CAPITAL_PROTECTION_PATH, {})
    return (cap.get("global") or {}).get("mode") == "normal"


def _is_blocked(symbol: str) -> bool:
    q = _load_json(QUARANTINE_PATH, {})
    blocked = q.get("blocked_symbols") or q.get("blocked") or q.get("symbols") or []
    if isinstance(blocked, dict):
        blocked = list(blocked.keys())
    return symbol in set(str(s).upper() for s in blocked)


def _log_applied(entry: Dict[str, Any]) -> None:
    APPLIED_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with APPLIED_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def main() -> None:
    state = _load_state()
    last_line = state.get("last_line", -1)
    last_applied_at_raw = state.get("last_applied_at")
    last_applied_at = None
    if last_applied_at_raw:
        try:
            last_applied_at = datetime.fromisoformat(last_applied_at_raw)
        except Exception:
            last_applied_at = None

    proposals = []
    if PROPOSALS_PATH.exists():
        with PROPOSALS_PATH.open("r", encoding="utf-8") as f:
            for idx, line in enumerate(f):
                if idx <= last_line:
                    continue
                try:
                    proposals.append((idx, json.loads(line)))
                except Exception:
                    continue

    if not proposals:
        state["last_processed_ts"] = _iso(_now())
        _save_state(state)
        return

    cfg = _load_engine_config()
    promos = cfg.get("core_promotions", {})

    applied_now = False
    for idx, proposal in proposals:
        sym = str(proposal.get("symbol") or "").upper()
        if not sym:
            continue

        # throttle: 1 per hour
        if last_applied_at and (_now() - last_applied_at) < timedelta(hours=APPLY_COOLDOWN_HOURS):
            state["last_line"] = idx
            continue

        # safety gates
        if not _gates_pass():
            state["last_line"] = idx
            continue
        if not _capital_mode_normal():
            state["last_line"] = idx
            continue
        if _is_blocked(sym):
            state["last_line"] = idx
            continue

        existing = promos.get(sym, {})
        # skip if already enabled and not expired
        if existing.get("enabled") and existing.get("expires_at"):
            try:
                exp_dt = datetime.fromisoformat(existing["expires_at"])
                if exp_dt > _now():
                    state["last_line"] = idx
                    continue
            except Exception:
                pass

        applied_at = _iso(_now())
        expires_at = _iso(_now() + timedelta(hours=PROMO_TTL_HOURS))
        promos[sym] = {
            "enabled": True,
            "source": "shadow_promotion",
            "applied_at": applied_at,
            "expires_at": expires_at,
            "risk_mult_cap": 0.25,
            "max_positions": 1,
            "notes": ["option_a_safe_caps"],
        }
        cfg["core_promotions"] = promos
        _save_engine_config(cfg)

        _log_applied(
            {
                "ts": applied_at,
                "symbol": sym,
                "proposal": proposal,
                "action": "applied",
                "expires_at": expires_at,
            }
        )

        last_applied_at = _now()
        state["last_applied_at"] = _iso(last_applied_at)
        state["last_line"] = idx
        applied_now = True

    state["last_processed_ts"] = _iso(_now())
    _save_state(state)


if __name__ == "__main__":
    main()

