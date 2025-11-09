#!/usr/bin/env python3
"""
Run backtest replay - Phase 23 (paper only).
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from engine_alpha.core.paths import REPORTS, CONFIG
from engine_alpha.data.historical_loader import load_ohlcv
from engine_alpha.loop.replay import replay
from engine_alpha.reflect import trade_analysis


def _write_trades(trades_path: Path, trades):
    trades_path.parent.mkdir(parents=True, exist_ok=True)
    with trades_path.open("a") as f:
        for trade in trades:
            f.write(json.dumps(trade) + "\n")


def _write_equity_curve(equity_path: Path, trades, start_equity: float) -> None:
    equity_path.parent.mkdir(parents=True, exist_ok=True)
    equity = float(start_equity)
    entries = []
    for trade in trades:
        trade_type = str(trade.get("type") or trade.get("event", "")).lower()
        if trade_type != "close":
            continue
        adj_pct = trade.get("adj_pct")
        if adj_pct is None:
            continue
        try:
            adj_pct = float(adj_pct)
        except (TypeError, ValueError):
            continue
        equity *= 1.0 + adj_pct
        entries.append({"ts": trade.get("ts"), "equity": equity, "adj_pct": adj_pct})
    with equity_path.open("w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def main():
    with (CONFIG / "backtest.yaml").open() as f:
        cfg = yaml.safe_load(f)
    symbols = cfg.get("symbols", ["ETHUSDT"])
    timeframe = cfg.get("timeframe", "1h")
    start = cfg.get("start")
    end = cfg.get("end")
    seed = cfg.get("seed", 42)
    start_equity = float(cfg.get("start_equity", 10000.0))

    bt_dir = REPORTS / "backtest"
    trades_path = bt_dir / "trades.jsonl"
    equity_path = bt_dir / "equity_curve.jsonl"

    total_trades = []
    bars = 0
    for symbol in symbols:
        rows = load_ohlcv(symbol, timeframe, start, end, cfg)
        result = replay(symbol, timeframe, rows, seed=seed)
        total_trades.extend(result["trades"])
        bars += result["bars"]

    _write_trades(trades_path, total_trades)

    old_reports = trade_analysis.REPORTS
    try:
        trade_analysis.REPORTS = bt_dir
        trade_analysis.REPORTS.mkdir(parents=True, exist_ok=True)
        trade_analysis.update_pf_reports(
            trades_path,
            bt_dir / "pf_local.json",
            bt_dir / "pf_live.json",
        )
    finally:
        trade_analysis.REPORTS = old_reports

    _write_equity_curve(equity_path, total_trades, start_equity)

    pf_live = json.loads((bt_dir / "pf_live.json").read_text()) if (bt_dir / "pf_live.json").exists() else {}
    pf_live_adj = json.loads((bt_dir / "pf_live_adj.json").read_text()) if (bt_dir / "pf_live_adj.json").exists() else {}

    summary = {
        "symbol": symbols[0],
        "timeframe": timeframe,
        "bars": bars,
        "trades": sum(
            1
            for t in total_trades
            if str(t.get("type") or t.get("event", "")).lower() == "close"
        ),
        "pf": pf_live.get("pf"),
        "pf_adj": pf_live_adj.get("pf"),
    }
    (bt_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(
        "BT: symbol={symbol} tf={tf} bars={bars} trades={trades} PF={pf} PF_adj={pf_adj}".format(
            symbol=summary["symbol"],
            tf=timeframe,
            bars=summary["bars"],
            trades=summary["trades"],
            pf=summary["pf"],
            pf_adj=summary["pf_adj"],
        )
    )


if __name__ == "__main__":
    main()
