from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from engine_alpha.core.paths import CONFIG, REPORTS

_OPPORTUNIST_DIR = REPORTS / "opportunist"
_OPPORTUNIST_DIR.mkdir(parents=True, exist_ok=True)

UNIVERSE_STATE_PATH = _OPPORTUNIST_DIR / "universe_state.json"
SEED_PATH = CONFIG / "opportunist_universe_seed.json"


@dataclass
class UniverseEntry:
    symbol: str
    realized_vol_15m: float
    realized_vol_1h: float
    avg_liquidity_usd: float
    last_seen_ts: str
    active: bool = True

    def composite_score(self) -> float:
        liquidity = max(self.avg_liquidity_usd, 1.0)
        return (self.realized_vol_15m * 0.6 + self.realized_vol_1h * 0.4) * liquidity


def load_seed_symbols() -> List[str]:
    if not SEED_PATH.exists():
        return []
    try:
        payload = json.loads(SEED_PATH.read_text())
    except json.JSONDecodeError:
        return []
    symbols = payload.get("symbols", []) or []
    normalized = []
    for sym in symbols:
        if not isinstance(sym, str):
            continue
        sym_u = sym.upper()
        if sym_u.endswith("USDT"):
            normalized.append(sym_u)
    # Preserve ordering while removing duplicates
    seen = set()
    deduped = []
    for sym in normalized:
        if sym in seen:
            continue
        seen.add(sym)
        deduped.append(sym)
    return deduped


def load_universe_state() -> Dict[str, UniverseEntry]:
    if not UNIVERSE_STATE_PATH.exists():
        return {}
    try:
        payload = json.loads(UNIVERSE_STATE_PATH.read_text())
    except json.JSONDecodeError:
        return {}
    entries: Dict[str, UniverseEntry] = {}
    for symbol, data in (payload.get("symbols") or {}).items():
        if not isinstance(data, dict):
            continue
        entries[symbol] = UniverseEntry(
            symbol=symbol,
            realized_vol_15m=float(data.get("realized_vol_15m", 0.0)),
            realized_vol_1h=float(data.get("realized_vol_1h", 0.0)),
            avg_liquidity_usd=float(data.get("avg_liquidity_usd", 0.0)),
            last_seen_ts=str(data.get("last_seen_ts", "")),
            active=bool(data.get("active", True)),
        )
    return entries


def save_universe_state(entries: Dict[str, UniverseEntry]) -> None:
    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbols": {
            symbol: {
                "realized_vol_15m": entry.realized_vol_15m,
                "realized_vol_1h": entry.realized_vol_1h,
                "avg_liquidity_usd": entry.avg_liquidity_usd,
                "last_seen_ts": entry.last_seen_ts,
                "active": entry.active,
            }
            for symbol, entry in entries.items()
        },
    }
    UNIVERSE_STATE_PATH.write_text(json.dumps(snapshot, indent=2))


def get_active_universe(max_symbols: int = 50) -> List[str]:
    entries = load_universe_state()
    if entries:
        ranked = sorted(
            (entry for entry in entries.values() if entry.active),
            key=lambda e: e.composite_score(),
            reverse=True,
        )
        symbols = [entry.symbol for entry in ranked[:max_symbols] if entry.composite_score() > 0]
        if symbols:
            return symbols
    seeds = load_seed_symbols()
    if seeds and not entries:
        now = datetime.now(timezone.utc).isoformat()
        bootstrap = {
            sym: UniverseEntry(
                symbol=sym,
                realized_vol_15m=0.0,
                realized_vol_1h=0.0,
                avg_liquidity_usd=0.0,
                last_seen_ts=now,
                active=True,
            )
            for sym in seeds
        }
        save_universe_state(bootstrap)
    return seeds[:max_symbols] if max_symbols else seeds


def update_universe_stats(
    symbol: str,
    *,
    realized_vol_15m: float,
    realized_vol_1h: float,
    liquidity_usd: float,
) -> None:
    entries = load_universe_state()
    now = datetime.now(timezone.utc).isoformat()
    entry = entries.get(symbol)
    if entry is None:
        entry = UniverseEntry(
            symbol=symbol,
            realized_vol_15m=0.0,
            realized_vol_1h=0.0,
            avg_liquidity_usd=0.0,
            last_seen_ts=now,
            active=True,
        )
    alpha = 0.3
    entry.realized_vol_15m = (1 - alpha) * entry.realized_vol_15m + alpha * max(realized_vol_15m, 0.0)
    entry.realized_vol_1h = (1 - alpha) * entry.realized_vol_1h + alpha * max(realized_vol_1h, 0.0)
    entry.avg_liquidity_usd = (1 - alpha) * entry.avg_liquidity_usd + alpha * max(liquidity_usd, 0.0)
    entry.last_seen_ts = now
    entry.active = True
    entries[symbol] = entry
    save_universe_state(entries)


__all__ = [
    "UniverseEntry",
    "get_active_universe",
    "load_seed_symbols",
    "load_universe_state",
    "save_universe_state",
    "update_universe_stats",
]

