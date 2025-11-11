#!/usr/bin/env python3
"""Normalize equity curve using fixed risk per trade."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

import yaml

from engine_alpha.core.paths import CONFIG, REPORTS

CONFIG_PATH = CONFIG / "accounting.yaml"
TRADES_PATH = REPORTS / "trades.jsonl"
EQUITY_OUT = REPORTS / "equity_curve_norm.jsonl"
PF_OUT = REPORTS / "pf_local_norm.json"
SUMMARY_OUT = REPORTS / "equity_norm_summary.json"

DEFAULTS: Dict[str, Any] = {
    "start_equity_norm": 10000.0,
    "start_equity_live": 10000.0,
    "risk_per_trade_bps": 25,
    "cap_adj_pct": 0.005,
    "fees_bps_default": 50,
    "slip_bps_default": 15,
    "batch_noise_bps": 20,
}


def _load_config() -> Dict[str, Any]:
    cfg = DEFAULTS.copy()
    if CONFIG_PATH.exists():
        try:
            data = yaml.safe_load(CONFIG_PATH.read_text()) or {}
            if isinstance(data, dict):
                for key, value in data.items():
                    cfg[key] = value
        except Exception:
            pass
    return cfg


def _iter_closes(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    closes: List[Dict[str, Any]] = []
    try:
        for raw in path.read_text().splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            event = str(obj.get("type") or obj.get("event") or "").lower()
            if event == "close":
                closes.append(obj)
    except Exception:
        return []
    return closes


def _noise_from_trade(trade: Dict[str, Any], noise_bps: float) -> float:
    if noise_bps <= 0:
        return 0.0
    seed_parts = [
        str(trade.get("ts") or trade.get("exit_ts") or ""),
        str(trade.get("id") or trade.get("trade_id") or ""),
        str(trade.get("pct") or trade.get("pnl_pct") or ""),
        str(trade.get("direction") or trade.get("dir") or ""),
    ]
    seed = "|".join(seed_parts).encode("utf-8")
    digest = hashlib.sha256(seed).digest()
    rand = int.from_bytes(digest[:8], "big") / float(1 << 64)
    return (rand * 2.0 - 1.0) * (noise_bps / 10000.0)


def _pf_from_returns(returns: List[float]) -> float:
    if not returns:
        return 0.0
    pos_sum = sum(r for r in returns if r > 0)
    neg_sum = sum(r for r in returns if r < 0)
    if neg_sum < 0:
        return pos_sum / abs(neg_sum)
    if pos_sum > 0:
        return float("inf")
    return 0.0


def main() -> int:
    cfg = _load_config()
    closes = _iter_closes(TRADES_PATH)

    start_equity = float(
        cfg.get("start_equity_norm", cfg.get("start_equity_live", DEFAULTS["start_equity_live"]))
    )
    risk_fraction = float(cfg.get("risk_per_trade_bps", DEFAULTS["risk_per_trade_bps"])) / 10000.0
    cap_pct = float(cfg.get("cap_adj_pct", DEFAULTS["cap_adj_pct"]))
    fee_bps = float(cfg.get("fees_bps_default", DEFAULTS["fees_bps_default"]))
    slip_bps = float(cfg.get("slip_bps_default", DEFAULTS["slip_bps_default"]))
    noise_bps = float(cfg.get("batch_noise_bps", DEFAULTS["batch_noise_bps"]))
    cost = (fee_bps + slip_bps) / 10000.0

    EQUITY_OUT.parent.mkdir(parents=True, exist_ok=True)
    PF_OUT.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_OUT.parent.mkdir(parents=True, exist_ok=True)

    equity_rows: List[str] = []
    returns: List[float] = []
    equity = float(start_equity)
    last_ts: str | None = None

    for close in closes:
        ts = close.get("ts") or close.get("exit_ts") or None
        if isinstance(ts, str):
            last_ts = ts
        try:
            adj_pct = float(close.get("pct", close.get("pnl_pct", 0.0)))
        except Exception:
            adj_pct = 0.0
        adj_pct = max(-cap_pct, min(cap_pct, adj_pct))
        noise = _noise_from_trade(close, noise_bps)
        pct_net = adj_pct + noise - cost
        r_val = pct_net * risk_fraction
        returns.append(r_val)
        equity = max(0.0, equity * (1.0 + r_val))
        equity_rows.append(
            json.dumps(
                {
                    "ts": ts or "",
                    "equity": equity,
                    "adj_pct": adj_pct,
                    "pct_net": pct_net,
                    "r": r_val,
                    "fraction": risk_fraction,
                    "noise": noise,
                }
            )
        )

    equity_text = "\n".join(equity_rows) + ("\n" if equity_rows else "")
    try:
        EQUITY_OUT.write_text(equity_text)
    except Exception as exc:
        print(f"normalize_equity: failed to write equity curve ({exc})")

    pf_payload = {"pf": _pf_from_returns(returns), "count": len(returns), "source": "norm"}
    try:
        PF_OUT.write_text(json.dumps(pf_payload, indent=2))
    except Exception as exc:
        print(f"normalize_equity: failed to write pf_local_norm.json ({exc})")

    summary_payload = {
        "ts": last_ts,
        "start_equity_norm": start_equity,
        "risk_per_trade_bps": cfg.get("risk_per_trade_bps", DEFAULTS["risk_per_trade_bps"]),
        "count": len(returns),
        "last_equity": equity,
    }
    try:
        SUMMARY_OUT.write_text(json.dumps(summary_payload, indent=2))
    except Exception as exc:
        print(f"normalize_equity: failed to write equity_norm_summary.json ({exc})")

    print(
        "normalize_equity: closes={count} | last_equity={equity:.2f} | pf={pf}".format(
            count=len(returns),
            equity=equity,
            pf=("∞" if pf_payload["pf"] == float("inf") else f"{pf_payload['pf']:.4f}"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
