"""Wallet Hunter - Phase 34.2 (Alchemy seed discovery).

Paper-only module that discovers active wallets via Alchemy's getAssetTransfers,
computes lightweight heuristics, and emits mirror hunter artifacts. If no
Alchemy key is configured the module produces an empty snapshot and exits.
"""

from __future__ import annotations

import json
import math
import os
import statistics
import time
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # pragma: no cover - optional dependency
    import requests
except Exception:  # pragma: no cover
    requests = None

try:  # pragma: no cover
    import yaml
except Exception:  # pragma: no cover
    yaml = None

from engine_alpha.core.paths import CONFIG, REPORTS

CONFIG_PATH = CONFIG / "wallet_hunter.yaml"
OUTPUT_DIR = REPORTS / "mirror"
HUNTER_SNAPSHOT = OUTPUT_DIR / "hunter_snapshot.json"
HUNTER_CANDIDATES = OUTPUT_DIR / "hunter_candidates.json"
TARGETS_PATH = OUTPUT_DIR / "targets.json"
COUNCIL_PATH = REPORTS / "council_weights.json"

DEFAULT_CFG = {
    "lookback_hours": 48,
    "provider": "alchemy",
    "seed_mode": "discover",
    "max_candidates": 50,
    "top_targets": 8,
    "min_tx_count": 3,
    "exclude_hot_wallets": ["binance", "okx", "coinbase"],
    "cap_notional_native": 5000.0,
    "bot_interval_s": 90,
    "token_min_unique": 2,
    "token_seeds": [
        "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "0xC02aaA39b223FE8D0A0E5C4F27eAD9083C756Cc2",
        "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    ],
}

MAX_TRANSFERS_PER_SEED = 2000
MAX_TRANSFERS_PER_ADDRESS = 300
MAX_ADDRESSES = 200


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_config() -> Dict[str, Any]:
    cfg = DEFAULT_CFG.copy()
    if CONFIG_PATH.exists() and yaml is not None:
        try:
            data = yaml.safe_load(CONFIG_PATH.read_text()) or {}
            if isinstance(data, dict):
                cfg.update(data)
        except Exception:
            pass
    return cfg


def _alchemy_key() -> str:
    return os.getenv("ALCHEMY_API_KEY", "")


def _write_json(path: Path, payload: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2))
    except Exception:
        pass


