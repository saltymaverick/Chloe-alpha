from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine_alpha.core.gpt_client import query_gpt


TRADES_PATH = Path("reports/trades.jsonl")
SIGNAL_HISTORY_PATH = Path("reports/debug/signals_history.jsonl")
HINDSIGHT_LOG = Path("reports/research/hindsight_reviews.jsonl")


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _load_signal_history(max_lines: int = 5000) -> Dict[str, List[Dict[str, Any]]]:
    history: Dict[str, List[Dict[str, Any]]] = {}
    if not SIGNAL_HISTORY_PATH.exists():
        return history
    try:
        with SIGNAL_HISTORY_PATH.open("r") as handle:
            lines = handle.readlines()
    except Exception:
        return history
    for line in lines[-max_lines:]:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        sym = record.get("symbol")
        if not sym:
            continue
        record["_ts_obj"] = _parse_iso(record.get("ts"))
        history.setdefault(sym.upper(), []).append(record)
    for sym_records in history.values():
        sym_records.sort(key=lambda r: r.get("_ts_obj") or datetime.min)
    return history


def _clean_history_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in entry.items() if k != "_ts_obj"}


def get_signals_around(
    ts: Optional[str],
    symbol: str,
    history: Dict[str, List[Dict[str, Any]]],
    window: int = 4,
) -> Dict[str, Any]:
    entries = history.get(symbol.upper(), [])
    if not entries:
        return {}
    target = _parse_iso(ts)
    if target is None:
        sample = [_clean_history_entry(e) for e in entries[-window:]]
        return {"samples": sample}

    before = [e for e in entries if e.get("_ts_obj") and e["_ts_obj"] <= target]
    after = [e for e in entries if e.get("_ts_obj") and e["_ts_obj"] > target]
    return {
        "before": [_clean_history_entry(e) for e in before[-window:]],
        "after": [_clean_history_entry(e) for e in after[:window]],
    }


def load_closed_trades(path: Path = TRADES_PATH, max_trades: int = 20) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text().splitlines()
    except Exception:
        return []
    closed: List[Dict[str, Any]] = []
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        if rec.get("type") == "close" or rec.get("event") == "close":
            closed.append(rec)
        if len(closed) >= max_trades:
            break
    return list(reversed(closed))


def build_hindsight_context(
    max_trades: int = 20,
) -> List[Dict[str, Any]]:
    closed_trades = load_closed_trades(max_trades=max_trades)
    history = _load_signal_history()
    context: List[Dict[str, Any]] = []
    for trade in closed_trades:
        symbol = trade.get("symbol")
        if not symbol:
            continue
        entry_ts = trade.get("entry_ts") or trade.get("entry_time") or trade.get("open_ts")
        exit_ts = trade.get("ts") or trade.get("close_ts")
        entry_signals = get_signals_around(entry_ts, symbol, history)
        exit_signals = get_signals_around(exit_ts, symbol, history)
        context.append(
            {
                "symbol": symbol.upper(),
                "entry_ts": entry_ts,
                "exit_ts": exit_ts,
                "dir": trade.get("dir"),
                "pnl_pct": trade.get("pct"),
                "regime_entry": trade.get("regime"),
                "regime_exit": trade.get("exit_regime"),
                "entry_signals": entry_signals,
                "exit_signals": exit_signals,
            }
        )
    return context


def _fallback_review(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    reviews: List[Dict[str, Any]] = []
    for trade in trades:
        pnl = trade.get("pnl_pct")
        grade = "win" if isinstance(pnl, (int, float)) and pnl >= 0 else "loss"
        reviews.append(
            {
                "symbol": trade.get("symbol"),
                "entry_ts": trade.get("entry_ts"),
                "exit_ts": trade.get("exit_ts"),
                "dir": trade.get("dir"),
                "pnl_pct": pnl,
                "hindsight": {
                    "entry_eval": {
                        "grade": grade,
                        "comment": "GPT unavailable; basic outcome recorded.",
                    },
                    "exit_eval": {
                        "grade": grade,
                        "comment": "No GPT review; please inspect manually.",
                    },
                    "policy_suggestions": [],
                },
            }
        )
    return reviews


def _call_gpt_for_hindsight(context: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    if not context:
        return None
    prompt = {
        "role": "hindsight_coach",
        "task": (
            "You are Chloe's trading coach. For each closed trade below, provide a JSON object with:\n"
            "entry_eval (grade/comment), exit_eval (grade/comment), positioning_eval (grade/comment), "
            "and policy_suggestions (list of strings). Be specific but do not invent data not shown.\n"
            "Return strict JSON matching the schema."
        ),
        "context": {"trades": context},
    }
    try:
        from engine_alpha.core.chloe_core import think

        response = think(prompt)
        if isinstance(response, list):
            return response
        if isinstance(response, dict):
            return response.get("reviews")
    except Exception:
        pass

    try:
        task = prompt["task"]
        ctx_blob = json.dumps(prompt["context"], indent=2)
        full_prompt = f"{task}\n\nContext:\n{ctx_blob}"
        response = query_gpt(full_prompt, "hindsight_coach")
        if not response:
            return None
        text = response.get("text") or ""
        return json.loads(text)
    except Exception:
        return None


def _append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(record) + "\n")


def run_hindsight_coach(max_trades: int = 20) -> List[Dict[str, Any]]:
    trades_context = build_hindsight_context(max_trades=max_trades)
    if not trades_context:
        return []
    reviews = _call_gpt_for_hindsight(trades_context)
    if not isinstance(reviews, list):
        reviews = _fallback_review(trades_context)

    normalized_reviews: List[Dict[str, Any]] = []
    for trade, review in zip(trades_context, reviews):
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "symbol": trade.get("symbol"),
            "entry_ts": trade.get("entry_ts"),
            "exit_ts": trade.get("exit_ts"),
            "dir": trade.get("dir"),
            "pnl_pct": trade.get("pnl_pct"),
            "review": review,
        }
        normalized_reviews.append(record)
        _append_jsonl(HINDSIGHT_LOG, record)

    return normalized_reviews


__all__ = ["run_hindsight_coach", "build_hindsight_context"]

