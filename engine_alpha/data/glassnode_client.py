# engine_alpha/data/glassnode_client.py

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, List
import json
import requests
import datetime as dt

ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"
GLASSNODE_CONFIG_PATH = CONFIG_DIR / "glassnode_config.json"


@dataclass
class GlassnodeConfig:
    api_key: str
    base_url: str
    assets: Dict[str, str]
    metrics: Dict[str, str]
    default_params: Dict[str, Any]


def load_glassnode_config() -> GlassnodeConfig:
    if not GLASSNODE_CONFIG_PATH.exists():
        raise FileNotFoundError(f"Glassnode config not found at {GLASSNODE_CONFIG_PATH}")
    data = json.loads(GLASSNODE_CONFIG_PATH.read_text())
    return GlassnodeConfig(
        api_key=data.get("api_key", ""),
        base_url=data.get("base_url", "https://api.glassnode.com/v1/metrics"),
        assets=data.get("assets", {}),
        metrics=data.get("metrics", {}),
        default_params=data.get("default_params", {"frequency": "24h"}),
    )


class GlassnodeClient:
    def __init__(self, cfg: GlassnodeConfig):
        self.cfg = cfg
        if not self.cfg.api_key or self.cfg.api_key == "YOUR_GLASSNODE_API_KEY_HERE":
            raise ValueError("Glassnode API key is missing or not configured in glassnode_config.json")

    def fetch_metric(
        self,
        symbol: str,
        metric_name: str,
        start: dt.datetime,
        end: dt.datetime,
        extra_params: Dict[str, Any] | None = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch a metric for a given symbol between start and end.
        Returns list of {t: timestamp, v: value}.
        """
        asset_code = self.cfg.assets.get(symbol)
        if not asset_code:
            raise ValueError(f"No Glassnode asset mapping found for symbol {symbol}")

        endpoint = self.cfg.metrics.get(metric_name)
        if not endpoint:
            raise ValueError(f"No Glassnode metric endpoint configured for {metric_name}")

        url = self.cfg.base_url.rstrip("/") + endpoint

        params: Dict[str, Any] = {
            "a": asset_code,
            "api_key": self.cfg.api_key,
            "s": int(start.timestamp()),
            "u": int(end.timestamp()),
        }
        params.update(self.cfg.default_params)
        if extra_params:
            params.update(extra_params)

        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        # Glassnode typically returns [{"t": 1609459200, "v": 123.45}, ...]
        if not isinstance(data, list):
            raise ValueError(f"Unexpected Glassnode response for {metric_name}: {data}")

        return data


