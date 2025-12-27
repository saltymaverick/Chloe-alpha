from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from engine_alpha.core.paths import CONFIG, REPORTS, ROOT
from engine_alpha.core.config_loader import load_engine_config


TUNER_OUTPUT_PATH = REPORTS / "gpt" / "tuner_output.json"
CAP_PROTECTION_PATH = REPORTS / "risk" / "capital_protection.json"
PF_LOCAL_PATH = REPORTS / "pf_local.json"
LOOP_HEALTH_PATH = REPORTS / "loop" / "loop_health.json"
LOOP_HEALTH_FALLBACK_PATH = REPORTS / "loop_health.json"
SYMBOL_STATES_PATH = REPORTS / "risk" / "symbol_states.json"
TRADES_PATH = REPORTS / "trades.jsonl"

APPLY_PATCH_PATH = REPORTS / "gpt" / "tuner_apply_patch.json"
APPLY_LOG_PATH = REPORTS / "gpt" / "tuner_apply_log.jsonl"
LAST_APPLY_PATH = REPORTS / "gpt" / "tuner_last_apply.json"
ROLLBACK_ARMED_PATH = REPORTS / "gpt" / "tuner_rollback_armed.json"

# Repo rule: data writes live under /reports or /logs (not code dirs).
# Keep backups under reports/ so rollback is still possible and auditable.
BACKUPS_ROOT = REPORTS / "gpt" / "tuner_backups"

# Canonical tuning targets
ENTRY_THRESHOLDS_PATH = CONFIG / "entry_thresholds.json"
COUNCIL_WEIGHTS_PATH = CONFIG / "council_weights.yaml"
PAPER_OVERRIDES_PATH = CONFIG / "paper_tuning_overrides.json"


FATAL_LOOP_ISSUES = {
    "FEED_STALE",
    "EXEC_QUALITY_LOW",
    "DATA_GAP",
    "CLOCK_SKEW",
    "CRASH_LOOPING",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_load_json(path: Path) -> Dict[str, Any]:
    try:
        if not path.exists():
            return {}
        txt = path.read_text().strip()
        if not txt:
            return {}
        data = json.loads(txt)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True))


def _append_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj) + "\n")


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _hash_snippet(obj: Any) -> str:
    try:
        raw = json.dumps(obj, sort_keys=True, default=str).encode("utf-8")
    except Exception:
        raw = str(obj).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _count_closes_7d() -> int:
    if not TRADES_PATH.exists():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    n = 0
    try:
        with TRADES_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    evt = json.loads(line)
                except Exception:
                    continue
                if (evt.get("type") or "").lower() != "close":
                    continue
                ts = evt.get("ts") or evt.get("timestamp")
                dt = _parse_ts(ts)
                if not dt or dt < cutoff:
                    continue
                n += 1
    except Exception:
        return 0
    return n


def _loop_health() -> Tuple[Optional[bool], List[str]]:
    data = _safe_load_json(LOOP_HEALTH_PATH)
    if not data:
        data = _safe_load_json(LOOP_HEALTH_FALLBACK_PATH)
    ok = data.get("ok") if isinstance(data, dict) else None
    issues_raw = (data.get("issues") or []) if isinstance(data, dict) else []
    issues: List[str] = []
    if isinstance(issues_raw, list):
        for x in issues_raw:
            if x is None:
                continue
            issues.append(str(x))
    return (bool(ok) if isinstance(ok, bool) else None), issues


def _pf_local_ok() -> Tuple[bool, List[str]]:
    pf = _safe_load_json(PF_LOCAL_PATH)
    blocked: List[str] = []
    count_24h = pf.get("count_24h")
    try:
        count_24h = int(count_24h or 0)
    except Exception:
        count_24h = 0
    if count_24h < 10:
        blocked.append("G6:pf_count_24h_lt_10")

    pf_24h = pf.get("pf_24h")
    pf_7d = pf.get("pf_7d")
    # handle "inf" string
    def _to_float(x: Any) -> Optional[float]:
        try:
            if x is None:
                return None
            if isinstance(x, str) and x.lower() == "inf":
                return float("inf")
            return float(x)
        except Exception:
            return None

    pf24 = _to_float(pf_24h)
    pf7 = _to_float(pf_7d)
    if pf24 is None and pf7 is None:
        blocked.append("G6:pf_missing")
    else:
        ok_perf = (pf24 is not None and pf24 >= 0.95) or (pf7 is not None and pf7 >= 1.00)
        if not ok_perf:
            blocked.append("G6:pf_below_floor")
    return (len(blocked) == 0), blocked


