from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine_alpha.core.gpt_client import query_gpt
from engine_alpha.core.paths import CONFIG, REPORTS

DEBUG_DIR = REPORTS / "debug"
LATEST_SIGNALS_PATH = DEBUG_DIR / "latest_signals.json"
WHY_BLOCKED_PATH = DEBUG_DIR / "why_blocked.jsonl"
EXPLAIN_LOG_PATH = DEBUG_DIR / "decision_explanations.jsonl"
LOOSEN_FLAGS_PATH = CONFIG / "loosen_flags.json"
OBS_MODE_PATH = CONFIG / "observation_mode.json"
REGIME_THRESHOLDS_PATH = CONFIG / "regime_thresholds.json"

_OBS_CFG_CACHE: Optional[Dict[str, Any]] = None
_LOOSEN_FLAGS_CACHE: Optional[Dict[str, Any]] = None
_REGIME_THRESH_CACHE: Optional[Dict[str, Any]] = None


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_loosen_flags() -> Dict[str, Any]:
    global _LOOSEN_FLAGS_CACHE
    if _LOOSEN_FLAGS_CACHE is not None:
        return _LOOSEN_FLAGS_CACHE
    data = _load_json(LOOSEN_FLAGS_PATH)
    normalized: Dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            normalized[key.upper()] = value
    _LOOSEN_FLAGS_CACHE = normalized
    return normalized


def _load_obs_cfg() -> Dict[str, Any]:
    global _OBS_CFG_CACHE
    if _OBS_CFG_CACHE is not None:
        return _OBS_CFG_CACHE
    data = _load_json(OBS_MODE_PATH)
    _OBS_CFG_CACHE = data if data else {}
    return _OBS_CFG_CACHE


def _load_regime_thresholds() -> Dict[str, Any]:
    global _REGIME_THRESH_CACHE
    if _REGIME_THRESH_CACHE is not None:
        return _REGIME_THRESH_CACHE
    data = _load_json(REGIME_THRESHOLDS_PATH)
    _REGIME_THRESH_CACHE = data if data else {}
    return _REGIME_THRESH_CACHE


