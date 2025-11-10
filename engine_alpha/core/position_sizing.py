"""Position sizing helpers for risk-weighted execution (paper-only)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import yaml

from engine_alpha.core.paths import CONFIG, REPORTS

ACCOUNTING_PATH = CONFIG / "accounting.yaml"
EQUITY_LIVE_PATH = REPORTS / "equity_live.json"

__all__ = [
    "cfg",
    "load_cfg",
    "risk_fraction",
    "compute_R",
    "can_open",
    "pretrade_check",
    "read_equity_live",
    "write_equity_live",
    "json_timestamp",
]


_DEFAULTS = {
    "start_equity_live": 10000.0,
    "risk_per_trade_bps": 100,
    "max_gross_exposure_r": 4.0,
    "max_symbol_exposure_r": 2.0,
    "slippage_bps_cap": 50,
    "spread_bps_cap": 25,
    "reject_if_spread_bps_gt": 20,
    "reject_if_latency_ms_gt": 2000,
    "write_live_equity": True,
}


def _load_accounting() -> Dict[str, Any]:
    if ACCOUNTING_PATH.exists():
        try:
            data = yaml.safe_load(ACCOUNTING_PATH.read_text()) or {}
            if isinstance(data, dict):
                merged = _DEFAULTS.copy()
                merged.update({k: v for k, v in data.items() if k in merged})
                return merged
        except Exception:
            return _DEFAULTS.copy()
    return _DEFAULTS.copy()


def cfg() -> Dict[str, Any]:
    return _load_accounting()


def load_cfg() -> Dict[str, Any]:
    return cfg()


def risk_fraction(conf: Dict[str, Any] | None = None) -> float:
    data = conf or cfg()
    return float(data.get("risk_per_trade_bps", _DEFAULTS["risk_per_trade_bps"])) / 10000.0


def compute_R(equity_live: float, conf: Dict[str, Any] | None = None) -> float:
    fraction = risk_fraction(conf)
    return max(0.0, equity_live * fraction)


# Backwards compatibility alias (if earlier phases referenced compute_size_r)
compute_size_r = compute_R


def can_open(current_exposure_r: float, symbol_exposure_r: float, conf: Dict[str, Any] | None = None) -> bool:
    data = conf or cfg()
    gross_cap = float(data.get("max_gross_exposure_r", _DEFAULTS["max_gross_exposure_r"]))
    symbol_cap = float(data.get("max_symbol_exposure_r", _DEFAULTS["max_symbol_exposure_r"]))
    return current_exposure_r < gross_cap and symbol_exposure_r < symbol_cap


def pretrade_check(spread_bps: float | None, latency_ms: float | None, conf: Dict[str, Any] | None = None) -> bool:
    data = conf or cfg()
    spread_limit = float(data.get("reject_if_spread_bps_gt", _DEFAULTS["reject_if_spread_bps_gt"]))
    latency_limit = float(data.get("reject_if_latency_ms_gt", _DEFAULTS["reject_if_latency_ms_gt"]))
    if spread_bps is not None and spread_bps > spread_limit:
        return False
    if latency_ms is not None and latency_ms > latency_limit:
        return False
    return True


def read_equity_live() -> float:
    if EQUITY_LIVE_PATH.exists():
        try:
            data = json.loads(EQUITY_LIVE_PATH.read_text())
            if isinstance(data, dict):
                value = data.get("equity")
                if isinstance(value, (int, float)):
                    return float(value)
        except Exception:
            pass
    return float(cfg().get("start_equity_live", _DEFAULTS["start_equity_live"]))


def write_equity_live(value: float) -> None:
    EQUITY_LIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"equity": float(value), "ts": json_timestamp()}
    EQUITY_LIVE_PATH.write_text(json.dumps(payload, indent=2))


def json_timestamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