def _mode_is_paper() -> bool:
    cfg = load_engine_config()
    mode = (cfg.get("mode") if isinstance(cfg, dict) else None) or "PAPER"
    return str(mode).upper() == "PAPER"


def _capital_mode() -> str:
    cp = _safe_load_json(CAP_PROTECTION_PATH)
    mode = (cp.get("global") or {}).get("mode") if isinstance(cp, dict) else None
    mode = mode or cp.get("mode") or "unknown"
    return str(mode)


def _cooldown_ok(now: datetime) -> Tuple[bool, Optional[str]]:
    last = _safe_load_json(LAST_APPLY_PATH)
    last_ts = last.get("last_apply_ts") if isinstance(last, dict) else None
    last_dt = _parse_ts(last_ts)
    if last_dt is None:
        return True, None
    if (now - last_dt) < timedelta(hours=12):
        return False, "A5:cooldown_12h"
    return True, None


@dataclass
class NormalizedChange:
    kind: str  # "weight" | "threshold" | "symbol_threshold"
    path: str  # human-readable target key path
    delta: float
    symbol: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"kind": self.kind, "path": self.path, "delta": self.delta}
        if self.symbol:
            d["symbol"] = self.symbol
        if isinstance(self.meta, dict) and self.meta:
            d["meta"] = self.meta
        return d


_SYM_RE = re.compile(r"\b[A-Z0-9]{3,}USDT\b")


def _extract_tuner_risk(tuner: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], List[str]]:
    """
    Returns (status, risk_level, blocked_by_list) in normalized form.
    Supports schema variants; if missing risk field, caller should block.
    """
    status = tuner.get("status") or tuner.get("state") or tuner.get("mode")
    risk = tuner.get("risk_level") or tuner.get("risk") or tuner.get("risk_rating")
    blocked_by = tuner.get("blocked_by") or tuner.get("blocks") or []
    bb: List[str] = []
    if isinstance(blocked_by, list):
        bb = [str(x) for x in blocked_by if x is not None]
    elif isinstance(blocked_by, str):
        bb = [blocked_by]
    return (str(status) if status is not None else None, str(risk) if risk is not None else None, bb)


def _detect_structural(tuner: Dict[str, Any]) -> Optional[str]:
    """
    Reject structural changes by scanning tuner output text/keys for forbidden domains.
    """
    try:
        blob = json.dumps(tuner, sort_keys=True, default=str).lower()
    except Exception:
        blob = str(tuner).lower()
    forbidden_tokens = [
        "add_signal",
        "remove_signal",
        "signal_registry",
        "bucket",
        "regime_classifier",
        "lane",
        "safe_mode",
        "profit_amplifier",
        "pa gates",
        "pa_gates",
        "capital_protection",
        "slot_limits",
        "review_bootstrap",
        "exploration_lane",
        "recovery_lane",
    ]
    for tok in forbidden_tokens:
        if tok in blob:
            return tok
    return None


