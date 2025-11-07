"""
Sandbox manager - Phase 18 (paper only)
Coordinates sandbox simulations derived from promotion proposals.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import yaml

from engine_alpha.core.paths import REPORTS, CONFIG
from engine_alpha.signals.signal_processor import get_signal_vector
from engine_alpha.core.confidence_engine import decide
from engine_alpha.core.regime import RegimeClassifier

SANDBOX_DIR = REPORTS / "sandbox"
QUEUE_PATH = SANDBOX_DIR / "sandbox_queue.jsonl"
RUNS_PATH = SANDBOX_DIR / "sandbox_runs.jsonl"
STATUS_PATH = SANDBOX_DIR / "sandbox_status.json"
PROMOTION_PATH = REPORTS / "promotion_proposals.jsonl"

DEFAULT_ACCOUNTING = {"taker_fee_bps": 6.0, "slip_bps": 2.0}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_accounting() -> Dict[str, float]:
    path = CONFIG / "risk.yaml"
    if not path.exists():
        return DEFAULT_ACCOUNTING.copy()
    try:
        data = yaml.safe_load(path.read_text()) or {}
        accounting = data.get("accounting", {})
        return {
            "taker_fee_bps": float(accounting.get("taker_fee_bps", DEFAULT_ACCOUNTING["taker_fee_bps"])),
            "slip_bps": float(accounting.get("slip_bps", DEFAULT_ACCOUNTING["slip_bps"])),
        }
    except Exception:
        return DEFAULT_ACCOUNTING.copy()


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def _append_jsonl(path: Path, entry: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def _load_status() -> Dict[str, str]:
    if not STATUS_PATH.exists():
        return {}
    try:
        return json.loads(STATUS_PATH.read_text())
    except Exception:
        return {}


def _write_status(status: Dict[str, str]) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, indent=2))


def _short_name(name: str) -> str:
    return name.replace(" ", "-")[:12]


def enqueue_from_proposals(max_new: int = 3) -> int:
    promotions = _read_jsonl(PROMOTION_PATH)
    if not promotions:
        return 0

    queue_entries = _read_jsonl(QUEUE_PATH)
    queued_ids = {entry.get("child") for entry in queue_entries}
    run_entries = _read_jsonl(RUNS_PATH)
    ran_children = {entry.get("child") for entry in run_entries}

    added = 0
    for proposal in reversed(promotions):
        if added >= max_new:
            break
        if proposal.get("recommendation") != "PROMOTE":
            continue
        child = proposal.get("child")
        if not child or child in queued_ids or child in ran_children:
            continue
        sandbox_id = f"sbx-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{_short_name(child)}"
        entry = {
            "id": sandbox_id,
            "child": child,
            "params": {
                "pf_cf": proposal.get("pf_cf"),
                "uplift": proposal.get("uplift"),
                "baseline": proposal.get("baseline"),
            },
            "state": "queued",
            "ts": _now(),
        }
        _append_jsonl(QUEUE_PATH, entry)
        added += 1
    return added


def _simulate_run(steps: int, accounting: Dict[str, float]) -> Dict[str, Any]:
    classifier = RegimeClassifier()
    taker_fee = accounting.get("taker_fee_bps", DEFAULT_ACCOUNTING["taker_fee_bps"])
    slip = accounting.get("slip_bps", DEFAULT_ACCOUNTING["slip_bps"])
    cost = (taker_fee * 2.0 + slip) / 10000.0

    state = {"dir": 0, "bars_open": 0}
    trades: List[Dict[str, Any]] = []
    wins = losses = 0.0
    for _ in range(steps):
        vec = get_signal_vector()
        decision = decide(vec["signal_vector"], vec["raw_registry"], classifier)
        final_dir = decision["final"]["dir"]
        conf = decision["final"]["conf"]
        gates = decision["gates"]
        ret = vec["raw_registry"].get("Ret_G5", {}).get("value", 0.0)

        if state["dir"] == 0:
            if final_dir != 0 and conf >= gates["entry_min_conf"]:
                state.update({"dir": final_dir, "bars_open": 0})
                trades.append({"ts": _now(), "type": "open", "dir": final_dir})
        else:
            state["bars_open"] += 1
            pnl_pct = state["dir"] * float(ret)
            exit_due_conf = conf < gates["exit_min_conf"]
            flip_possible = final_dir != 0 and final_dir != state["dir"] and conf >= gates["reverse_min_conf"]
            timeout = state["bars_open"] > 12
            if exit_due_conf or flip_possible or timeout:
                adj_pct = pnl_pct - cost
                if adj_pct > 0:
                    wins += adj_pct
                elif adj_pct < 0:
                    losses += -adj_pct
                trades.append({
                    "ts": _now(),
                    "type": "close",
                    "dir": state["dir"],
                    "base_pct": pnl_pct,
                    "adj_pct": adj_pct,
                })
                state.update({"dir": 0, "bars_open": 0})
                if flip_possible:
                    state.update({"dir": final_dir, "bars_open": 0})
                    trades.append({"ts": _now(), "type": "open", "dir": final_dir, "reason": "flip"})
    pf_adj = float("inf") if wins > 0 and losses == 0 else (wins / losses if losses > 0 else 0.0)
    return {"trades": trades, "wins": wins, "losses": losses, "pf_adj": pf_adj}


def run_next(steps: int = 200) -> Dict[str, Any]:
    queue_entries = _read_jsonl(QUEUE_PATH)
    status = _load_status()
    queued = next((entry for entry in queue_entries if status.get(entry.get("id")) in (None, "queued")), None)
    if not queued:
        return {"ran": 0}

    sandbox_id = queued["id"]
    status[sandbox_id] = "running"
    _write_status(status)

    accounting = _load_accounting()
    result = _simulate_run(steps, accounting)

    run_dir = SANDBOX_DIR / sandbox_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trades_path = run_dir / "trades.jsonl"
    with trades_path.open("w") as f:
        for trade in result["trades"]:
            f.write(json.dumps(trade) + "\n")

    record = {
        "id": sandbox_id,
        "child": queued.get("child"),
        "steps": steps,
        "pf_adj": result["pf_adj"],
        "wins": result["wins"],
        "losses": result["losses"],
        "ts": _now(),
        "state": "complete",
    }
    _append_jsonl(RUNS_PATH, record)
    status[sandbox_id] = "complete"
    _write_status(status)
    return {"ran": 1, **record}


def run_cycle(steps: int = 200, max_new: int = 1) -> Dict[str, Any]:
    enqueued = enqueue_from_proposals(max_new=max_new)
    status = _load_status()
    queue_entries = _read_jsonl(QUEUE_PATH)
    queued_exists = any(status.get(entry.get("id"), "queued") == "queued" for entry in queue_entries)
    ran_summary = {}
    if queued_exists:
        ran_summary = run_next(steps=steps)
    return {"enqueued": enqueued, "ran": ran_summary.get("ran", 0)}
