#!/usr/bin/env python3
"""Normalize equity curve using fixed risk per trade."""

from __future__ import annotations

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

DEFAULTS = {
    "start_equity_norm": 10000.0,
    "risk_per_trade_bps": 100,
    "cap_adj_pct": 0.05,
    "use_abs": False,
}


def _load_config() -> Dict[str, Any]:
    if CONFIG_PATH.exists():
        try:
            data = yaml.safe_load(CONFIG_PATH.read_text()) or {}
            cfg = DEFAULTS.copy()
            cfg.update({k: data.get(k, cfg[k]) for k in DEFAULTS})
            cfg["use_abs"] = bool(cfg.get("use_abs"))
            return cfg
        except Exception:
            pass
    return DEFAULTS.copy()


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


def main() -> int:
    cfg = _load_config()
    closes = _iter_closes(TRADES_PATH)

    equity = float(cfg["start_equity_norm"])
    risk_factor = float(cfg["risk_per_trade_bps"]) / 10000.0
    cap_pct = float(cfg["cap_adj_pct"])
    use_abs = bool(cfg["use_abs"])

    EQUITY_OUT.parent.mkdir(parents=True, exist_ok=True)
    PF_OUT.parent.mkdir(parents=True, exist_ok=True)

    equity_rows: List[str] = []
    pos_sum = 0.0
    neg_sum = 0.0

    if not closes:
        EQUITY_OUT.write_text("")
        PF_OUT.write_text(json.dumps({"pf": 0.0, "window": 0, "count": 0}, indent=2))
        SUMMARY_OUT.write_text(
            json.dumps(
                {
                    "ts": None,
                    "start_equity_norm": equity,
                    "risk_per_trade_bps": cfg["risk_per_trade_bps"],
                    "count": 0,
                    "last_equity": equity,
                },
                indent=2,
            )
        )
        print("normalize_equity: no close events found; outputs reset.")
        return 0

    last_ts = None
    for close in closes:
        last_ts = close.get("ts")
        adj_raw = close.get("pct")
        try:
            adj = float(adj_raw)
        except Exception:
            adj = 0.0
        adj = max(-cap_pct, min(cap_pct, adj))
        if use_abs and close.get("dir") in (1, -1):
            sign = 1.0 if adj >= 0 else -1.0
            adj = abs(adj) * sign
        if adj > 0:
            pos_sum += adj
        elif adj < 0:
            neg_sum += abs(adj)
        equity *= (1.0 + adj * risk_factor)
        equity_rows.append(
            json.dumps(
                {
                    "ts": close.get("ts"),
                    "equity": equity,
                    "adj_pct": adj,
                    "rf": risk_factor,
                }
            )
        )

    EQUITY_OUT.write_text("\n".join(equity_rows) + "\n")

    pf = pos_sum / neg_sum if neg_sum > 0 else (pos_sum if pos_sum > 0 else 0.0)
    PF_OUT.write_text(
        json.dumps({"pf": pf, "window": len(closes), "count": len(closes)}, indent=2)
    )

    SUMMARY_OUT.write_text(
        json.dumps(
            {
                "ts": last_ts,
                "start_equity_norm": cfg["start_equity_norm"],
                "risk_per_trade_bps": cfg["risk_per_trade_bps"],
                "count": len(closes),
                "last_equity": equity,
            },
            indent=2,
        )
    )

    print(
        "normalize_equity: processed {count} closes -> last_equity={equity:.2f}".format(
            count=len(closes), equity=equity
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
