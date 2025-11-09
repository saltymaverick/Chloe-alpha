#!/usr/bin/env python3
"""
Run backtest replay - Phase 27 (paper only, multi-run support).
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import yaml

from engine_alpha.core.paths import CONFIG, REPORTS
from engine_alpha.data.historical_loader import load_ohlcv
from engine_alpha.loop.replay import replay
from engine_alpha.reflect import trade_analysis


def _load_backtest_config() -> Dict[str, Any]:
    cfg_path = CONFIG / "backtest.yaml"
    if not cfg_path.exists():
        return {}
    try:
        with cfg_path.open("r") as f:
            data = yaml.safe_load(f) or {}
        return data
    except Exception:
        return {}


def _default_symbol(cfg: Dict[str, Any]) -> str:
    symbols = cfg.get("symbols")
    if isinstance(symbols, list) and symbols:
        return str(symbols[0])
    return "ETHUSDT"


def _sanitize_segment(value: str | None) -> str:
    if not value:
        return "NA"
    cleaned = (
        str(value)
        .replace(":", "")
        .replace("-", "")
        .replace("T", "")
        .replace("Z", "")
        .strip()
    )
    return cleaned or "NA"


def _write_trades(trades_path: Path, trades: List[Dict[str, Any]]) -> None:
    trades_path.parent.mkdir(parents=True, exist_ok=True)
    with trades_path.open("w") as f:
        for trade in trades:
            f.write(json.dumps(trade) + "\n")


def _write_equity_curve(equity_path: Path, trades: List[Dict[str, Any]], start_equity: float) -> None:
    equity = float(start_equity)
    entries: List[Dict[str, Any]] = []
    for trade in trades:
        trade_type = str(trade.get("type") or trade.get("event", "")).lower()
        if trade_type != "close":
            continue
        adj_pct = trade.get("adj_pct")
        if adj_pct is None:
            continue
        try:
            adj_pct_val = float(adj_pct)
        except (TypeError, ValueError):
            continue
        equity *= 1.0 + adj_pct_val
        entries.append({"ts": trade.get("ts"), "equity": equity, "adj_pct": adj_pct_val})
    equity_path.parent.mkdir(parents=True, exist_ok=True)
    with equity_path.open("w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _build_arg_parser(cfg: Dict[str, Any]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a paper backtest replay.")
    parser.add_argument("--symbol", default=_default_symbol(cfg))
    parser.add_argument("--timeframe", default=str(cfg.get("timeframe", "1h")))
    parser.add_argument("--start", default=str(cfg.get("start", "")))
    parser.add_argument("--end", default=str(cfg.get("end", "")))
    parser.add_argument("--limit", type=int, default=int(cfg.get("limit", 0)))
    parser.add_argument("--tag", default="", help="Optional label for this run.")
    parser.add_argument(
        "--start_equity",
        type=float,
        default=float(cfg.get("start_equity", 10000.0)),
        help="Starting equity for equity curve computation.",
    )
    return parser


def main(argv: List[str] | None = None) -> None:
    cfg = _load_backtest_config()
    parser = _build_arg_parser(cfg)
    args = parser.parse_args(argv)

    symbol = str(args.symbol)
    timeframe = str(args.timeframe)
    start = str(args.start) if args.start else cfg.get("start")
    end = str(args.end) if args.end else cfg.get("end")
    limit = int(args.limit) if args.limit else 0
    tag = str(args.tag or "")
    start_equity = float(args.start_equity)
    seed = int(cfg.get("seed", 42))

    if not start or not end:
        raise ValueError("Both --start and --end must be provided (or set in config/backtest.yaml).")

    bt_root = REPORTS / "backtest"
    run_prefix = f"{symbol}_{timeframe}_{_sanitize_segment(start)}_{_sanitize_segment(end)}"
    timestamp_label = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    run_dir = bt_root / run_prefix / timestamp_label
    run_dir.mkdir(parents=True, exist_ok=True)

    rows = load_ohlcv(symbol, timeframe, start, end, cfg)
    if limit and limit > 0:
        rows = rows[:limit]

    result = replay(symbol, timeframe, rows, cfg=cfg, seed=seed)
    trades = result["trades"]
    bars = result.get("bars", len(rows))

    trades_path = run_dir / "trades.jsonl"
    _write_trades(trades_path, trades)

    original_reports = trade_analysis.REPORTS
    try:
        trade_analysis.REPORTS = run_dir
        trade_analysis.update_pf_reports(
            trades_path,
            run_dir / "pf_local.json",
            run_dir / "pf_live.json",
        )
    finally:
        trade_analysis.REPORTS = original_reports

    _write_equity_curve(run_dir / "equity_curve.jsonl", trades, start_equity)

    pf_live = _load_json(run_dir / "pf_live.json")
    pf_live_adj = _load_json(run_dir / "pf_live_adj.json")

    closed_trades = [
        t for t in trades if str(t.get("type") or t.get("event", "")).lower() == "close"
    ]
    summary = {
        "symbol": symbol,
        "timeframe": timeframe,
        "start": start,
        "end": end,
        "bars": bars,
        "trades": len(closed_trades),
        "pf": pf_live.get("pf"),
        "pf_adj": pf_live_adj.get("pf"),
        "tag": tag,
        "limit": limit,
        "start_equity": start_equity,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    index_path = bt_root / "index.json"
    try:
        existing = json.loads(index_path.read_text()) if index_path.exists() else []
        if not isinstance(existing, list):
            existing = []
    except Exception:
        existing = []

    run_record = {
        "symbol": symbol,
        "timeframe": timeframe,
        "start": start,
        "end": end,
        "ts": datetime.now(timezone.utc).isoformat(),
        "dir": str(run_dir.relative_to(bt_root)),
        "pf": summary.get("pf"),
        "pf_adj": summary.get("pf_adj"),
        "trades": summary.get("trades"),
        "tag": tag,
    }
    updated = existing + [run_record]
    updated.sort(key=lambda item: item.get("ts", ""), reverse=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(updated, indent=2))

    print(
        "BT run complete: symbol={symbol} timeframe={timeframe} bars={bars} trades={trades} "
        "PF={pf} PF_adj={pf_adj} dir={dir}".format(
            symbol=symbol,
            timeframe=timeframe,
            bars=bars,
            trades=summary["trades"],
            pf=summary.get("pf"),
            pf_adj=summary.get("pf_adj"),
            dir=run_record["dir"],
        )
    )


if __name__ == "__main__":
    main()
