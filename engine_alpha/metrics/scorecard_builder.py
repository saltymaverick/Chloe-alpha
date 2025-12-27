"""
Performance scorecard builders for assets and strategies.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

ROOT_DIR = Path(__file__).resolve().parents[2]
REPORTS_DIR = ROOT_DIR / "reports"
SCORECARD_DIR = REPORTS_DIR / "scorecards"
SCORECARD_DIR.mkdir(parents=True, exist_ok=True)


def _read_trades(trades_path: Path) -> Iterable[dict]:
    if not trades_path.exists():
        return []

    trades: List[dict] = []
    with trades_path.open("r") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                trades.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return trades


def _compute_max_drawdown(pcts: List[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pct in pcts:
        equity += pct
        peak = max(peak, equity)
        drawdown = peak - equity
        if drawdown > max_dd:
            max_dd = drawdown
    return max_dd


def _safe_mean(total: float, count: int) -> float | None:
    if count <= 0:
        return None
    return total / count


def _pf(gross_win: float, gross_loss: float) -> float | None:
    if gross_loss < 0:
        return gross_win / abs(gross_loss)
    if gross_win > 0:
        return None  # Infinite PF; represented as None and formatted later
    return 0.0


def build_asset_scorecards(
    trades_path: Path = REPORTS_DIR / "trades.jsonl",
    pf_path: Path = REPORTS_DIR / "pf_local.json",
    output_path: Path = SCORECARD_DIR / "asset_scorecards.json",
) -> Path:
    """
    Build per-asset scorecards from historical trades.
    """
    trades = _read_trades(trades_path)
    if not trades:
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "assets": [],
        }
        output_path.write_text(json.dumps(payload, indent=2))
        return output_path

    per_symbol: Dict[str, Dict[str, any]] = defaultdict(lambda: {
        "pcts": [],
        "wins": 0,
        "losses": 0,
        "scratches": 0,
        "wins_total": 0.0,
        "losses_total": 0.0,
        "regimes": Counter(),
        "strategies": Counter(),
        "trade_records": [],
    })

    for trade in trades:
        if trade.get("type") != "close":
            continue
        symbol = trade.get("symbol", "ETHUSDT").upper()
        pct = float(trade.get("pct", 0.0) or 0.0)
        is_scratch = bool(trade.get("is_scratch", False))
        regime = trade.get("regime", "unknown")
        strategy = trade.get("strategy") or trade.get("strategy_name") or "unknown"

        sym_bucket = per_symbol[symbol]
        if is_scratch:
            sym_bucket["scratches"] += 1
            continue

        sym_bucket["pcts"].append(pct)
        sym_bucket["trade_records"].append(pct)
        if pct > 0:
            sym_bucket["wins"] += 1
            sym_bucket["wins_total"] += pct
        elif pct < 0:
            sym_bucket["losses"] += 1
            sym_bucket["losses_total"] += pct
        sym_bucket["regimes"][regime] += 1
        sym_bucket["strategies"][strategy] += 1

    asset_rows: List[dict] = []
    for symbol, bucket in per_symbol.items():
        total_trades = bucket["wins"] + bucket["losses"]
        gross_win = bucket["wins_total"]
        gross_loss = bucket["losses_total"]
        row = {
            "symbol": symbol,
            "total_trades": total_trades,
            "wins": bucket["wins"],
            "losses": bucket["losses"],
            "scratches": bucket["scratches"],
            "pf": _pf(gross_win, gross_loss),
            "avg_win": _safe_mean(gross_win, bucket["wins"]),
            "avg_loss": _safe_mean(gross_loss, bucket["losses"]),
            "max_drawdown": _compute_max_drawdown(bucket["pcts"]),
            "most_used_regime": bucket["regimes"].most_common(1)[0][0] if bucket["regimes"] else None,
            "most_used_strategy": bucket["strategies"].most_common(1)[0][0] if bucket["strategies"] else None,
        }
        asset_rows.append(row)

    asset_rows.sort(key=lambda r: (-r["total_trades"], r["symbol"]))
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "assets": asset_rows,
    }
    output_path.write_text(json.dumps(payload, indent=2))
    return output_path


def build_strategy_scorecards(
    trades_path: Path = REPORTS_DIR / "trades.jsonl",
    output_path: Path = SCORECARD_DIR / "strategy_scorecards.json",
) -> Path:
    """
    Build per-strategy scorecards (per symbol and aggregated).
    """
    trades = _read_trades(trades_path)
    if not trades:
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "per_symbol": [],
            "overall": [],
        }
        output_path.write_text(json.dumps(payload, indent=2))
        return output_path

    per_pair: Dict[Tuple[str, str], Dict[str, any]] = defaultdict(lambda: {
        "pcts": [],
        "wins": 0,
        "losses": 0,
        "scratches": 0,
        "wins_total": 0.0,
        "losses_total": 0.0,
    })
    per_strategy: Dict[str, Dict[str, any]] = defaultdict(lambda: {
        "pcts": [],
        "wins": 0,
        "losses": 0,
        "scratches": 0,
        "wins_total": 0.0,
        "losses_total": 0.0,
    })

    for trade in trades:
        if trade.get("type") != "close":
            continue
        symbol = trade.get("symbol", "ETHUSDT").upper()
        strategy = trade.get("strategy") or trade.get("strategy_name") or "unknown"
        pct = float(trade.get("pct", 0.0) or 0.0)
        is_scratch = bool(trade.get("is_scratch", False))

        if is_scratch:
            per_pair[(strategy, symbol)]["scratches"] += 1
            per_strategy[strategy]["scratches"] += 1
            continue

        pair_bucket = per_pair[(strategy, symbol)]
        strat_bucket = per_strategy[strategy]

        pair_bucket["pcts"].append(pct)
        strat_bucket["pcts"].append(pct)

        if pct > 0:
            pair_bucket["wins"] += 1
            pair_bucket["wins_total"] += pct
            strat_bucket["wins"] += 1
            strat_bucket["wins_total"] += pct
        elif pct < 0:
            pair_bucket["losses"] += 1
            pair_bucket["losses_total"] += pct
            strat_bucket["losses"] += 1
            strat_bucket["losses_total"] += pct

    per_symbol_rows = []
    for (strategy, symbol), bucket in per_pair.items():
        total_trades = bucket["wins"] + bucket["losses"]
        row = {
            "strategy": strategy,
            "symbol": symbol,
            "total_trades": total_trades,
            "wins": bucket["wins"],
            "losses": bucket["losses"],
            "scratches": bucket["scratches"],
            "pf": _pf(bucket["wins_total"], bucket["losses_total"]),
            "avg_win": _safe_mean(bucket["wins_total"], bucket["wins"]),
            "avg_loss": _safe_mean(bucket["losses_total"], bucket["losses"]),
            "max_drawdown": _compute_max_drawdown(bucket["pcts"]),
        }
        per_symbol_rows.append(row)

    overall_rows = []
    for strategy, bucket in per_strategy.items():
        total_trades = bucket["wins"] + bucket["losses"]
        row = {
            "strategy": strategy,
            "total_trades": total_trades,
            "wins": bucket["wins"],
            "losses": bucket["losses"],
            "scratches": bucket["scratches"],
            "pf": _pf(bucket["wins_total"], bucket["losses_total"]),
            "avg_win": _safe_mean(bucket["wins_total"], bucket["wins"]),
            "avg_loss": _safe_mean(bucket["losses_total"], bucket["losses"]),
            "max_drawdown": _compute_max_drawdown(bucket["pcts"]),
        }
        overall_rows.append(row)

    per_symbol_rows.sort(key=lambda r: (-r["total_trades"], r["strategy"], r["symbol"]))
    overall_rows.sort(key=lambda r: (-r["total_trades"], r["strategy"]))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "per_symbol": per_symbol_rows,
        "overall": overall_rows,
    }
    output_path.write_text(json.dumps(payload, indent=2))
    return output_path

