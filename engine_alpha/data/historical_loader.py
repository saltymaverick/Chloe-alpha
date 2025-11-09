"""
Historical data loader - Phase 23
Loads OHLCV data from csv/parquet/ccxt/synthetic sources with caching.
"""

from __future__ import annotations

import csv
import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine_alpha.core.paths import DATA

try:  # Optional dependency
    import pandas as _pd  # type: ignore
except Exception:  # pragma: no cover
    _pd = None

CACHE_DIR = DATA / "ohlcv"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_path(symbol: str, timeframe: str) -> Path:
    return CACHE_DIR / f"{symbol}_{timeframe}.parquet"


def _meta_path(symbol: str, timeframe: str) -> Path:
    return CACHE_DIR / f"{symbol}_{timeframe}.meta.json"


def save_cache(symbol: str, timeframe: str, rows: List[Dict[str, Any]], meta: Dict[str, Any]) -> None:
    if _pd is None:
        _meta_path(symbol, timeframe).write_text(json.dumps(meta, indent=2))
        return
    df = _pd.DataFrame(rows)
    df.to_parquet(_cache_path(symbol, timeframe), index=False)
    _meta_path(symbol, timeframe).write_text(json.dumps(meta, indent=2))


def load_cache(symbol: str, timeframe: str) -> Optional[List[Dict[str, Any]]]:
    if _pd is None:
        return None
    path = _cache_path(symbol, timeframe)
    if not path.exists():
        return None
    try:
        df = _pd.read_parquet(path)
        return _normalize(df.to_dict(orient="records"))
    except Exception:
        return None


def _normalize(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        try:
            ts = row.get("ts") or row.get("timestamp")
            if ts is None:
                continue
            if isinstance(ts, (int, float)):
                ts = datetime.utcfromtimestamp(ts / 1000 if ts > 1e12 else ts).isoformat() + "Z"
            elif isinstance(ts, str) and not ts.endswith("Z"):
                ts = ts
            out.append(
                {
                    "ts": str(ts),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume", 0.0)),
                }
            )
        except Exception:
            continue
    return out


def _load_csv(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return _normalize(rows)


def _load_parquet(path: Path) -> List[Dict[str, Any]]:
    if _pd is None:
        raise RuntimeError("Parquet support unavailable (pandas missing)")
    df = _pd.read_parquet(path)
    return _normalize(df.to_dict(orient="records"))


def _load_ccxt(symbol: str, timeframe: str, start: str, end: str, cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        import ccxt  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("ccxt not available") from exc

    exchange_id = cfg.get("ccxt", {}).get("exchange", "binanceus")
    rate_limit = cfg.get("ccxt", {}).get("rate_limit_ms", 300)
    if not hasattr(ccxt, exchange_id):
        raise RuntimeError(f"ccxt exchange {exchange_id} not found")
    exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True})
    since = exchange.parse8601(start)
    end_ts = exchange.parse8601(end)
    all_rows: List[Dict[str, Any]] = []
    while since < end_ts:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=500)
        if not ohlcv:
            break
        for row in ohlcv:
            ts = datetime.utcfromtimestamp(row[0] / 1000).isoformat() + "Z"
            all_rows.append(
                {
                    "ts": ts,
                    "open": row[1],
                    "high": row[2],
                    "low": row[3],
                    "close": row[4],
                    "volume": row[5],
                }
            )
        since = ohlcv[-1][0] + exchange.parse_timeframe(timeframe) * 1000
        if rate_limit:
            exchange.sleep(rate_limit)
    return all_rows


def _seconds_from_timeframe(timeframe: str) -> int:
    unit = timeframe[-1]
    value = int(timeframe[:-1])
    if unit.lower() == "m":
        return value * 60
    if unit.lower() == "h":
        return value * 3600
    if unit.lower() == "d":
        return value * 86400
    raise ValueError(f"Unsupported timeframe: {timeframe}")


def _synthetic(symbol: str, timeframe: str, start: str, end: str, seed: int) -> List[Dict[str, Any]]:
    random.seed(seed)
    start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
    step = timedelta(seconds=_seconds_from_timeframe(timeframe))
    rows: List[Dict[str, Any]] = []
    price = 1000.0
    ts = start_dt
    while ts < end_dt:
        change = random.uniform(-0.02, 0.02)
        open_price = price
        close_price = price * (1 + change)
        high_price = max(open_price, close_price) * (1 + random.uniform(0, 0.01))
        low_price = min(open_price, close_price) * (1 - random.uniform(0, 0.01))
        volume = random.uniform(10, 100)
        rows.append(
            {
                "ts": ts.isoformat().replace("+00:00", "Z"),
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume": volume,
            }
        )
        price = close_price
        ts += step
    return rows


def load_ohlcv(symbol: str, timeframe: str, start: str, end: str, cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    cached = load_cache(symbol, timeframe)
    if cached:
        return cached

    source = cfg.get("source", "csv")
    rows: List[Dict[str, Any]]
    if source == "csv":
        csv_path = Path(cfg.get("csv_glob", "").format(symbol=symbol, timeframe=timeframe))
        if not csv_path.exists():
            raise FileNotFoundError(csv_path)
        rows = _load_csv(csv_path)
    elif source == "parquet":
        parquet_path = Path(cfg.get("parquet_path", "").format(symbol=symbol, timeframe=timeframe))
        if not parquet_path.exists():
            raise FileNotFoundError(parquet_path)
        rows = _load_parquet(parquet_path)
    elif source == "ccxt":
        rows = _load_ccxt(symbol, timeframe, start, end, cfg)
    elif source == "synthetic":
        rows = _synthetic(symbol, timeframe, start, end, cfg.get("seed", 42))
    else:
        raise ValueError(f"Unsupported source: {source}")

    rows = [row for row in rows if start <= row["ts"] < end]
    if rows and source != "synthetic" and _pd is not None:
        save_cache(
            symbol,
            timeframe,
            rows,
            {
                "source": source,
                "start": start,
                "end": end,
            },
        )
    return rows