def _normalize_changes(tuner: Dict[str, Any]) -> Tuple[List[NormalizedChange], List[str], List[str]]:
    """
    Returns (changes, touched_symbols, blocked_by_parse_errors).
    """
    blocked: List[str] = []
    changes: List[NormalizedChange] = []
    touched_symbols: List[str] = []

    # accept a few top-level schema variants
    candidates: Any = (
        tuner.get("proposed_changes")
        or tuner.get("changes")
        or tuner.get("delta_changes")
        or tuner.get("deltas")
    )

    # v-run_tuner_cycle style proposals: {"proposals": {SYM: {"conf_min_delta":..., "exploration_cap_delta":...}}}
    if not candidates and isinstance(tuner.get("proposals"), dict):
        proposals = tuner.get("proposals") or {}
        for sym, props in proposals.items():
            if not isinstance(props, dict):
                continue
            sym_u = str(sym).upper()
            sym_is_valid = bool(_SYM_RE.fullmatch(sym_u))
            # conf_min_delta is a threshold delta; allow if numeric
            conf_delta_nonzero = False
            if "conf_min_delta" in props:
                try:
                    d = float(props.get("conf_min_delta") or 0.0)
                except Exception:
                    blocked.append("C?:cannot_parse_conf_min_delta")
                    continue
                if abs(d) > 0.0:
                    conf_delta_nonzero = True
                    changes.append(
                        NormalizedChange(kind="symbol_threshold", path="paper_tuning_overrides.conf_min_delta", delta=d, symbol=sym_u)
                    )
            # exploration_cap_delta is lane-rule; only allow if explicitly zero
            if "exploration_cap_delta" in props:
                try:
                    cap_d = float(props.get("exploration_cap_delta") or 0.0)
                except Exception:
                    blocked.append("structural:exploration_cap_delta_unparseable")
                    continue
                if abs(cap_d) > 0.0:
                    blocked.append("structural:lane_rule_exploration_cap_delta")

            # Only treat a symbol as "touched" if it has an actionable (non-zero) delta.
            # This prevents G4 from blocking the whole universe when tuner is effectively no-op.
            if sym_is_valid and conf_delta_nonzero:
                touched_symbols.append(sym_u)

        return changes, sorted(set(touched_symbols)), blocked

    # list-of-change objects
    if isinstance(candidates, list):
        for c in candidates:
            if not isinstance(c, dict):
                blocked.append("C?:changes_not_dict")
                continue
            # attempt to infer symbol mention
            sym = c.get("symbol") or c.get("sym")
            if sym:
                sym_u = str(sym).upper()
                if _SYM_RE.fullmatch(sym_u):
                    touched_symbols.append(sym_u)

            kind = (c.get("kind") or c.get("type") or "").lower()
            path = str(c.get("path") or c.get("key") or c.get("target") or "")
            delta_raw = c.get("delta")
            if delta_raw is None and "new" in c and "old" in c:
                try:
                    delta_raw = float(c.get("new")) - float(c.get("old"))
                except Exception:
                    delta_raw = None
            try:
                delta = float(delta_raw)
            except Exception:
                blocked.append("C?:delta_not_numeric")
                continue
            if not path:
                blocked.append("C?:missing_path")
                continue

            # classify
            if "council_weights" in path or "weights" in path or kind == "weight":
                changes.append(NormalizedChange(kind="weight", path=path, delta=delta, symbol=str(sym).upper() if sym else None, meta=c))
            elif "threshold" in path or kind == "threshold" or "entry_min" in path:
                changes.append(NormalizedChange(kind="threshold", path=path, delta=delta, symbol=str(sym).upper() if sym else None, meta=c))
            else:
                blocked.append("structural:unrecognized_change_kind")
    elif isinstance(candidates, dict):
        # dict style: weights_delta / threshold_deltas
        w = candidates.get("weights_delta") or candidates.get("weight_deltas")
        t = candidates.get("threshold_deltas") or candidates.get("thresholds_delta")
        if isinstance(w, dict):
            for k, v in w.items():
                try:
                    delta = float(v)
                except Exception:
                    blocked.append("C?:weights_delta_not_numeric")
                    continue
                changes.append(NormalizedChange(kind="weight", path=str(k), delta=delta))
        if isinstance(t, dict):
            for k, v in t.items():
                try:
                    delta = float(v)
                except Exception:
                    blocked.append("C?:threshold_delta_not_numeric")
                    continue
                changes.append(NormalizedChange(kind="threshold", path=str(k), delta=delta))
        if not isinstance(w, dict) and not isinstance(t, dict):
            blocked.append("C?:unknown_changes_dict_schema")
    else:
        blocked.append("C?:no_changes_found")

    # fall back symbol detection via regex scan
    try:
        blob = json.dumps(tuner, sort_keys=True, default=str)
        touched_symbols.extend(_SYM_RE.findall(blob))
    except Exception:
        pass

    return changes, sorted(set([s.upper() for s in touched_symbols])), blocked


