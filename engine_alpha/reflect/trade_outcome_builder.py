"""
Trade outcome builder - Hybrid Self-Learning Mode

Scans trade logs and builds clean outcome records for research.
"""

import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from datetime import datetime

ROOT_DIR = Path(__file__).resolve().parents[2]
REPORTS_DIR = ROOT_DIR / "reports"
RESEARCH_DIR = REPORTS_DIR / "research"
RESEARCH_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_TRADE_LOGS = [
    REPORTS_DIR / "trades.jsonl",
    REPORTS_DIR / "trade_log.jsonl",
]

OUTCOME_PATH = RESEARCH_DIR / "trade_outcomes.jsonl"


def _parse_ts(ts) -> Optional[datetime]:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, (int, float)):
        # assume seconds
        return datetime.utcfromtimestamp(ts)
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return None
    return None


def _iter_trade_logs() -> Iterable[Dict]:
    for path in DEFAULT_TRADE_LOGS:
        if not path.exists():
            continue
        with path.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def _is_closed(trade: Dict) -> bool:
    """Check if trade is closed based on status or exit fields."""
    status = (trade.get("status") or trade.get("state") or "").lower()
    if status in ("closed", "completed", "exited"):
        return True
    # fall back on presence of exit_price / exit_ts
    if trade.get("exit_price") is not None and trade.get("exit_ts") is not None:
        return True
    # Also check for close event type
    if trade.get("type") == "close":
        return True
    return False


def _build_outcome(trade: Dict, default_timeframe: str = "1h") -> Optional[Dict]:
    """Build a clean outcome record from a trade dict."""
    if not _is_closed(trade):
        return None

    entry_ts = _parse_ts(trade.get("entry_ts") or trade.get("open_ts") or trade.get("ts"))
    exit_ts = _parse_ts(trade.get("exit_ts") or trade.get("close_ts"))

    if not entry_ts or not exit_ts:
        return None

    entry_price = float(trade.get("entry_px") or trade.get("entry_price") or trade.get("open_price") or trade.get("price", 0.0))
    exit_price = float(trade.get("exit_px") or trade.get("exit_price") or trade.get("close_price") or trade.get("price", 0.0))
    
    # Get direction from trade or compute from pct
    dir_val = trade.get("dir") or trade.get("direction")
    if dir_val is None:
        # Try to infer from pct sign
        pct = trade.get("pct", 0.0)
        dir_val = 1 if pct >= 0 else -1
    
    side = "long" if dir_val == 1 else "short"

    # Compute PnL if not present
    pnl_pct = trade.get("pct")
    if pnl_pct is None:
        if side == "long":
            pnl_pct = (exit_price - entry_price) / entry_price if entry_price > 0 else 0.0
        else:
            pnl_pct = (entry_price - exit_price) / entry_price if entry_price > 0 else 0.0

    symbol = trade.get("symbol", "ETHUSDT")
    timeframe = trade.get("timeframe", default_timeframe)

    # approximate holding bars if timeframe is like '1h', '4h' etc.
    holding_seconds = (exit_ts - entry_ts).total_seconds()
    bar_seconds = 3600.0
    if timeframe.endswith("h"):
        try:
            bar_seconds = float(timeframe[:-1]) * 3600.0
        except ValueError:
            pass
    elif timeframe.endswith("m"):
        try:
            bar_seconds = float(timeframe[:-1]) * 60.0
        except ValueError:
            pass

    holding_bars = holding_seconds / bar_seconds if bar_seconds > 0 else None

    outcome = {
        "trade_id": trade.get("id") or trade.get("trade_id"),
        "symbol": symbol,
        "timeframe": timeframe,
        "side": side,
        "entry_ts": entry_ts.isoformat(),
        "exit_ts": exit_ts.isoformat(),
        "entry_price": entry_price,
        "exit_price": exit_price,
        "pnl_pct": pnl_pct,
        "holding_bars": holding_bars,
        "size": float(trade.get("size") or trade.get("qty") or 0.0),
        "strategy": trade.get("strategy") or trade.get("strategy_name"),
        "regime_at_entry": trade.get("regime") or trade.get("regime_at_entry"),
        "confidence_at_entry": trade.get("entry_conf") or trade.get("conf") or trade.get("confidence_at_entry"),
        "exit_reason": trade.get("exit_reason"),
        "risk_band": trade.get("risk_band"),
    }
    return outcome


def build_trade_outcomes(output_path: Path = OUTCOME_PATH) -> Path:
    """
    Scan trade logs, build outcomes, and write them to a JSONL file.

    This can be run nightly as part of the research flow.
    """
    seen_ids = set()
    if output_path.exists():
        try:
            with output_path.open("r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        if rec.get("trade_id"):
                            seen_ids.add(rec["trade_id"])
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass

    new_count = 0
    with output_path.open("a") as out:
        for trade in _iter_trade_logs():
            trade_id = trade.get("id") or trade.get("trade_id")
            if trade_id and trade_id in seen_ids:
                continue

            outcome = _build_outcome(trade)
            if not outcome:
                continue

            if outcome.get("trade_id"):
                seen_ids.add(outcome["trade_id"])

            out.write(json.dumps(outcome) + "\n")
            new_count += 1

    return output_path


if __name__ == "__main__":
    path = build_trade_outcomes()
    print(f"✅ Wrote trade outcomes to {path}")


