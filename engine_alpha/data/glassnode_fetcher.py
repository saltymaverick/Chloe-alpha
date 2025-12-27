# engine_alpha/data/glassnode_fetcher.py

from __future__ import annotations

from pathlib import Path
from typing import Dict, Any
import datetime as dt

import pandas as pd

from engine_alpha.data.glassnode_client import GlassnodeConfig, GlassnodeClient, load_glassnode_config

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
GLASSNODE_DIR = DATA_DIR / "glassnode"
GLASSNODE_DIR.mkdir(parents=True, exist_ok=True)


def _symbol_cache_path(symbol: str) -> Path:
    return GLASSNODE_DIR / f"{symbol}_glassnode.parquet"


def fetch_glassnode_metrics_for_symbol(
    symbol: str,
    days_back: int = 365,
) -> pd.DataFrame:
    """
    Fetch Glassnode metrics for the given symbol over the last `days_back` days.
    Returns a DataFrame with 'ts' and one column per metric (e.g. 'gn_exchange_netflow').
    Caches to data/glassnode/{symbol}_glassnode.parquet.
    """
    try:
        cfg: GlassnodeConfig = load_glassnode_config()
    except FileNotFoundError:
        print(f"[Glassnode] Config not found, skipping fetch for {symbol}")
        return pd.DataFrame()
    except Exception as e:
        print(f"[Glassnode] Config load error for {symbol}: {e}")
        return pd.DataFrame()

    try:
        client = GlassnodeClient(cfg)
    except ValueError as e:
        print(f"[Glassnode] Client init failed for {symbol}: {e}")
        return pd.DataFrame()

    end = dt.datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    start = end - dt.timedelta(days=days_back)

    frames = []
    for metric_name in cfg.metrics.keys():
        try:
            raw = client.fetch_metric(symbol, metric_name, start=start, end=end)
        except Exception as e:
            print(f"[Glassnode] Error fetching {metric_name} for {symbol}: {e}")
            continue

        if not raw:
            continue

        df = pd.DataFrame(raw)
        # Glassnode uses 't' for unix timestamp seconds, 'v' for value
        df["ts"] = pd.to_datetime(df["t"], unit="s", utc=True)
        df = df[["ts", "v"]].rename(columns={"v": f"gn_{metric_name}"})
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    merged = frames[0]
    for df in frames[1:]:
        merged = merged.merge(df, on="ts", how="outer")

    merged = merged.sort_values("ts").reset_index(drop=True)

    # cache
    cache_path = _symbol_cache_path(symbol)
    merged.to_parquet(cache_path)
    print(f"[Glassnode] Cached {len(merged)} rows for {symbol} to {cache_path}")

    return merged


def load_cached_glassnode_metrics(symbol: str) -> pd.DataFrame:
    """
    Load cached Glassnode metrics for a symbol, if available.
    """
    path = _symbol_cache_path(symbol)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception as e:
        print(f"[Glassnode] Error loading cached metrics for {symbol}: {e}")
        return pd.DataFrame()