def _change_size_gates(changes: List[NormalizedChange]) -> List[str]:
    blocked: List[str] = []
    if len(changes) > 6:
        blocked.append("C1:num_changes_gt_6")

    # weight deltas
    w_deltas = [c.delta for c in changes if c.kind == "weight"]
    if w_deltas:
        if any(abs(d) > 0.05 for d in w_deltas):
            blocked.append("C2:weight_delta_gt_0.05")
        if sum(abs(d) for d in w_deltas) > 0.12:
            blocked.append("C2:weight_l1_gt_0.12")

    # threshold deltas
    t_deltas = [c.delta for c in changes if c.kind in {"threshold", "symbol_threshold"}]
    if t_deltas:
        if any(abs(d) > 0.03 for d in t_deltas):
            blocked.append("C3:threshold_delta_gt_0.03")
    return blocked


def _require_symbol_samples(symbols: List[str], symbol_states: Dict[str, Any]) -> List[str]:
    blocked: List[str] = []
    sym_map = symbol_states.get("symbols") if isinstance(symbol_states, dict) else {}
    if not isinstance(sym_map, dict):
        sym_map = {}
    for sym in symbols:
        entry = sym_map.get(sym) or {}
        n = entry.get("n_closes_7d") or entry.get("closes_7d") or entry.get("n_7d") or 0
        try:
            n = int(n or 0)
        except Exception:
            n = 0
        if n < 20:
            blocked.append(f"G4:symbol_sample_lt_20:{sym}")
    return blocked


def _apply_entry_threshold_deltas(changes: List[NormalizedChange]) -> Tuple[bool, Dict[str, Any], Dict[str, Any], List[str]]:
    """
    Apply threshold deltas to config/entry_thresholds.json.
    Supported paths:
      - 'trend_down', 'trend_up', 'high_vol', 'chop' (direct)
      - strings containing those tokens
    """
    before = _safe_load_json(ENTRY_THRESHOLDS_PATH)
    if not before:
        before = {"trend_down": 0.50, "high_vol": 0.55, "trend_up": 0.60, "chop": 0.65}
    after = dict(before)
    blocked: List[str] = []
    regime_keys = ["trend_down", "trend_up", "high_vol", "chop"]

    touched = False
    for c in changes:
        if c.kind != "threshold":
            continue
        key = None
        for rk in regime_keys:
            if c.path == rk or rk in c.path:
                key = rk
                break
        if not key:
            blocked.append(f"structural:unknown_threshold_target:{c.path}")
            continue
        old = after.get(key)
        try:
            old_f = float(old)
        except Exception:
            blocked.append(f"C?:threshold_old_not_numeric:{key}")
            continue
        new_f = max(0.0, min(1.0, old_f + float(c.delta)))
        after[key] = float(new_f)
        touched = True

    if blocked:
        return False, before, after, blocked
    if not touched:
        return True, before, after, []

    _atomic_write_json(ENTRY_THRESHOLDS_PATH, after)
    return True, before, after, []


