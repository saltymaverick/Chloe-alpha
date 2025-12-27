from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _safe_load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = path.read_text().strip()
        return json.loads(data) if data else {}
    except Exception:
        return {}


def _load_history(path: Path, max_lines: int) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r") as handle:
            lines = handle.readlines()
    except Exception:
        return []
    history: List[Dict[str, Any]] = []
    for line in lines[-max_lines:]:
        try:
            record = json.loads(line)
            if isinstance(record, dict):
                history.append(record)
        except json.JSONDecodeError:
            continue
    return history


def _accumulate_metric(state: Dict[str, Any], metric: str, value: Any) -> None:
    if not isinstance(value, (int, float)):
        return
    sum_key = f"{metric}_sum"
    cnt_key = f"{metric}_count"
    state[sum_key] = state.get(sum_key, 0.0) + float(value)
    state[cnt_key] = state.get(cnt_key, 0) + 1


def _finalize_avg(state: Dict[str, Any], metric: str) -> Optional[float]:
    sum_key = f"{metric}_sum"
    cnt_key = f"{metric}_count"
    total = state.get(sum_key, 0.0)
    count = state.get(cnt_key, 0)
    if count:
        return total / count
    return None


def build_signal_context(
    history_path: str = "reports/debug/signals_history.jsonl",
    latest_path: str = "reports/debug/latest_signals.json",
    output_path: str = "reports/research/signal_context.json",
    lookback_bars: int = 96,
    max_history_lines: int = 5000,
) -> Dict[str, Any]:
    """
    Build a per-asset summary of recent signals. Each asset snapshot includes:
        - regime distribution over the lookback window
        - average dir/conf/edge
        - average ATRp / RET_1H / Funding_Bias / REALVOL / VOL_Z
        - latest snapshot for reference
    """
    history_file = Path(history_path)
    latest_file = Path(latest_path)
    output_file = Path(output_path)

    history_entries = _load_history(history_file, max_lines=max_history_lines)
    latest_snapshot = _safe_load_json(latest_file)

    by_symbol: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for entry in history_entries:
        sym = entry.get("symbol")
        if not sym:
            continue
        by_symbol[sym.upper()].append(entry)

    assets_summary: Dict[str, Any] = {}
    for sym, entries in by_symbol.items():
        window = entries[-lookback_bars:]
        if not window:
            continue
        regime_counts: Counter[str] = Counter()
        state: Dict[str, Any] = {}

        for row in window:
            regime_counts[row.get("regime", "unknown")] += 1
            _accumulate_metric(state, "conf", row.get("conf"))
            _accumulate_metric(state, "edge", row.get("combined_edge"))
            _accumulate_metric(state, "dir", row.get("dir"))
            _accumulate_metric(state, "ATRp", row.get("ATRp"))
            _accumulate_metric(state, "RET_1H", row.get("RET_1H"))
            _accumulate_metric(state, "Funding_Bias", row.get("Funding_Bias"))
            _accumulate_metric(state, "REALVOL_15", row.get("REALVOL_15"))
            _accumulate_metric(state, "REALVOL_60", row.get("REALVOL_60"))
            _accumulate_metric(state, "VOL_Z_20", row.get("VOL_Z_20"))

        assets_summary[sym] = {
            "regime_counts": dict(regime_counts),
            "avg_conf": _finalize_avg(state, "conf"),
            "avg_edge": _finalize_avg(state, "edge"),
            "avg_dir": _finalize_avg(state, "dir"),
            "avg_atrp": _finalize_avg(state, "ATRp"),
            "avg_ret_1h": _finalize_avg(state, "RET_1H"),
            "avg_funding_bias": _finalize_avg(state, "Funding_Bias"),
            "avg_realvol_15": _finalize_avg(state, "REALVOL_15"),
            "avg_realvol_60": _finalize_avg(state, "REALVOL_60"),
            "avg_vol_z_20": _finalize_avg(state, "VOL_Z_20"),
            "latest_snapshot": latest_snapshot.get(sym, {}),
            "notes": [],
        }

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timeframe": "15m",
        "lookback_bars": lookback_bars,
        "assets": assets_summary,
    }
    try:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(json.dumps(payload, indent=2))
    except Exception:
        pass
    return payload


__all__ = ["build_signal_context"]

