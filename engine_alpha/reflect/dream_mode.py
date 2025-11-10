"""
Dream Mode - Phase 6 (Paper only)
Nightly counterfactual replay exploring gate variations.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from engine_alpha.core.gpt_client import load_prompt, query_gpt
from engine_alpha.core.paths import REPORTS, CONFIG
from engine_alpha.signals.signal_processor import get_signal_vector
from engine_alpha.core.confidence_engine import decide
from engine_alpha.core.regime import RegimeClassifier


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def _read_jsonl_tail(path: Path, lines: int = 1) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        raw_lines = path.read_text().splitlines()
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for entry in raw_lines[-lines:]:
        entry = entry.strip()
        if not entry:
            continue
        try:
            out.append(json.loads(entry))
        except Exception:
            continue
    return out


def _load_gates() -> Dict[str, Any]:
    gates_path = CONFIG / "gates.yaml"
    if gates_path.exists():
        try:
            with open(gates_path, "r") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            pass
    return {}


def _baseline_entry(gates: Dict[str, Any]) -> float:
    entry_conf = gates.get("ENTRY_EXIT", gates.get("entry_exit", {})).get("entry_min_conf", {})
    if isinstance(entry_conf, dict) and entry_conf:
        return sum(entry_conf.values()) / len(entry_conf)
    return 0.6


def _baseline_exit(gates: Dict[str, Any]) -> float:
    section = gates.get("ENTRY_EXIT", gates.get("entry_exit", {}))
    return float(section.get("exit_min_conf", 0.42))


def _baseline_flip(gates: Dict[str, Any]) -> float:
    section = gates.get("ENTRY_EXIT", gates.get("entry_exit", {}))
    return float(section.get("reverse_min_conf", 0.55))


def _simulate_pf(
    steps: List[Dict[str, float]],
    entry_min: float,
    exit_min: float,
    flip_min: float,
) -> float:
    position = 0  # -1, 0, +1
    wins = 0.0
    losses = 0.0

    for step in steps:
        direction = step["dir"]
        conf = step["conf"]
        ret = step["ret"]

        if position == 0:
            if direction != 0 and conf >= entry_min:
                position = direction
        else:
            pnl = position * ret
            if pnl > 0:
                wins += pnl
            elif pnl < 0:
                losses += -pnl

            if conf < exit_min:
                position = 0
            elif direction != 0 and direction != position and conf >= flip_min:
                position = direction

    if losses <= 0:
        return wins if wins > 0 else 1.0
    return wins / losses


def _collect_steps(window_steps: int) -> List[Dict[str, float]]:
    classifier = RegimeClassifier()
    steps: List[Dict[str, float]] = []
    for _ in range(window_steps):
        signal_result = get_signal_vector()
        decision = decide(signal_result["signal_vector"], signal_result["raw_registry"], classifier)
        steps.append(
            {
                "dir": decision["final"]["dir"],
                "conf": float(decision["final"]["conf"]),
                "ret": float(
                    signal_result["raw_registry"].get("Ret_G5", {}).get("value", 0.0)
                ),
            }
        )
    return steps


def _build_combos(entry: float, exit_: float, flip: float) -> List[Tuple[float, float, float]]:
    offsets = [-0.02, 0.0, 0.02]

    def clamp(val: float) -> float:
        return max(0.01, min(0.99, val))

    entry_opts = sorted({clamp(entry + d) for d in offsets})
    exit_opts = sorted({clamp(exit_ + d) for d in offsets})
    flip_opts = sorted({clamp(flip + d) for d in offsets})
    combos: List[Tuple[float, float, float]] = []
    for e, x, f in product(entry_opts, exit_opts, flip_opts):
        combos.append((e, x, f))
    return combos


def _load_equity_tail(limit: int = 200) -> List[float]:
    path = REPORTS / "equity_curve.jsonl"
    if not path.exists():
        return []
    values: List[float] = []
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            equity = obj.get("equity")
            if equity is None:
                continue
            try:
                values.append(float(equity))
            except Exception:
                continue
    except Exception:
        return []
    return values[-limit:]


def _compute_slope(data: List[float], window: int) -> float:
    if not data:
        return 0.0
    n = min(window, len(data))
    if n < 2:
        return 0.0
    start = data[-n]
    end = data[-1]
    denom = max(n - 1, 1)
    return (end - start) / denom


def _load_council_delta() -> Dict[str, Dict[str, float]]:
    weights_path = REPORTS / "council_weights.json"
    data = _read_json(weights_path) or {}
    delta = data.get("delta") if isinstance(data, dict) else None
    if not isinstance(delta, dict):
        train_log = REPORTS / "council_train_log.jsonl"
        tail = _read_jsonl_tail(train_log, lines=1)
        if tail:
            delta = tail[-1].get("delta")
    summary: Dict[str, Dict[str, float]] = {}
    if isinstance(delta, dict):
        for regime, buckets in delta.items():
            if not isinstance(buckets, dict):
                continue
            summary[regime] = {bucket: float(value) for bucket, value in buckets.items() if isinstance(value, (int, float))}
    return summary


def _load_governance_summary() -> Dict[str, Any]:
    data = _read_json(REPORTS / "governance_vote.json") or {}
    sci = data.get("sci")
    rec = data.get("recommendation")
    out: Dict[str, Any] = {}
    if isinstance(sci, (int, float)):
        out["sci"] = float(sci)
    if isinstance(rec, str):
        out["rec"] = rec
    return out


def _load_trades_snapshot(limit: int = 100) -> Dict[str, Any]:
    trades_path = REPORTS / "trades.jsonl"
    if not trades_path.exists():
        return {}
    try:
        raw_lines = trades_path.read_text().splitlines()
    except Exception:
        raw_lines = []
    tail = raw_lines[-limit:]
    opens = closes = wins = losses = 0
    abs_sum = 0.0
    for line in tail:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        event = str(obj.get("type") or obj.get("event") or "").lower()
        if event == "open":
            opens += 1
        elif event == "close":
            closes += 1
            try:
                pct = float(obj.get("pct", 0.0))
            except Exception:
                pct = 0.0
            if pct > 0:
                wins += 1
            elif pct < 0:
                losses += 1
            abs_sum += abs(pct)
    avg_abs = abs_sum / closes if closes else 0.0
    return {
        "opens": opens,
        "closes": closes,
        "wins": wins,
        "losses": losses,
        "avg_abs_close_pct": avg_abs,
    }


def _maybe_run_gpt(summary_payload: Dict[str, Any]) -> Optional[str]:
    template = load_prompt("dream")
    if not template:
        template = "Provide a concise reflection on the dream mode analytics provided."
    prompt = f"{template}\n\nCONTEXT:\n{json.dumps(summary_payload, indent=2)}"
    result = query_gpt(prompt, "dream")
    if not result:
        return None
    text = result.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return None


def run_dream(window_steps: int = 200) -> Dict[str, Any]:
    """
    Replay recent signal vectors, test gate variations, and log proposals along with context analytics.
    """
    gates = _load_gates()
    entry_base = _baseline_entry(gates)
    exit_base = _baseline_exit(gates)
    flip_base = _baseline_flip(gates)

    steps = _collect_steps(window_steps)
    combos = _build_combos(entry_base, exit_base, flip_base)

    pf_results: List[Dict[str, Any]] = []
    for entry_min, exit_min, flip_min in combos:
        pf = _simulate_pf(steps, entry_min, exit_min, flip_min)
        pf_results.append(
            {
                "entry_min": entry_min,
                "exit_min": exit_min,
                "flip_min": flip_min,
                "pf_cf": pf,
            }
        )

    baseline_pf = _simulate_pf(steps, entry_base, exit_base, flip_base)

    pf_local_data = _read_json(REPORTS / "pf_local.json") or {"pf": baseline_pf}
    pf_local = float(pf_local_data.get("pf", baseline_pf))

    best = max(pf_results, key=lambda x: x["pf_cf"], default=None)
    if best is None:
        best = {
            "entry_min": entry_base,
            "exit_min": exit_base,
            "flip_min": flip_base,
            "pf_cf": baseline_pf,
        }

    delta = best["pf_cf"] - pf_local
    improvement_threshold = 0.05
    proposal_kind = "update_gates" if delta > improvement_threshold else "hold"

    equity_values = _load_equity_tail(limit=200)
    pf_adj_trend = {
        "slope_50": _compute_slope(equity_values, 50),
        "slope_10": _compute_slope(equity_values, 10),
    }

    council_summary = _load_council_delta()
    governance_summary = _load_governance_summary()
    trades_summary = _load_trades_snapshot(limit=100)

    context_summary = {
        "pf_adj_trend": pf_adj_trend,
        "council": council_summary,
        "governance": governance_summary,
        "trades": trades_summary,
        "proposal_kind": proposal_kind,
        "best_delta": delta,
    }

    gpt_text = _maybe_run_gpt(context_summary)

    ts = datetime.now(timezone.utc).isoformat()
    log_entry = {
        "ts": ts,
        "window_steps": window_steps,
        "entry_base": entry_base,
        "exit_base": exit_base,
        "flip_base": flip_base,
        "pf_local": pf_local,
        "baseline_pf_cf": baseline_pf,
        "best_combo": best,
        "best_delta": delta,
        "proposal_kind": proposal_kind,
        "pf_adj_trend": pf_adj_trend,
        "council": council_summary,
        "governance": governance_summary,
        "trades": trades_summary,
        "gpt_text": gpt_text,
    }

    dream_log = REPORTS / "dream_log.jsonl"
    dream_log.parent.mkdir(parents=True, exist_ok=True)
    with open(dream_log, "a") as f:
        f.write(json.dumps(log_entry) + "\n")

    proposal = {
        "ts": ts,
        "proposal_kind": proposal_kind,
        "best_combo": best,
        "pf_local": pf_local,
        "pf_cf": best["pf_cf"],
        "delta": delta,
    }

    proposals_path = REPORTS / "dream_proposals.json"
    with open(proposals_path, "w") as f:
        json.dump(proposal, f, indent=2)

    snapshot = {
        "ts": ts,
        "window_steps": window_steps,
        "pf_local": pf_local,
        "baseline_pf_cf": baseline_pf,
        "best_pf_cf": best["pf_cf"],
        "proposal_kind": proposal_kind,
        "best_combo": best,
        "pf_adj_trend": pf_adj_trend,
        "council": council_summary,
        "governance": governance_summary,
        "trades": trades_summary,
        "gpt_text": gpt_text,
    }

    snapshot_path = REPORTS / "dream_snapshot.json"
    with open(snapshot_path, "w") as f:
        json.dump(snapshot, f, indent=2)

    summary_path = REPORTS / "dream_summary.json"
    dream_summary = {
        "ts": ts,
        "pf_adj_trend": pf_adj_trend,
        "council": council_summary,
        "governance": governance_summary,
        "trades": trades_summary,
        "proposal_kind": proposal_kind,
        "gpt_text": gpt_text,
    }
    with open(summary_path, "w") as f:
        json.dump(dream_summary, f, indent=2)

    return {
        "log": log_entry,
        "proposal": proposal,
        "snapshot": snapshot,
        "summary": dream_summary,
        "combos_tested": len(combos),
    }