def _apply_council_weight_deltas(changes: List[NormalizedChange]) -> Tuple[bool, str, str, List[str]]:
    """
    Apply weight deltas to config/council_weights.yaml.
    Supported path forms:
      - 'council_weights.<regime>.<bucket>'
      - '<regime>.<bucket>'
    """
    blocked: List[str] = []
    try:
        import yaml  # local import to keep module lightweight
    except Exception as exc:
        return False, "", "", [f"yaml_missing:{exc!r}"]

    if not COUNCIL_WEIGHTS_PATH.exists():
        return False, "", "", ["missing_council_weights_yaml"]
    before_text = COUNCIL_WEIGHTS_PATH.read_text()
    try:
        data = yaml.safe_load(before_text) or {}
    except Exception:
        return False, before_text, before_text, ["yaml_parse_failed"]

    cw = data.get("council_weights")
    if not isinstance(cw, dict):
        return False, before_text, before_text, ["yaml_missing_council_weights_root"]

    touched = False
    for c in changes:
        if c.kind != "weight":
            continue
        p = c.path.replace("/", ".")
        p = p.replace("council_weights.", "")
        parts = [x for x in p.split(".") if x]
        if len(parts) < 2:
            blocked.append(f"structural:bad_weight_path:{c.path}")
            continue
        regime = parts[-2]
        bucket = parts[-1]
        if regime not in cw or not isinstance(cw.get(regime), dict):
            blocked.append(f"structural:unknown_regime:{regime}")
            continue
        if bucket not in cw[regime]:
            blocked.append(f"structural:unknown_bucket:{bucket}")
            continue
        try:
            old = float(cw[regime].get(bucket))
        except Exception:
            blocked.append(f"C?:weight_old_not_numeric:{regime}.{bucket}")
            continue
        cw[regime][bucket] = float(max(0.0, old + float(c.delta)))
        touched = True

    if blocked:
        return False, before_text, before_text, blocked

    if touched:
        # Write back with minimal formatting disturbance (yaml.safe_dump will reformat; accept as best effort).
        after_text = yaml.safe_dump(data, sort_keys=False)
        _atomic_write_text(COUNCIL_WEIGHTS_PATH, after_text)
        return True, before_text, after_text, []
    return True, before_text, before_text, []


def _apply_symbol_conf_overrides(changes: List[NormalizedChange]) -> Tuple[bool, Dict[str, Any], Dict[str, Any], List[str]]:
    """
    Apply per-symbol conf_min_delta changes to config/paper_tuning_overrides.json.
    """
    before = _safe_load_json(PAPER_OVERRIDES_PATH)
    # accept wrapped or direct format
    overrides = before.get("overrides") if isinstance(before.get("overrides"), dict) else (before if isinstance(before, dict) else {})
    overrides = overrides.copy() if isinstance(overrides, dict) else {}
    after_wrapper = dict(before) if isinstance(before, dict) else {}
    blocked: List[str] = []
    touched = False

    for c in changes:
        if c.kind != "symbol_threshold":
            continue
        sym = (c.symbol or "").upper()
        if not _SYM_RE.fullmatch(sym):
            blocked.append(f"structural:bad_symbol:{sym or c.symbol}")
            continue
        entry = overrides.get(sym) if isinstance(overrides.get(sym), dict) else {}
        entry = dict(entry) if isinstance(entry, dict) else {}
        old = entry.get("conf_min_delta", 0.0)
        try:
            old_f = float(old or 0.0)
        except Exception:
            old_f = 0.0
        entry["conf_min_delta"] = float(old_f + float(c.delta))
        # clamp accumulated override safely
        entry["conf_min_delta"] = max(-0.05, min(0.05, float(entry["conf_min_delta"])))
        overrides[sym] = entry
        touched = True

    if blocked:
        return False, before, before, blocked

    if not touched:
        return True, before, before, []

    # write wrapped format
    out = {
        "generated_at": _now_iso(),
        "mode": "PAPER_ONLY",
        "overrides": overrides,
    }
    _atomic_write_json(PAPER_OVERRIDES_PATH, out)
    return True, before, out, []


