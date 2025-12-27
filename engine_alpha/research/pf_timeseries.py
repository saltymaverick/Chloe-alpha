"""
PF Time-Series Engine
---------------------

Pro-quant PF time-series calculator for Chloe.

Responsibilities:
  * Read trade history from reports/trades.jsonl
  * Compute rolling PF statistics over multiple windows:
        - 1D, 7D, 14D, 30D, 90D
    plus:
        - month-to-date (MTD)
  * Compute:
        - per-symbol PF per window
        - global PF per window (trade-weighted)
  * Persist results to:
        reports/pf/pf_timeseries.json

All outputs are ADVISORY-ONLY and PAPER-SAFE.
No configs, executions, or capital are modified.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from engine_alpha.core.paths import REPORTS
from engine_alpha.reflect.trade_sanity import filter_corrupted

TRADES_PATH = REPORTS / "trades.jsonl"
OUT_PATH = REPORTS / "pf" / "pf_timeseries.json"

WINDOW_DAYS = [1, 7, 14, 30, 90]


@dataclass
class PFStats:
    pf: Optional[float]
    wins: int
    losses: int
    avg_win: Optional[float]
    avg_loss: Optional[float]
    trades: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pf": self.pf,
            "wins": self.wins,
            "losses": self.losses,
            "avg_win": self.avg_win,
            "avg_loss": self.avg_loss,
            "trades": self.trades,
        }


def _safe_parse_ts(ts: Any) -> Optional[datetime]:
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except Exception:
            return None
    if isinstance(ts, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                return datetime.strptime(ts, fmt).astimezone(timezone.utc)
            except Exception:
                continue
        try:
            # Last resort: fromisoformat for slightly off formats
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            return None
    return None


def _extract_return(trade: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """
    Extract (return_pct, weight) from a trade record.

    Priority:
      1) 'pnl_pct' and 'notional' / 'size'
      2) 'realized_pct'
      3) 'pnl' and 'notional'
      4) Fallback: None (skip)

    return_pct is expressed as decimal (0.01 = +1%).
    weight is used to trade-weight the global PF (notional if present, else 1.0).
    """
    pnl_pct = trade.get("pnl_pct")
    if pnl_pct is not None:
        try:
            r = float(pnl_pct)
        except Exception:
            r = None
        else:
            weight = float(trade.get("notional") or trade.get("size") or 1.0)
            return r, weight

    realized_pct = trade.get("realized_pct")
    if realized_pct is not None:
        try:
            r = float(realized_pct)
        except Exception:
            r = None
        else:
            weight = float(trade.get("notional") or trade.get("size") or 1.0)
            return r, weight

    pnl = trade.get("pnl")
    notional = trade.get("notional") or trade.get("size")
    if pnl is not None and notional is not None:
        try:
            pnl_f = float(pnl)
            notional_f = float(notional)
            if notional_f != 0.0:
                r = pnl_f / notional_f
            else:
                r = None
        except Exception:
            r = None
        else:
            if r is not None:
                return r, float(notional_f)

    # Fallback: try 'pct' field (used in trades.jsonl closes)
    # Note: pct is already a decimal (0.01 = 1%), not a percentage
    pct = trade.get("pct")
    if pct is not None:
        try:
            r = float(pct)  # Already in decimal form
        except Exception:
            r = None
        else:
            weight = float(trade.get("notional") or trade.get("size") or 1.0)
            return r, weight

    return None


def _load_trades() -> List[Dict[str, Any]]:
    if not TRADES_PATH.exists():
        return []
    trades: List[Dict[str, Any]] = []
    with TRADES_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            # Only process "close" events for PF calculation
            event_type = rec.get("type", "").lower()
            if event_type != "close":
                continue
            ts = _safe_parse_ts(rec.get("ts") or rec.get("timestamp"))
            if ts is None:
                continue
            rec["_ts_dt"] = ts
            trades.append(rec)
    # Filter corrupted events (analytics-only)
    trades = filter_corrupted(trades)
    trades.sort(key=lambda x: x["_ts_dt"])
    return trades


def _compute_pf_for_window(
    returns: List[Tuple[float, float]]
) -> PFStats:
    """
    Compute PF stats given a list of (return_pct, weight).
    """
    if not returns:
        return PFStats(pf=None, wins=0, losses=0, avg_win=None, avg_loss=None, trades=0)

    wins = [(r, w) for r, w in returns if r > 0.0]
    losses = [(r, w) for r, w in returns if r < 0.0]

    trades = len(returns)

    if wins:
        win_num = sum(r * w for r, w in wins)
        win_den = sum(abs(w) for _, w in wins) or 1.0
        avg_win = win_num / win_den
    else:
        avg_win = None

    if losses:
        loss_num = sum(abs(r) * w for r, w in losses)
        loss_den = sum(abs(w) for _, w in losses) or 1.0
        avg_loss = loss_num / loss_den
    else:
        avg_loss = None

    if losses and avg_loss not in (None, 0.0) and avg_win is not None:
        pf = float(avg_win / avg_loss)
    elif losses and avg_loss in (None, 0.0):
        pf = None
    elif wins and not losses:
        pf = None  # effectively "infinite PF" but we keep it None to stay conservative
    else:
        pf = None

    return PFStats(
        pf=pf,
        wins=len(wins),
        losses=len(losses),
        avg_win=avg_win,
        avg_loss=avg_loss,
        trades=trades,
    )


def _group_trades_by_symbol(trades: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    by_sym: Dict[str, List[Dict[str, Any]]] = {}

    for t in trades:
        sym = t.get("symbol") or t.get("pair") or "UNKNOWN"
        by_sym.setdefault(str(sym), []).append(t)
    return by_sym


def compute_pf_timeseries(now: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Core engine: compute PF time-series for all symbols + global.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    trades = _load_trades()
    by_sym = _group_trades_by_symbol(trades)

    def in_window(ts: datetime, days: int) -> bool:
        delta = now - ts
        return delta.total_seconds() <= days * 86400.0

    # MTD helper
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    symbol_stats: Dict[str, Dict[str, Any]] = {}

    # Per-symbol stats
    for symbol, sym_trades in by_sym.items():
        sym_returns: Dict[str, List[Tuple[float, float]]] = {f"{d}d": [] for d in WINDOW_DAYS}
        sym_returns["mtd"] = []

        for t in sym_trades:
            ts = t["_ts_dt"]
            rets = _extract_return(t)
            if rets is None:
                continue
            r, w = rets

            # assign to windows
            for d in WINDOW_DAYS:
                if in_window(ts, d):
                    sym_returns[f"{d}d"].append((r, w))
            if ts >= start_of_month:
                sym_returns["mtd"].append((r, w))

        symbol_stats[symbol] = {}
        for key, values in sym_returns.items():
            symbol_stats[symbol][key] = _compute_pf_for_window(values).to_dict()

    # Global stats (trade-weighted)
    global_stats: Dict[str, Any] = {}
    global_returns: Dict[str, List[Tuple[float, float]]] = {f"{d}d": [] for d in WINDOW_DAYS}
    global_returns["mtd"] = []

    for t in trades:
        ts = t["_ts_dt"]
        rets = _extract_return(t)
        if rets is None:
            continue
        r, w = rets

        for d in WINDOW_DAYS:
            if in_window(ts, d):
                global_returns[f"{d}d"].append((r, w))
        if ts >= start_of_month:
            global_returns["mtd"].append((r, w))

    for key, values in global_returns.items():
        global_stats[key] = _compute_pf_for_window(values).to_dict()

    payload = {
        "meta": {
            "engine": "pf_timeseries_v1",
            "version": "1.0.0",
            "generated_at": now.isoformat(),
            "windows_days": WINDOW_DAYS,
            "advisory_only": True,
        },
        "global": global_stats,
        "symbols": symbol_stats,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)

    return payload


__all__ = ["compute_pf_timeseries", "OUT_PATH", "TRADES_PATH"]