def _load_why_blocked(limit: int = 50) -> List[Dict[str, Any]]:
    if not WHY_BLOCKED_PATH.exists():
        return []
    try:
        lines = WHY_BLOCKED_PATH.read_text().splitlines()
    except Exception:
        return []
    entries: List[Dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                entries.append(parsed)
        except Exception:
            continue
    return entries


def _build_prompt(payload: Dict[str, Any]) -> str:
    return (
        "You are Chloe's decision explainer. Review the latest signals and "
        "why-blocked log to explain, asset by asset, why no trades fired. "
        "Reference regime, direction, confidence vs thresholds, combined edge, "
        "quant gate reasons, and whether soft_mode is enabled. "
        "Suggest one concrete next check per asset if appropriate.\n\n"
        "JSON DATA:\n"
        f"{json.dumps(payload, indent=2)}\n"
    )


def _fallback_text(payload: Dict[str, Any]) -> str:
    symbol_summaries = payload.get("symbol_explanations") or {}
    if symbol_summaries:
        lines = ["GPT unavailable; summarizing gate outcomes per asset."]
        for sym, msg in symbol_summaries.items():
            lines.append(f"{sym}: {msg}")
        return "\n".join(lines)
    return "No gate information available."


def _get_observation_override(symbol: str) -> Dict[str, Any]:
    cfg = _load_obs_cfg()
    default_cfg = cfg.get("default", {})
    overrides = cfg.get("asset_overrides", {})
    merged = dict(default_cfg)
    asset_cfg = overrides.get(symbol.upper())
    if isinstance(asset_cfg, dict):
        merged.update(asset_cfg)
    return merged


def compute_effective_thresholds(symbol: str, regime: Optional[str], soft_mode: bool) -> Dict[str, float]:
    symbol = symbol.upper()
    reg = (regime or "unknown").lower()

    regime_cfg = _load_regime_thresholds().get(reg, {})
    eff_min_conf = float(regime_cfg.get("entry_min_conf", 0.5))
    eff_edge_floor = float(regime_cfg.get("edge_floor", 0.0))

    obs_cfg = _get_observation_override(symbol)
    obs_min_conf = obs_cfg.get("min_conf")
    obs_edge_floor = obs_cfg.get("edge_floor")

    if obs_min_conf is not None:
        eff_min_conf = min(eff_min_conf, float(obs_min_conf))
    if obs_edge_floor is not None:
        eff_edge_floor = min(eff_edge_floor, float(obs_edge_floor))

    loosen_cfg = _load_loosen_flags().get(symbol, {})
    if soft_mode or loosen_cfg.get("soft_mode"):
        soft_conf = loosen_cfg.get("min_conf_soft") or loosen_cfg.get("min_conf")
        soft_edge = loosen_cfg.get("edge_floor_soft") or loosen_cfg.get("edge_floor")
        if soft_conf is not None:
            eff_min_conf = min(eff_min_conf, float(soft_conf))
        if soft_edge is not None:
            eff_edge_floor = min(eff_edge_floor, float(soft_edge))

    return {"min_conf": eff_min_conf, "edge_floor": eff_edge_floor}


def _latest_block_map(entries: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    block_map: Dict[str, Dict[str, Any]] = {}
    for entry in entries:
        sym = entry.get("symbol")
        if not sym:
            continue
        block_map[sym] = entry
    return block_map


def explain_no_trade_for_symbol(
    symbol: str,
    latest_block: Optional[Dict[str, Any]],
    latest_snapshot: Optional[Dict[str, Any]],
) -> str:
    symbol = symbol.upper()
    snapshot = latest_snapshot or {}
    block = latest_block or {}

    regime = block.get("regime") or snapshot.get("regime") or "unknown"
    conf = float(block.get("conf", snapshot.get("conf", 0.0)) or 0.0)
    edge = float(block.get("combined_edge", snapshot.get("combined_edge", 0.0)) or 0.0)
    direction = block.get("dir", snapshot.get("dir"))
    gate_stage = block.get("gate_stage") or "unknown"
    reason = block.get("reason") or "unspecified"
    soft_mode = bool(snapshot.get("soft_mode"))

    thresholds = compute_effective_thresholds(symbol, regime, soft_mode)
    eff_min_conf = thresholds["min_conf"]
    eff_edge_floor = thresholds["edge_floor"]

    if not latest_block:
        return (
            f"No recent gate block recorded. Latest snapshot: dir={direction}, "
            f"conf={conf:.2f}, edge={edge:.4f}, regime={regime}."
        )

    if gate_stage == "regime_gate":
        return f"Regime {regime} is currently disallowed for {symbol}; waiting for allowed regime."
    if gate_stage == "direction":
        return f"Direction neutral (dir={direction}) in regime={regime}; waiting for stronger bias."
    if gate_stage == "confidence_gate":
        return (
            f"Confidence {conf:.2f} below effective threshold {eff_min_conf:.2f} "
            f"(regime={regime}, soft_mode={soft_mode})."
        )
    if gate_stage in ("edge_gate", "quant_gate"):
        if edge < eff_edge_floor:
            return (
                f"Combined edge {edge:.4f} below floor {eff_edge_floor:.4f}; "
                f"quant gate rejected despite conf={conf:.2f}."
            )
        return f"Quant gate blocked trade (reason={reason}); conf={conf:.2f}, edge={edge:.4f}."

    return (
        f"No trade (gate_stage={gate_stage}, reason={reason}); "
        f"conf={conf:.2f}, edge={edge:.4f}, regime={regime}."
    )


def load_latest_blocks(limit: int = 200) -> Dict[str, Dict[str, Any]]:
    entries = _load_why_blocked(limit=limit)
    return _latest_block_map(entries)


def load_latest_signals(symbols: Optional[List[str]] = None) -> Dict[str, Any]:
    data = _load_json(LATEST_SIGNALS_PATH)
    filtered: Dict[str, Any] = {}
    for key, value in data.items():
        if key == "generated_at":
            continue
        if symbols and key not in symbols:
            continue
        filtered[key] = value
    return filtered


def run_decision_explainer(
    symbols: Optional[List[str]] = None,
    *,
    use_gpt: bool = True,
    reason_limit: int = 50,
) -> Dict[str, Any]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    focus_symbols = symbols or ["ETHUSDT", "BTCUSDT", "SOLUSDT", "DOGEUSDT"]

    latest_per_symbol = load_latest_signals(focus_symbols)
    why_entries = _load_why_blocked(limit=reason_limit)
    latest_blocks = _latest_block_map(why_entries)
    loosen_flags = {
        sym: cfg
        for sym, cfg in _load_loosen_flags().items()
        if sym in focus_symbols
    }

    symbol_explanations = {
        sym: explain_no_trade_for_symbol(sym, latest_blocks.get(sym), latest_per_symbol.get(sym, {}))
        for sym in focus_symbols
    }

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbols": focus_symbols,
        "latest_signals": latest_per_symbol,
        "why_blocked_recent": [entry for entry in why_entries if entry.get("symbol") in focus_symbols],
        "loosen_flags": loosen_flags,
        "symbol_explanations": symbol_explanations,
    }

    if not use_gpt:
        explanation = _fallback_text(payload)
    else:
        prompt = _build_prompt(payload)
        response = query_gpt(prompt, purpose="decision_explainer")
        explanation = (
            response.get("text")
            if response and response.get("text")
            else _fallback_text(payload)
        )

    record = {"ts": payload["generated_at"], "explanation": explanation}
    try:
        with EXPLAIN_LOG_PATH.open("a") as handle:
            handle.write(json.dumps(record) + "\n")
    except Exception:
        pass
    return {"generated_at": payload["generated_at"], "explanation": explanation}