def apply_tuner_if_safe(*, now_ts: str | None = None, dry_run_only: bool = False) -> dict:
    now = _parse_ts(now_ts) or datetime.now(timezone.utc)
    blocked_by: List[str] = []

    # Load required inputs
    tuner = _safe_load_json(TUNER_OUTPUT_PATH)
    if not tuner:
        return {
            "applied": False,
            "blocked_by": ["missing_tuner_output"],
            "reason": f"missing {str(TUNER_OUTPUT_PATH)}",
            "summary": {},
            "changes": [],
            "backup_path": None,
        }

    # G1: Mode gate
    if not _mode_is_paper():
        blocked_by.append("G1:not_paper_mode")

    # G2: Not in global risk-off
    cap_mode = _capital_mode()
    if cap_mode in {"halt_new_entries", "de_risk", "review"}:
        blocked_by.append(f"G2:global_risk_off:{cap_mode}")

    # A5 cooldown (applies even in dry-run; it is a real apply gate)
    ok_cd, cd_reason = _cooldown_ok(now)
    if not ok_cd and cd_reason:
        blocked_by.append(cd_reason)

    # G3: Sample size gate
    closes_7d = _count_closes_7d()
    if closes_7d < 40:
        blocked_by.append("G3:closed_trades_7d_lt_40")

    # G5: Stability gate
    ok_health, issues = _loop_health()
    if ok_health is not True:
        blocked_by.append("G5:loop_health_ok_not_true")
    if any(str(i).upper() in FATAL_LOOP_ISSUES for i in issues):
        blocked_by.append("G5:fatal_loop_issue")

    # G6: Performance sanity gate
    ok_pf, pf_blocks = _pf_local_ok()
    blocked_by.extend(pf_blocks)

    # G7: Tuner risk gate
    status, risk_level, tuner_blocks = _extract_tuner_risk(tuner)
    if tuner_blocks:
        blocked_by.append("G7:tuner_blocked_by_nonempty")
    if status is None or str(status).upper() != "ACTIVE":
        blocked_by.append("G7:status_not_ACTIVE")
    if risk_level is None or str(risk_level).upper() != "LOW":
        blocked_by.append("G7:risk_not_LOW")

    # Structural rejection
    structural_hit = _detect_structural(tuner)
    if structural_hit:
        blocked_by.append(f"structural:{structural_hit}")

    # Parse/normalize changes
    norm_changes, touched_symbols, parse_blocks = _normalize_changes(tuner)
    blocked_by.extend(parse_blocks)

    # Change-size gates
    blocked_by.extend(_change_size_gates(norm_changes))

    # G4: Per-symbol sample gate if tuner touches symbols explicitly
    if touched_symbols:
        sym_states = _safe_load_json(SYMBOL_STATES_PATH)
        if not sym_states:
            blocked_by.append("G4:missing_symbol_states")
        else:
            blocked_by.extend(_require_symbol_samples(touched_symbols, sym_states))

    # If we cannot parse numeric deltas clearly, block (explicitly requested)
    if not norm_changes and "C?:no_changes_found" not in blocked_by:
        blocked_by.append("C?:no_changes_found")

    summary = {
        "now": now.isoformat(),
        "capital_mode": cap_mode,
        "closed_trades_7d": closes_7d,
        "loop_ok": ok_health,
        "loop_issues": issues,
        "tuner_hash": _hash_snippet(tuner),
        "touched_symbols": touched_symbols,
        "num_changes": len(norm_changes),
    }

    if blocked_by or dry_run_only:
        return {
            "applied": False,
            "blocked_by": sorted(set(blocked_by)) if blocked_by else (["dry_run_only"] if dry_run_only else []),
            "reason": "blocked" if blocked_by else "dry_run_only",
            "summary": summary,
            "changes": [c.to_dict() for c in norm_changes],
            "backup_path": None,
        }

    # --- Apply path ---
    apply_ts = now.strftime("%Y%m%dT%H%M%SZ")
    backup_dir = BACKUPS_ROOT / apply_ts
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Build apply patch payload
    patch_payload = {
        "timestamp": now.isoformat(),
        "tuner_output_hash": _hash_snippet(tuner),
        "changes": [c.to_dict() for c in norm_changes],
        "targets": [],
    }

    # Back up relevant files
    targets: List[Path] = []
    # always back up engine_config + key reports
    targets.extend([CONFIG / "engine_config.json", CAP_PROTECTION_PATH, PF_LOCAL_PATH])
    # per-change backups
    if any(c.kind == "threshold" for c in norm_changes):
        targets.append(ENTRY_THRESHOLDS_PATH)
    if any(c.kind == "weight" for c in norm_changes):
        targets.append(COUNCIL_WEIGHTS_PATH)
    if any(c.kind == "symbol_threshold" for c in norm_changes):
        targets.append(PAPER_OVERRIDES_PATH)

    copied: List[str] = []
    for p in targets:
        try:
            if not p.exists():
                continue
            rel = p.relative_to(ROOT)
            dest = backup_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
            copied.append(str(rel))
        except Exception:
            continue

    _atomic_write_json(backup_dir / "backup_meta.json", {"timestamp": now.isoformat(), "files": copied, "reason": "tuner_apply"})

    # Apply changes atomically (by target class)
    patch_payload["targets"] = [str(p.relative_to(ROOT)) for p in targets if p.exists()]

    before_after: Dict[str, Any] = {}
    # thresholds
    ok_thr, thr_before, thr_after, thr_block = _apply_entry_threshold_deltas(norm_changes)
    if not ok_thr:
        return {
            "applied": False,
            "blocked_by": thr_block,
            "reason": "apply_failed_thresholds",
            "summary": summary,
            "changes": [c.to_dict() for c in norm_changes],
            "backup_path": str(backup_dir),
        }
    if thr_before != thr_after:
        before_after["entry_thresholds"] = {"before": thr_before, "after": thr_after}

    # weights
    ok_w, w_before, w_after, w_block = _apply_council_weight_deltas(norm_changes)
    if not ok_w:
        return {
            "applied": False,
            "blocked_by": w_block,
            "reason": "apply_failed_weights",
            "summary": summary,
            "changes": [c.to_dict() for c in norm_changes],
            "backup_path": str(backup_dir),
        }
    if w_before != w_after:
        before_after["council_weights_yaml_sha"] = {
            "before": hashlib.sha256(w_before.encode("utf-8")).hexdigest()[:16],
            "after": hashlib.sha256(w_after.encode("utf-8")).hexdigest()[:16],
        }

    # symbol thresholds
    ok_sym, sym_before, sym_after, sym_block = _apply_symbol_conf_overrides(norm_changes)
    if not ok_sym:
        return {
            "applied": False,
            "blocked_by": sym_block,
            "reason": "apply_failed_symbol_overrides",
            "summary": summary,
            "changes": [c.to_dict() for c in norm_changes],
            "backup_path": str(backup_dir),
        }
    if sym_before != sym_after:
        before_after["paper_tuning_overrides"] = {"before_hash": _hash_snippet(sym_before), "after_hash": _hash_snippet(sym_after)}

    # Write patch & logs
    patch_payload["before_after"] = before_after
    _atomic_write_json(APPLY_PATCH_PATH, patch_payload)

    # Log apply
    log_entry = {
        "ts": now.isoformat(),
        "applied": True,
        "passed_gates": True,
        "summary": summary,
        "changes": [c.to_dict() for c in norm_changes],
        "backup_path": str(backup_dir),
    }
    _append_jsonl(APPLY_LOG_PATH, log_entry)

    # Cooldown stamp
    _atomic_write_json(LAST_APPLY_PATH, {"last_apply_ts": now.isoformat(), "backup_path": str(backup_dir)})

    # Rollback guard record (arming only; no automation)
    _atomic_write_json(
        ROLLBACK_ARMED_PATH,
        {
            "backup_path": str(backup_dir),
            "apply_ts": now.isoformat(),
            "rollback_triggers": {
                "pf_24h_below": 0.90,
                "loss_streak_gte": 7,
                "capital_mode_flip_to": "halt_new_entries",
            },
        },
    )

    return {
        "applied": True,
        "blocked_by": [],
        "reason": "applied",
        "summary": summary,
        "changes": [c.to_dict() for c in norm_changes],
        "backup_path": str(backup_dir),
    }


__all__ = ["apply_tuner_if_safe"]


