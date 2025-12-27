"""
Trade analysis utilities with cost-aware adjustments.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import yaml

from engine_alpha.core.paths import REPORTS, CONFIG
from engine_alpha.reflect.trade_sanity import filter_corrupted

REPORTS.mkdir(parents=True, exist_ok=True)


def pf_from_trades(trades: List[Dict]) -> float:
    wins = sum(float(t.get("pct", 0.0)) for t in trades if float(t.get("pct", 0.0)) > 0)
    losses = -sum(float(t.get("pct", 0.0)) for t in trades if float(t.get("pct", 0.0)) < 0)
    if losses <= 0:
        return float("inf") if wins > 0 else 0.0
    return wins / losses


def _read_trades(trades_path: Path) -> List[Dict]:
    out: List[Dict] = []
    if trades_path.exists():
        for line in trades_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    # Filter corrupted events (analytics-only)
    return filter_corrupted(out)


def _load_accounting() -> Dict[str, float]:
    defaults = {"start_equity": 10000.0, "taker_fee_bps": 6.0, "slip_bps": 2.0}
    cfg_path = CONFIG / "risk.yaml"
    if not cfg_path.exists():
        return defaults
    try:
        data = yaml.safe_load(cfg_path.read_text()) or {}
        accounting = data.get("accounting", {})
        return {
            "start_equity": float(accounting.get("start_equity", defaults["start_equity"])),
            "taker_fee_bps": float(accounting.get("taker_fee_bps", defaults["taker_fee_bps"])),
            "slip_bps": float(accounting.get("slip_bps", defaults["slip_bps"])),
        }
    except Exception:
        return defaults


def adjust_pct(trade: Dict[str, Any], accounting: Dict[str, float]) -> float:
    trade_type = str(trade.get("type") or trade.get("event", "")).lower()
    if trade_type != "close":
        return 0.0
    base = float(trade.get("pct", 0.0))
    cost = (accounting["taker_fee_bps"] * 2.0 + accounting["slip_bps"]) / 10000.0
    return base - cost


def equity_curve_from_trades(trades: List[Dict], start_equity: float, accounting: Dict[str, float]) -> List[Dict[str, float]]:
    equity = start_equity
    curve: List[Dict[str, float]] = []
    for trade in trades:
        adj_pct = adjust_pct(trade, accounting)
        if adj_pct == 0.0:
            continue
        equity *= (1.0 + adj_pct)
        curve.append({"ts": trade.get("ts"), "equity": equity, "adj_pct": adj_pct})
    return curve


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2))


def update_pf_reports(trades_path: Path, out_pf_local: Path, out_pf_live: Path, window: int = 150) -> None:
    """Update PF reports. Skips in DRY_RUN mode."""
    import os
    is_dry_run = os.getenv("MODE", "").upper() == "DRY_RUN" or os.getenv("CHLOE_DRY_RUN", "0") == "1"
    if is_dry_run:
        return  # Skip PF updates in dry-run mode
    
    trades = _read_trades(trades_path)
    accounting = _load_accounting()

    pf_live = pf_from_trades(trades) if trades else 0.0
    pf_local = pf_from_trades(trades[-window:]) if trades else 0.0

    # Preserve existing detailed PF data if present (e.g., from run_pf_local.py)
    existing_pf_local = {}
    if out_pf_local.exists():
        try:
            with out_pf_local.open("r") as f:
                existing_pf_local = json.load(f)
        except Exception:
            pass

    # Merge with simple format
    pf_local_data = {"pf": pf_local, "window": window, "count": min(len(trades), window)}
    pf_local_data.update(existing_pf_local)  # Existing detailed data takes precedence

    _write_json(out_pf_live, {"pf": pf_live, "count": len(trades)})
    _write_json(out_pf_local, pf_local_data)

    closed_trades = [t for t in trades if str(t.get("type") or t.get("event", "")).lower() == "close"]
    adj_entries: List[Dict[str, float]] = []
    for trade in closed_trades:
        adj = adjust_pct(trade, accounting)
        if adj != 0.0:
            adj_entries.append({"pct": adj})

    pf_live_adj = pf_from_trades(adj_entries) if adj_entries else 0.0
    pf_local_adj = pf_from_trades(adj_entries[-window:]) if adj_entries else 0.0

    _write_json(REPORTS / "pf_live_adj.json", {"pf": pf_live_adj, "count": len(adj_entries)})
    _write_json(
        REPORTS / "pf_local_adj.json",
        {"pf": pf_local_adj, "window": window, "count": min(len(adj_entries), window)},
    )

    curve = equity_curve_from_trades(closed_trades, accounting["start_equity"], accounting)
    curve_path = REPORTS / "equity_curve.jsonl"
    with curve_path.open("w") as f:
        for point in curve:
            f.write(json.dumps(point) + "\n")


def main():
    trades_path = REPORTS / "trades.jsonl"
    update_pf_reports(trades_path, REPORTS / "pf_local.json", REPORTS / "pf_live.json")


if __name__ == "__main__":
    main()
