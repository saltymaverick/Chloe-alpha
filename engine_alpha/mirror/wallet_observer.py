"""Wallet observer - Phase 34.1 (read-only, paper-only).

Fetches wallet activity via Alchemy or Etherscan (preferring Alchemy when keys
are available), derives behaviour scores, and emits mirror artifacts. All
network access is fail-soft; missing API keys simply result in empty outputs.
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
    import requests  # pragma: no cover
except Exception:  # pragma: no cover - requests may be absent
    requests = None

try:
    import yaml  # pragma: no cover
except Exception:  # pragma: no cover - yaml may be missing
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
    "provider": "auto",
    "lookback_hours": 24,
    "min_usd_notional": 0.0,
    "max_candidates": 5,
    "min_score": 0.65,
    "targets": [],
}


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
    """Public helper for other modules."""
    return _load_config()


def _get_api_keys() -> Dict[str, str]:
    return {
        "alchemy": os.getenv("ALCHEMY_API_KEY", ""),
        "etherscan": os.getenv("ETHERSCAN_API_KEY", ""),
    }


def _select_provider(cfg: Dict[str, Any], keys: Dict[str, str]) -> Tuple[str, str]:
    provider = (cfg.get("provider") or "auto").lower()
    if provider == "alchemy":
        return ("alchemy", keys.get("alchemy", "")) if keys.get("alchemy") else ("none", "")
    if provider == "etherscan":
        return ("etherscan", keys.get("etherscan", "")) if keys.get("etherscan") else ("none", "")
    if keys.get("alchemy"):
        return "alchemy", keys["alchemy"]
    if keys.get("etherscan"):
        return "etherscan", keys["etherscan"]
    return "none", ""


def _within_lookback(ts: int | float, lookback_hours: int) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    try:
        dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except Exception:
        return False
    return dt >= cutoff


def _normalize_observation(
    address: str,
    tx_hash: str,
    ts: datetime,
    direction: str,
    from_addr: str,
    to_addr: str,
    asset: str,
    amount: Optional[float],
    value_native: Optional[float],
    token_symbol: Optional[str],
    token_value: Optional[float],
    protocol: str,
) -> Dict[str, Any]:
    return {
        "address": address,
        "ts": ts.isoformat(),
        "hash": tx_hash,
        "protocol": protocol,
        "direction": direction,
        "from": from_addr,
        "to": to_addr,
        "asset": asset,
        "amount": amount,
        "value_native": value_native,
        "token_symbol": token_symbol,
        "token_value": token_value,
    }


def _etherscan_txlist(address: str, cfg: Dict[str, Any], api_key: str) -> List[Dict[str, Any]]:
    if not api_key or requests is None:
        return []
    lookback_hours = int(cfg.get("lookback_hours", 24))
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
        resp = requests.get("https://api.etherscan.io/api", params=params, timeout=8)
        if resp.status_code != 200:
            return []
        data = resp.json()
    except Exception:
        return []
    result = data.get("result") if isinstance(data, dict) else None
    if not isinstance(result, list):
        return []

    records: List[Dict[str, Any]] = []
    for tx in result:
        try:
            ts_int = int(tx.get("timeStamp"))
        except Exception:
            continue
        if not _within_lookback(ts_int, lookback_hours):
            continue
        tx_hash = tx.get("hash") or ""
        dt = datetime.fromtimestamp(ts_int, tz=timezone.utc)
        try:
            value_eth = float(tx.get("value", 0)) / 1e18
        except Exception:
            value_eth = None
        direction = "out" if tx.get("from", "").lower() == address.lower() else "in"
        records.append(
            _normalize_observation(
                address=address,
                tx_hash=tx_hash,
                ts=dt,
                direction=direction,
                from_addr=tx.get("from", "").lower(),
                to_addr=tx.get("to", "").lower(),
                asset="ETH",
                amount=value_eth,
                value_native=value_eth,
                token_symbol=None,
                token_value=None,
                protocol="etherscan",
            )
        )
        if len(records) >= 1000:
            break
    return records


def _etherscan_tokentx(address: str, cfg: Dict[str, Any], api_key: str) -> List[Dict[str, Any]]:
    if not api_key or requests is None:
        return []
    lookback_hours = int(cfg.get("lookback_hours", 24))
    params = {
        "module": "account",
        "action": "tokentx",
        "address": address,
        "startblock": 0,
        "endblock": 99999999,
        "sort": "desc",
        "apikey": api_key,
    }
    try:
        resp = requests.get("https://api.etherscan.io/api", params=params, timeout=8)
        if resp.status_code != 200:
            return []
        data = resp.json()
    except Exception:
        return []
    result = data.get("result") if isinstance(data, dict) else None
    if not isinstance(result, list):
        return []

    records: List[Dict[str, Any]] = []
    for tx in result:
        try:
            ts_int = int(tx.get("timeStamp"))
        except Exception:
            continue
        if not _within_lookback(ts_int, lookback_hours):
            continue
        tx_hash = tx.get("hash") or tx.get("transactionHash") or ""
        dt = datetime.fromtimestamp(ts_int, tz=timezone.utc)
        try:
            decimals = int(tx.get("tokenDecimal", 0))
            scale = 10 ** decimals
        except Exception:
            scale = 1
        try:
            token_value = float(tx.get("value", 0)) / scale
        except Exception:
            token_value = None
        direction = "out" if tx.get("from", "").lower() == address.lower() else "in"
        records.append(
            _normalize_observation(
                address=address,
                tx_hash=tx_hash,
                ts=dt,
                direction=direction,
                from_addr=tx.get("from", "").lower(),
                to_addr=tx.get("to", "").lower(),
                asset="TOKEN",
                amount=token_value,
                value_native=None,
                token_symbol=tx.get("tokenSymbol"),
                token_value=token_value,
                protocol="etherscan",
            )
        )
        if len(records) >= 1000:
            break
    return records


def _alchemy_fetch(address: str, cfg: Dict[str, Any], api_key: str) -> List[Dict[str, Any]]:
    if not api_key or requests is None:
        return []
    lookback_hours = int(cfg.get("lookback_hours", 24))
    endpoint = f"https://eth-mainnet.g.alchemy.com/v2/{api_key}"
    headers = {"Content-Type": "application/json"}

    def _call(params: Dict[str, Any]) -> List[Dict[str, Any]]:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "alchemy_getAssetTransfers",
            "params": [params],
        }
        try:
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=8)
            if resp.status_code != 200:
                return []
            data = resp.json()
            transfers = data.get("result", {}).get("transfers", [])
            return transfers if isinstance(transfers, list) else []
        except Exception:
            return []

    transfers: List[Dict[str, Any]] = []
    params_base = {
        "category": ["external", "erc20"],
        "withMetadata": True,
        "maxCount": "0x3E8",
        "order": "desc",
        "excludeZeroValue": False,
    }

    for direction, field in (("out", "fromAddress"), ("in", "toAddress")):
        params = params_base.copy()
        params[field] = address
        for tx in _call(params):
            metadata = tx.get("metadata") or {}
            ts_str = metadata.get("blockTimestamp")
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")) if ts_str else None
            except Exception:
                ts = None
            if not ts or not _within_lookback(ts.timestamp(), lookback_hours):
                continue
            tx_hash = tx.get("hash") or ""
            amount = None
            try:
                amount = float(tx.get("value", 0.0))
            except Exception:
                amount = None
            asset = tx.get("asset", "ETH")
            token_symbol = None
            token_value = None
            erc20_meta = tx.get("erc20Metadata") if isinstance(tx.get("erc20Metadata"), dict) else None
            if erc20_meta:
                token_symbol = erc20_meta.get("symbol")
                token_value = amount
            transfers.append(
                _normalize_observation(
                    address=address,
                    tx_hash=tx_hash,
                    ts=ts,
                    direction=direction,
                    from_addr=(tx.get("from") or "").lower(),
                    to_addr=(tx.get("to") or "").lower(),
                    asset=asset,
                    amount=amount,
                    value_native=amount if asset == "ETH" else None,
                    token_symbol=token_symbol,
                    token_value=token_value,
                    protocol="alchemy",
                )
            )
            if len(transfers) >= 1000:
                break
        if len(transfers) >= 1000:
            break
    return transfers


def _fetch_records(address: str, cfg: Dict[str, Any], provider: str, key: str) -> List[Dict[str, Any]]:
    if provider == "alchemy":
        return _alchemy_fetch(address, cfg, key)
    if provider == "etherscan":
        records = _etherscan_txlist(address, cfg, key)
        records.extend(_etherscan_tokentx(address, cfg, key))
        return records
    return []


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


def _score_metrics(records: List[Dict[str, Any]], lookback_hours: int) -> Dict[str, Any]:
    trade_count = len(records)
    daily_pace = trade_count / (lookback_hours / 24.0) if lookback_hours else trade_count
    assets = {rec.get("asset") or rec.get("token_symbol") for rec in records}
    assets.discard(None)
    diversity = len(assets)

    pace_component = 0.2 if daily_pace >= 1 else 0.0
    volume_component = min(trade_count / 10.0, 1.0) * 0.3
    diversity_component = min(diversity / 5.0, 1.0) * 0.5
    score = min(1.0, max(0.0, pace_component + volume_component + diversity_component))

    return {
        "trade_count": trade_count,
        "daily_pace": daily_pace,
        "diversity": diversity,
        "score": round(score, 4),
    }


def run_once() -> Dict[str, Any]:
    cfg = _load_config()
    api_keys = _get_api_keys()
    provider, provider_key = _select_provider(cfg, api_keys)

    targets = cfg.get("targets") or []
    if not isinstance(targets, list):
        targets = []

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        TARGETS_PATH.write_text(json.dumps(targets, indent=2))
    except Exception:
        pass

    lookback_hours = int(cfg.get("lookback_hours", 24))

    all_observed: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    total_records = 0

    if provider != "none":
        dedupe_hashes: set[Tuple[str, str]] = set()
        for target in targets:
            if not isinstance(target, str) or not target:
                continue
            records = _fetch_records(target.lower(), cfg, provider, provider_key)
            filtered: List[Dict[str, Any]] = []
            for record in records:
                key_pair = (record.get("hash", ""), record.get("direction", ""))
                if key_pair in dedupe_hashes:
                    continue
                dedupe_hashes.add(key_pair)
                filtered.append(record)
            total_records += _append_observations(filtered)
            all_observed[target.lower()].extend(filtered)

    behavior: Dict[str, Any] = {
        address: _score_metrics(records, lookback_hours)
        for address, records in all_observed.items()
    }
    try:
        BEHAVIOR_PATH.write_text(json.dumps(behavior, indent=2))
    except Exception:
        pass

    snapshot = {
        "ts": _now(),
        "provider": provider,
        "targets": len(targets),
        "obs_count": total_records,
        "addresses_scored": len(behavior),
    }
    try:
        SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2))
    except Exception:
        pass

    return {
        "config": cfg,
        "snapshot": snapshot,
        "behavior": behavior,
    }


if __name__ == "__main__":  # manual diagnostic
    print(json.dumps(run_once(), indent=2))
