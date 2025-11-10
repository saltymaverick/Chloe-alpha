"""Wallet observer - Phase 34 (read-only, paper-only).

Fetches wallet activity from supported providers (Alchemy/Etherscan) using
read-only APIs, derives lightweight behaviour scores, and emits mirror
artifacts for downstream evolution modules.
"""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:  # optional dependency
    import requests
except Exception:  # pragma: no cover - requests may be absent
    requests = None

try:  # yaml is optional but expected in this project
    import yaml
except Exception:  # pragma: no cover - fail-soft if yaml missing
    yaml = None

from engine_alpha.core.paths import CONFIG, REPORTS

CONFIG_PATH = CONFIG / "mirror.yaml"
OUTPUT_DIR = REPORTS / "mirror"
OBSERVATIONS_PATH = OUTPUT_DIR / "observations.jsonl"
TARGETS_PATH = OUTPUT_DIR / "targets.json"
BEHAVIOR_PATH = OUTPUT_DIR / "behavior.json"
SNAPSHOT_PATH = OUTPUT_DIR / "observer_snapshot.json"

DEFAULT_CFG = {
    "chain": "ethereum",
    "provider": "alchemy",
    "lookback_hours": 24,
    "min_usd_notional": 500.0,
    "max_candidates": 5,
    "min_score": 0.65,
    "targets": [],
}

ETH_PRICE_FALLBACK = 1800.0  # crude USD approximation when pricing unavailable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_config() -> Dict[str, Any]:
    cfg = DEFAULT_CFG.copy()
    if CONFIG_PATH.exists() and yaml is not None:
        try:
            loaded = yaml.safe_load(CONFIG_PATH.read_text()) or {}
            if isinstance(loaded, dict):
                cfg.update(loaded)
        except Exception:
            pass
    return cfg


def load_config() -> Dict[str, Any]:
    """Public helper for other modules to obtain mirror observer config."""
    return _load_config()


def _get_api_keys() -> Dict[str, str]:
    return {
        "alchemy": os.getenv("ALCHEMY_API_KEY", ""),
        "etherscan": os.getenv("ETHERSCAN_API_KEY", ""),
    }


def _within_lookback(ts: int, lookback_hours: int) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    try:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    except Exception:
        return False
    return dt >= cutoff


def _normalize_tx(address: str, tx: Dict[str, Any], notional_usd: float) -> Dict[str, Any]:
    ts_val = tx.get("timeStamp") or tx.get("blockTime") or int(time.time())
    try:
        ts_int = int(ts_val)
    except Exception:
        ts_int = int(time.time())
    return {
        "address": address,
        "ts": datetime.fromtimestamp(ts_int, tz=timezone.utc).isoformat(),
        "hash": tx.get("hash") or tx.get("transactionHash") or "unknown",
        "protocol": tx.get("protocol") or "uniswapv3",
        "side": tx.get("side") or ("buy" if notional_usd >= 0 else "sell"),
        "base": tx.get("base") or "ETH",
        "quote": tx.get("quote") or "USD",
        "notional_usd": float(notional_usd),
        "fee_bps": float(tx.get("fee_bps", 0.0)),
    }


def _etherscan_fetch(address: str, cfg: Dict[str, Any], api_key: str) -> List[Dict[str, Any]]:
    if not api_key or requests is None:
        return []
    lookback_hours = int(cfg.get("lookback_hours", 24))
    url = "https://api.etherscan.io/api"
    params = {
        "module": "account",
        "action": "txlist",
        "address": address,
        "startblock": 0,
        "endblock": 99999999,
        "sort": "desc",
        "apikey": api_key,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            return []
        data = resp.json()
    except Exception:
        return []
    result = data.get("result") if isinstance(data, dict) else None
    if not isinstance(result, list):
        return []
    records: List[Dict[str, Any]] = []
    min_notional = float(cfg.get("min_usd_notional", 0.0))
    for tx in result:
        try:
            ts_int = int(tx.get("timeStamp"))
        except Exception:
            continue
        if not _within_lookback(ts_int, lookback_hours):
            continue
        value = tx.get("value")
        try:
            value_eth = float(value) / 1e18
        except Exception:
            value_eth = 0.0
        notional = value_eth * ETH_PRICE_FALLBACK
        if notional < min_notional:
            continue
        records.append(_normalize_tx(address, tx, notional))
        if len(records) >= 50:  # cap per wallet to keep payload limited
            break
    return records


def _alchemy_fetch(address: str, cfg: Dict[str, Any], api_key: str) -> List[Dict[str, Any]]:
    # For now, we reuse Etherscan logic because basic REST support is limited.
    # Users can switch provider: "etherscan" for richer data.
    return _etherscan_fetch(address, cfg, api_key)


def _fetch_records(address: str, cfg: Dict[str, Any], api_keys: Dict[str, str]) -> List[Dict[str, Any]]:
    provider = (cfg.get("provider") or "alchemy").lower()
    if provider == "etherscan":
        return _etherscan_fetch(address, cfg, api_keys.get("etherscan", ""))
    return _alchemy_fetch(address, cfg, api_keys.get("alchemy", ""))


def _append_observations(records: Iterable[Dict[str, Any]]) -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    count = 0
    try:
        with OBSERVATIONS_PATH.open("a") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")
                count += 1
    except Exception:
        return count
    return count


def _score_metrics(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    trade_count = len(records)
    notional_sum = sum(float(r.get("notional_usd", 0.0)) for r in records)
    wins = sum(1 for r in records if r.get("side") == "sell")
    win_rate = wins / trade_count if trade_count else 0.0
    avg_notional = notional_sum / trade_count if trade_count else 0.0
    avg_hold = 0.0  # placeholder; requires position tracking

    score = min(
        1.0,
        max(0.0, win_rate * 0.5 + min(1.0, trade_count / 50.0) * 0.25 + min(1.0, notional_sum / 5000.0) * 0.25),
    )

    return {
        "trade_count": trade_count,
        "win_rate": win_rate,
        "avg_hold": avg_hold,
        "notional_sum": notional_sum,
        "avg_notional": avg_notional,
        "score": round(score, 4),
    }


def run_once() -> Dict[str, Any]:
    cfg = _load_config()
    api_keys = _get_api_keys()
    targets = cfg.get("targets") or []
    if not isinstance(targets, list):
        targets = []

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TARGETS_PATH.write_text(json.dumps(targets, indent=2))

    all_observed: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    total_records = 0

    for target in targets:
        if not isinstance(target, str) or not target:
            continue
        records = _fetch_records(target, cfg, api_keys)
        total_records += _append_observations(records)
        all_observed[target].extend(records)

    behavior: Dict[str, Any] = {}
    for address, records in all_observed.items():
        behavior[address] = _score_metrics(records)
    BEHAVIOR_PATH.write_text(json.dumps(behavior, indent=2))

    snapshot = {
        "ts": _now(),
        "targets": len(targets),
        "observations": total_records,
        "addresses_scored": len(behavior),
    }
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2))

    return {
        "config": cfg,
        "snapshot": snapshot,
        "behavior": behavior,
    }


if __name__ == "__main__":  # manual diagnostic
    print(json.dumps(run_once(), indent=2))
