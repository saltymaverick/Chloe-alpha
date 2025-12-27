from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from dateutil import parser

ENGINE_CONFIG_PATH = Path("config/engine_config.json")
TRADES_PATH = Path("reports/trades.jsonl")
ROLLBACK_LOG_PATH = Path("reports/gpt/shadow_promotion_rollbacks.jsonl")

PF_FLOOR = 0.95
LOSS_SHARE_LIMIT = 0.50
LOSS_STREAK_LIMIT = 3
LOOKBACK_HOURS = 24


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


def _load_engine_config() -> Dict[str, Any]:
    cfg = _load_json(ENGINE_CONFIG_PATH, {})
    if not isinstance(cfg, dict):
        cfg = {}
    cfg.setdefault("core_promotions", {})
    return cfg


def _save_engine_config(cfg: Dict[str, Any]) -> None:
    _write_json(ENGINE_CONFIG_PATH, cfg)


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


def _ts(e: Dict[str, Any]) -> datetime | None:
    ts = e.get("ts") or e.get("timestamp") or e.get("time")
    if not ts:
        return None
    try:
        return parser.isoparse(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _compute_pf(returns: List[float]) -> float | None:
    if not returns:
        return None
    gp = sum(r for r in returns if r > 0)
    gl = -sum(r for r in returns if r < 0)
    if gp == 0 and gl == 0:
        return 1.0
    if gl == 0:
        return float("inf")
    return gp / gl


def _compute_loss_share(returns: List[float]) -> float:
    losses = -sum(r for r in returns if r < 0)
    wins = sum(r for r in returns if r > 0)
    total = losses + wins
    if total <= 0:
        return 0.0
    return losses / total


def _loss_streak(returns: List[float]) -> int:
    streak = 0
    max_streak = 0
    for r in returns:
        if r < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return max_streak


def main() -> None:
    cfg = _load_engine_config()
    promos = cfg.get("core_promotions", {})
    if not promos:
        return

    cutoff = _now() - timedelta(hours=LOOKBACK_HOURS)
    returns_by_sym: Dict[str, List[float]] = {}

    for e in _iter_trades() or []:
        if not _is_close(e):
            continue
        sym = e.get("symbol")
        if not sym or sym not in promos:
            continue
        ts = _ts(e)
        if ts is None or ts < cutoff:
            continue
        p = _pct(e)
        if p is None:
            continue
        returns_by_sym.setdefault(sym, []).append(p)

    rolled = 0
    for sym, promo in list(promos.items()):
        if not promo.get("enabled"):
            continue
        # expiry check
        exp_raw = promo.get("expires_at")
        if exp_raw:
            try:
                if datetime.fromisoformat(exp_raw) <= _now():
                    promo["enabled"] = False
                    promo["expired_at"] = _iso(_now())
                    promos[sym] = promo
                    continue
            except Exception:
                pass

        rets = returns_by_sym.get(sym, [])
        pf = _compute_pf(rets)
        loss_share = _compute_loss_share(rets)
        loss_streak = _loss_streak(rets)

        should_rollback = False
        reason = None
        if pf is not None and pf < PF_FLOOR:
            should_rollback = True
            reason = f"pf_24h<{PF_FLOOR}"
        if loss_share > LOSS_SHARE_LIMIT:
            should_rollback = True
            reason = f"loss_share>{LOSS_SHARE_LIMIT}"
        if loss_streak >= LOSS_STREAK_LIMIT:
            should_rollback = True
            reason = f"loss_streak>={LOSS_STREAK_LIMIT}"

        if should_rollback:
            promo["enabled"] = False
            promo["rolled_back_at"] = _iso(_now())
            promo["rollback_reason"] = reason
            promos[sym] = promo
            ROLLBACK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with ROLLBACK_LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "ts": _iso(_now()),
                            "symbol": sym,
                            "pf_24h": pf,
                            "loss_share": loss_share,
                            "loss_streak": loss_streak,
                            "reason": reason,
                        }
                    )
                    + "\n"
                )
            rolled += 1

    cfg["core_promotions"] = promos
    _save_engine_config(cfg)


if __name__ == "__main__":
    main()