def _call_alchemy(session: requests.Session, api_key: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    endpoint = f"https://eth-mainnet.g.alchemy.com/v2/{api_key}"
    payload = {"jsonrpc": "2.0", "id": 1, "method": "alchemy_getAssetTransfers", "params": [params]}
    try:
        resp = session.post(endpoint, json=payload, timeout=8)
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


def _parse_timestamp(ts_str: Optional[str]) -> Optional[datetime]:
    if not isinstance(ts_str, str):
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return None


def _alchemy_fetch_transfers(
    session: requests.Session,
    api_key: str,
    base_params: Dict[str, Any],
    cutoff: datetime,
    max_items: int,
) -> List[Dict[str, Any]]:
    transfers: List[Dict[str, Any]] = []
    page_key: Optional[str] = None
    fetched = 0
    while fetched < max_items:
        params = dict(base_params)
        if page_key:
            params["pageKey"] = page_key
        data = _call_alchemy(session, api_key, params)
        if not isinstance(data, dict):
            break
        result = data.get("result")
        if not isinstance(result, dict):
            break
        batch = result.get("transfers")
        if not isinstance(batch, list) or not batch:
            break
        stop_due_cutoff = False
        for tx in batch:
            metadata = tx.get("metadata") or {}
            ts = _parse_timestamp(metadata.get("blockTimestamp"))
            if ts and ts < cutoff:
                stop_due_cutoff = True
                continue
            transfers.append(tx)
            fetched += 1
            if fetched >= max_items:
                break
        page_key = result.get("pageKey")
        if not page_key or stop_due_cutoff or fetched >= max_items:
            break
    return transfers


def _discover_addresses(
    session: requests.Session,
    cfg: Dict[str, Any],
    api_key: str,
    cutoff: datetime,
) -> List[str]:
    addresses: Counter[str] = Counter()
    token_seeds = cfg.get("token_seeds")
    if not isinstance(token_seeds, list):
        token_seeds = DEFAULT_CFG["token_seeds"]
    for token in token_seeds:
        params = {
            "fromBlock": "0x0",
            "toBlock": "latest",
            "category": ["erc20", "external"],
            "withMetadata": True,
            "excludeZeroValue": True,
            "contractAddresses": [token],
            "maxCount": "0x3e8",
            "order": "desc",
        }
        transfers = _alchemy_fetch_transfers(session, api_key, params, cutoff, MAX_TRANSFERS_PER_SEED)
        for tx in transfers:
            for field in ("from", "to"):
                addr = tx.get(field)
                if isinstance(addr, str) and addr.startswith("0x") and len(addr) == 42:
                    addresses[addr.lower()] += 1
    min_tx = int(cfg.get("min_tx_count", 3))
    candidates = [addr for addr, count in addresses.items() if count >= min_tx]
    candidates.sort(key=lambda a: addresses[a], reverse=True)
    return candidates[:MAX_ADDRESSES]


def _collect_address_records(
    session: requests.Session,
    cfg: Dict[str, Any],
    api_key: str,
    address: str,
    cutoff: datetime,
) -> List[Dict[str, Any]]:
    params_base = {
        "category": ["erc20", "external"],
        "withMetadata": True,
        "excludeZeroValue": False,
        "maxCount": "0x190",  # 400
        "order": "desc",
    }
    records: List[Dict[str, Any]] = []
    for key_field in ("fromAddress", "toAddress"):
        params = dict(params_base)
        params[key_field] = address
        records.extend(_alchemy_fetch_transfers(session, api_key, params, cutoff, MAX_TRANSFERS_PER_ADDRESS))
    # Deduplicate by (hash, direction)
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for tx in sorted(records, key=lambda x: _parse_timestamp((x.get("metadata") or {}).get("blockTimestamp")) or datetime.now(timezone.utc)):
        direction = "out" if tx.get("from", "").lower() == address else "in"
        key_pair = (tx.get("hash"), direction)
        if key_pair in seen:
            continue
        seen.add(key_pair)
        deduped.append({**tx, "direction": direction})
    return deduped[:MAX_TRANSFERS_PER_ADDRESS]


def _score_address(address: str, records: List[Dict[str, Any]], cfg: Dict[str, Any]) -> Dict[str, Any]:
    if not records:
        return {}
    lookback_hours = int(cfg.get("lookback_hours", 48))
    trade_count = len(records)
    timestamps: List[float] = []
    token_addresses: Counter[str] = Counter()
    direction_changes = 0
    last_direction = None
    buys_preceding = 0
    buy_events = 0

    sorted_records = sorted(
        records,
        key=lambda tx: _parse_timestamp((tx.get("metadata") or {}).get("blockTimestamp")) or datetime.now(timezone.utc),
    )

    for tx in sorted_records:
        ts = _parse_timestamp((tx.get("metadata") or {}).get("blockTimestamp"))
        if ts:
            timestamps.append(ts.timestamp())
        token_addr = (tx.get("rawContract") or {}).get("address") or "ETH"
        token_addresses[token_addr] += 1
        direction = tx.get("direction")
        if direction == "in":
            buy_events += 1
        if last_direction and direction and direction != last_direction:
            direction_changes += 1
        if direction == "in" and ts:
            # simple heuristic: check if another event within 10 minutes afterwards
            window_end = ts.timestamp() + 600
            if any((other_ts > ts.timestamp()) and (other_ts <= window_end) for other_ts in timestamps):
                buys_preceding += 1
        if direction:
            last_direction = direction

    diversity = len(token_addresses)
    intervals = [j - i for i, j in zip(timestamps[:-1], timestamps[1:]) if j >= i]
    if intervals:
        std_interval = statistics.pstdev(intervals)
        bot_likelihood = 1.0 - min(1.0, std_interval / 3600.0)
    else:
        bot_likelihood = 0.0

    repeatability = 0.0
    if token_addresses:
        repeatability = min(1.0, max(token_addresses.values()) / 10.0)

    notional_score = min(1.0, trade_count / 50.0)
    early_entry = buys_preceding / buy_events if buy_events else 0.5
    profit_score = min(1.0, direction_changes / trade_count) if trade_count else 0.0

    diversity_component = min(1.0, diversity / 5.0)
    final_score = (
        0.35 * profit_score
        + 0.15 * repeatability
        + 0.15 * bot_likelihood
        + 0.15 * diversity_component
        + 0.10 * notional_score
        + 0.10 * early_entry
    )
    final_score = max(0.0, min(1.0, final_score))

    return {
        "address": address,
        "final_score": round(final_score, 4),
        "metrics": {
            "trade_count": trade_count,
            "diversity": diversity,
            "bot_likelihood": round(bot_likelihood, 4),
            "repeatability": round(repeatability, 4),
            "notional_score": round(notional_score, 4),
            "early_entry": round(early_entry, 4),
            "profit_score": round(profit_score, 4),
        },
    }


def run_once() -> Dict[str, Any]:
    cfg = _load_config()
    api_key = _alchemy_key()
    provider = "alchemy" if api_key else "none"
    lookback_hours = int(cfg.get("lookback_hours", 48))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if provider == "none" or requests is None:
        snapshot = {
            "ts": _now(),
            "provider": "none",
            "lookback_hours": lookback_hours,
            "checked": 0,
            "eligible": 0,
            "top_targets": 0,
        }
        _write_json(HUNTER_SNAPSHOT, snapshot)
        _write_json(HUNTER_CANDIDATES, [])
        _write_json(TARGETS_PATH, [])
        return {"snapshot": snapshot, "candidates": [], "targets": []}

    session = requests.Session()

    discovered: List[str] = []
    seed_mode = str(cfg.get("seed_mode", "discover")).lower()
    if seed_mode == "discover":
        discovered = _discover_addresses(session, cfg, api_key, cutoff)
    else:
        mirror_cfg: Dict[str, Any] = {}
        if yaml and (CONFIG / "mirror.yaml").exists():
            try:
                mirror_cfg = yaml.safe_load((CONFIG / "mirror.yaml").read_text()) or {}
            except Exception:
                mirror_cfg = {}
        targets_cfg = mirror_cfg.get("targets") if isinstance(mirror_cfg, dict) else None
        if isinstance(targets_cfg, list):
            discovered = [addr.lower() for addr in targets_cfg if isinstance(addr, str)]

    filtered: List[str] = discovered[:MAX_ADDRESSES]

    behaviour: List[Dict[str, Any]] = []
    for address in filtered:
        records = _collect_address_records(session, cfg, api_key, address, cutoff)
        if len(records) < int(cfg.get("min_tx_count", 3)):
            continue
        scored = _score_address(address, records, cfg)
        if scored:
            behaviour.append(scored)
        if len(behaviour) >= int(cfg.get("max_candidates", 50)):
            break

    behaviour.sort(key=lambda item: item.get("final_score", 0.0), reverse=True)
    top_targets = [entry["address"] for entry in behaviour[: int(cfg.get("top_targets", 8))]]

    snapshot = {
        "ts": _now(),
        "provider": provider,
        "lookback_hours": lookback_hours,
        "checked": len(discovered),
        "eligible": len(behaviour),
        "top_targets": len(top_targets),
    }

    _write_json(HUNTER_SNAPSHOT, snapshot)
    _write_json(HUNTER_CANDIDATES, behaviour)
    _write_json(TARGETS_PATH, top_targets)

    return {"snapshot": snapshot, "candidates": behaviour, "targets": top_targets}


if __name__ == "__main__":  # manual diagnostic
    print(json.dumps(run_once(), indent=2))
