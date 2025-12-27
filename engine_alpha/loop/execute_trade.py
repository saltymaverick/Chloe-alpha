from __future__ import annotations
import json, os, time, yaml
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from datetime import datetime, timezone
from engine_alpha.core.paths import REPORTS, CONFIG
from engine_alpha.core.config_loader import load_engine_config
from engine_alpha.risk.symbol_state import load_symbol_states

DEBUG_SIGNALS = os.getenv("DEBUG_SIGNALS", "0") == "1"


def _get_default_timeframe() -> str:
    """Load default timeframe from engine_config.json, fallback to '15m'."""
    try:
        cfg = load_engine_config()
        if isinstance(cfg, dict):
            return cfg.get("timeframe", "15m")
    except Exception:
        pass
    return "15m"
from engine_alpha.loop.position_manager import get_open_position, set_position, compute_quant_position_size
from engine_alpha.loop.exit_engine import get_exit_label
from engine_alpha.risk.sanity_gates import check_sanity

OBS_CFG_PATH = CONFIG / "observation_mode.json"
LOOSEN_FLAGS_PATH = CONFIG / "loosen_flags.json"
_LOOSEN_FLAGS: Dict[str, Dict[str, Any]] | None = None
_EXPL_OVERRIDES: Dict[str, Any] | None = None
_EXPL_COOLDOWN_CACHE: Dict[str, datetime] = {}
EXPL_COOLDOWN_FLOOR = 900  # seconds


def _load_loosen_flags() -> Dict[str, Dict[str, Any]]:
    """Load (and cache) per-asset loosen flags."""
    global _LOOSEN_FLAGS
    if _LOOSEN_FLAGS is not None:
        return _LOOSEN_FLAGS
    if not LOOSEN_FLAGS_PATH.exists():
        _LOOSEN_FLAGS = {}
        return _LOOSEN_FLAGS
    try:
        data = json.loads(LOOSEN_FLAGS_PATH.read_text())
        if isinstance(data, dict):
            normalized: Dict[str, Dict[str, Any]] = {}
            for key, info in data.items():
                if isinstance(info, dict):
                    normalized[key.upper()] = info
            _LOOSEN_FLAGS = normalized
        else:
            _LOOSEN_FLAGS = {}
    except Exception:
        _LOOSEN_FLAGS = {}
    return _LOOSEN_FLAGS


def _load_exploration_config() -> Dict[str, Any]:
    """Load exploration mode configuration from engine_config.json."""
    try:
        cfg = load_engine_config()
        expl = cfg.get("exploration_mode", {}) if isinstance(cfg, dict) else {}
        return {
            "enabled": expl.get("enabled", False),
            "min_direction": float(expl.get("min_direction", 0.10)),
            "max_size_factor": float(expl.get("max_size_factor", 0.15)),
            "allow_in_trend_up": expl.get("allow_in_trend_up", True),
            "allow_in_trend_down": expl.get("allow_in_trend_down", True),
            "allow_in_high_vol": expl.get("allow_in_high_vol", True),
            "allow_in_chop": expl.get("allow_in_chop", False),
        }
    except Exception:
        pass
    return {
        "enabled": False,
        "min_direction": 0.10,
        "max_size_factor": 0.15,
        "allow_in_trend_up": True,
        "allow_in_trend_down": True,
        "allow_in_high_vol": True,
        "allow_in_chop": False,
    }


def _load_exploration_overrides() -> Dict[str, Any]:
    """Load exploration_overrides from engine_config.json (with expiry checks)."""
    global _EXPL_OVERRIDES
    now_dt = datetime.now(timezone.utc)
    if _EXPL_OVERRIDES is not None:
        return _EXPL_OVERRIDES
    try:
        cfg = load_engine_config()
        overrides = cfg.get("exploration_overrides") or {} if isinstance(cfg, dict) else {}
        valid: Dict[str, Any] = {}
        for sym, data in overrides.items():
            if not isinstance(data, dict) or not data.get("enabled"):
                continue
            exp_at = data.get("expires_at")
            if exp_at:
                try:
                    exp_dt = datetime.fromisoformat(exp_at.replace("Z", "+00:00"))
                    if now_dt > exp_dt:
                        continue
                except Exception:
                    pass
            valid[sym.upper()] = data
        _EXPL_OVERRIDES = valid
    except Exception:
        _EXPL_OVERRIDES = {}
    return _EXPL_OVERRIDES


def _load_observation_cfg() -> Dict[str, Any]:
    """Load observation mode configuration with defaults and per-asset overrides."""
    default_cfg = {
        "observation_regimes": ["trend_up", "trend_down"],
        "edge_floor": -0.0005,
        "size_factor": 0.5,
        "max_open_trades": 3,
    }
    
    if not OBS_CFG_PATH.exists():
        return {
            "default": default_cfg,
            "asset_overrides": {}
        }
    
    try:
        raw = json.loads(OBS_CFG_PATH.read_text())
        # Handle legacy format (flat structure)
        if "default" not in raw and "asset_overrides" not in raw:
            # Legacy format: convert to new structure
            return {
                "default": {
                    "observation_regimes": raw.get("observation_regimes", default_cfg["observation_regimes"]),
                    "edge_floor": raw.get("edge_floor", default_cfg["edge_floor"]),
                    "size_factor": raw.get("size_factor", default_cfg["size_factor"]),
                    "max_open_trades": raw.get("max_open_trades", default_cfg["max_open_trades"]),
                },
                "asset_overrides": {}
            }
        # New format: ensure defaults exist
        if "default" not in raw:
            raw["default"] = default_cfg
        if "asset_overrides" not in raw:
            raw["asset_overrides"] = {}
        return raw
    except Exception:
        # Fallback to defaults on parse error
        return {
            "default": default_cfg,
            "asset_overrides": {}
        }


def _get_observation_config(symbol: str, regime: str) -> Dict[str, Any]:
    """
    Get effective observation config for a specific symbol.
    
    Merges default config with asset-specific overrides.
    Returns a dict with: observation_regimes, edge_floor, size_factor, max_open_trades
    """
    full_cfg = _load_observation_cfg()
    default_cfg = full_cfg.get("default", {
        "observation_regimes": ["trend_up", "trend_down"],
        "edge_floor": -0.0005,
        "size_factor": 0.5,
        "max_open_trades": 3,
    })
    asset_overrides = full_cfg.get("asset_overrides", {})
    
    # Start with default config
    effective_cfg = default_cfg.copy()
    
    symbol_key = symbol.upper()
    # Apply asset-specific override if exists
    if symbol_key in asset_overrides:
        asset_override = asset_overrides[symbol_key]
        effective_cfg.update(asset_override)

    loosen_flags = _load_loosen_flags()
    asset_flags = loosen_flags.get(symbol_key)
    if asset_flags and asset_flags.get("soft_mode"):
        soft_edge = asset_flags.get("edge_floor_soft")
        soft_conf = asset_flags.get("min_conf_soft")
        if isinstance(soft_edge, (int, float)):
            effective_cfg["edge_floor"] = float(soft_edge)
        if isinstance(soft_conf, (int, float)):
            effective_cfg["min_conf"] = float(soft_conf)
    
    return effective_cfg

# Treat anything smaller than this as noise (~5 bps = 0.05%)
# NOTE: pct is stored as fractional return (e.g., 0.0993 = +9.93%), NOT percentage
# So 0.05% = 0.0005 in fractional units
SCRATCH_THRESHOLD = 0.0005  # 0.05% in fractional return units (5 bps)


def _is_effectively_zero(x: float, eps: float = 1e-9) -> bool:
    try:
        return abs(float(x)) <= eps
    except Exception:
        return False

ACCOUNTING_DEFAULT = {"taker_fee_bps": 6.0, "slip_bps": 2.0}


def _load_accounting():
    cfg = CONFIG / "risk.yaml"
    if cfg.exists():
        try:
            data = yaml.safe_load(cfg.read_text()) or {}
            accounting = data.get("accounting", {})
            return {
                "taker_fee_bps": float(accounting.get("taker_fee_bps", ACCOUNTING_DEFAULT["taker_fee_bps"])),
                "slip_bps": float(accounting.get("slip_bps", ACCOUNTING_DEFAULT["slip_bps"])),
            }
        except Exception:
            pass
    return ACCOUNTING_DEFAULT.copy()

ACCOUNTING = _load_accounting()

def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# Trade writer interface for backtest isolation
# In live/paper mode: None (uses _append_trade to main ledger)
# In backtest mode: BacktestTradeWriter instance (writes to backtest directory)
TRADE_WRITER = None


class TradeWriter:
    """Abstract base class for trade writers."""
    def write_open(self, event: dict) -> None:
        """Write an open event."""
        raise NotImplementedError
    
    def write_close(self, event: dict) -> None:
        """Write a close event."""
        raise NotImplementedError


def set_trade_writer(writer: Optional[TradeWriter]) -> None:
    """Set the global trade writer (used by backtest harness)."""
    global TRADE_WRITER
    TRADE_WRITER = writer


def _get_trades_path() -> Path:
    """Get the trades.jsonl path, respecting CHLOE_TRADES_PATH env var if set."""
    default_path = REPORTS / "trades.jsonl"
    env_path = os.getenv("CHLOE_TRADES_PATH")
    if env_path:
        return Path(env_path)
    return default_path


def log_trade_event(event: dict):
    """
    Single source of truth for writing trade events to trades.jsonl.
    Ensures all events include symbol, timeframe, and version marker.
    """
    path = _get_trades_path()
    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)
    
    # Tag with version marker
    event.setdefault("logger_version", "trades_v2")
    
    # Ensure symbol and timeframe are present (warn if missing but don't fail)
    if "symbol" not in event:
        event["symbol"] = "UNKNOWN"
    if "timeframe" not in event:
        event["timeframe"] = _get_default_timeframe()
    
    with path.open("a") as f:
        f.write(json.dumps(event) + "\n")


def _append_trade(event: dict):
    """Legacy wrapper - redirects to log_trade_event for backward compatibility."""
    log_trade_event(event)


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r") as f:
            return json.load(f)
    except Exception:
        return {}


def _load_promotions() -> Dict[str, Any]:
    """
    Load core promotions from config/engine_config.json, filtering expired ones.
    """
    promos: Dict[str, Any] = {}
    cfg = load_engine_config()
    entries = cfg.get("core_promotions") or {} if isinstance(cfg, dict) else {}
    now = datetime.now(timezone.utc)
    for sym, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        if not entry.get("enabled"):
            continue
        exp = entry.get("expires_at")
        if exp:
            try:
                if datetime.fromisoformat(exp) <= now:
                    continue
            except Exception:
                pass
        promos[str(sym).upper()] = entry
    return promos


def _lookup_conf_edge(confidence: float) -> float:
    conf_map_path = CONFIG / "confidence_map.json"
    cm = _load_json(conf_map_path)
    if not cm:
        return 0.0
    bucket = int(min(9, max(0, int(confidence * 10))))
    info = cm.get(str(bucket), {})
    return float(info.get("expected_return", 0.0))


def _lookup_regime_strength(regime: str) -> Dict[str, float]:
    strengths_path = REPORTS / "research" / "strategy_strength.json"
    strengths = _load_json(strengths_path)
    info = strengths.get(regime, {})
    return {
        "strength": float(info.get("strength", 0.0)),
        "edge": float(info.get("edge", 0.0)),
        "wN": float(info.get("weighted_count", 0.0)),
    }


def _lookup_pa_multiplier() -> float:
    """
    Optional: adjust notional by PA state.
    We assume gates.yaml contains profit_amplifier config.
    """
    gates_path = CONFIG / "gates.yaml"
    if not gates_path.exists():
        return 1.0
    try:
        gates = yaml.safe_load(gates_path.read_text()) or {}
        pa = gates.get("profit_amplifier", {})
        if not pa or not pa.get("enabled", True):
            return 1.0
        # Very simple: use multiplier; you can make this more complex later
        return float(pa.get("multiplier", 1.0))
    except Exception:
        return 1.0


def gate_and_size_trade(
    symbol: str,
    side: str,
    regime: str,
    confidence: float,
    base_notional: float,
    volatility_norm: float,
    direction: Optional[float] = None,
) -> Tuple[bool, float, str]:
    """
    Central quant gate + sizing:

      - runs sanity gates
      - optionally blocks low-edge trades
      - uses PF-local & risk autoscaler via compute_quant_position_size
      - applies Profit Amplifier multiplier
      - checks live mode safety (requires confirmation if enabled)

    Returns: (allow_trade, final_notional, reason)
    """
    # 0) Live mode safety check
    try:
        from engine_alpha.config.config_loader import load_wallet_config
        wallet_cfg = load_wallet_config()
        
        if wallet_cfg.active_wallet_mode == "real" and wallet_cfg.confirm_live_trade:
            return False, 0.0, (
                "Live mode ON but confirm_live_trade=true; "
                "trade blocked until confirmation mechanism is implemented. "
                "Set confirm_live_trade=false to disable (after thorough testing)."
            )
        
        # Check notional limits in live mode
        if wallet_cfg.active_wallet_mode == "real":
            if base_notional > wallet_cfg.max_live_notional_per_trade_usd:
                return False, 0.0, (
                    f"Base notional ${base_notional:.2f} exceeds "
                    f"max_live_notional_per_trade_usd ${wallet_cfg.max_live_notional_per_trade_usd:.2f}"
                )
    except ImportError:
        # If config_loader not available, skip this check (backward compat)
        pass
    
    # 0.5) Chop-blocker: Block Tier3 symbols in indecision/chop/noisy microstructure regimes
    try:
        from engine_alpha.core.regime_filters import should_block_tier3_in_chop
        if should_block_tier3_in_chop(symbol):
            micro_regime = None
            try:
                from engine_alpha.core.regime_filters import get_symbol_micro_regime
                micro_regime = get_symbol_micro_regime(symbol)
            except Exception:
                pass
            return False, 0.0, (
                f"CHOP-BLOCKER: skipping open for {symbol} in micro_regime={micro_regime} (tier3)"
            )
    except ImportError:
        # If regime_filters not available, skip this check (backward compat)
        pass
    
    # 1) Check max open trades for observation regimes
    # Get symbol-specific observation config
    obs_cfg_effective = _get_observation_config(symbol, regime)
    obs_regimes = set(obs_cfg_effective.get("observation_regimes", ["trend_up", "trend_down"]))
    max_open_trades = int(obs_cfg_effective.get("max_open_trades", 3))
    
    # gate_and_size_trade does not receive timeframe; use default for observation checks
    tf_used = _get_default_timeframe()
    if regime in obs_regimes:
        # Count current open positions in observation regimes
        try:
            # Check position for this specific symbol
            pos = get_open_position(symbol=symbol, timeframe=tf_used)
            if pos and pos.get("dir") != 0:
                # Check if we're already at max observation trades
                # For now, simple check: if any position is open, count it
                # TODO: Could enhance to count only observation regime positions
                current_open = 1 if pos.get("dir") != 0 else 0
                if current_open >= max_open_trades:
                    return False, 0.0, (
                        f"Blocked: max_open_trades={max_open_trades} reached for observation regimes"
                    )
        except Exception:
            # If position check fails, allow trade (fail open)
            pass
    
    # 2) global sanity gate
    sanity = check_sanity(regime=regime, confidence=confidence)
    if not sanity.allow_trade:
        return False, 0.0, f"Blocked by sanity gate: {sanity.reason}"

    # 3) Check exploration mode (can bypass confidence but not regime/edge)
    expl_cfg = _load_exploration_config()
    exploration_pass = False
    
    if expl_cfg.get("enabled", False) and direction is not None:
        # Check if regime is allowed for exploration
        allowed_regime = (
            (regime == "trend_up" and expl_cfg.get("allow_in_trend_up", True)) or
            (regime == "trend_down" and expl_cfg.get("allow_in_trend_down", True)) or
            (regime == "high_vol" and expl_cfg.get("allow_in_high_vol", True)) or
            (regime == "chop" and expl_cfg.get("allow_in_chop", False))
        )
        
        min_direction = expl_cfg.get("min_direction", 0.10)
        if allowed_regime and abs(direction) > min_direction:
            exploration_pass = True
    
    # 4) local edge check: if conf bucket edge + regime edge is strongly negative, skip
    conf_edge = _lookup_conf_edge(confidence)
    reg_strength = _lookup_regime_strength(regime)
    regime_edge = reg_strength["edge"]

    combined_edge = (conf_edge + regime_edge) / 2.0

    # Regime-aware edge gating: observation regimes get relaxed rules (configurable)
    # Use symbol-specific observation config (already loaded above)
    obs_regimes = set(obs_cfg_effective.get("observation_regimes", ["trend_up", "trend_down"]))
    obs_edge_floor = float(obs_cfg_effective.get("edge_floor", -0.0005))
    obs_size_factor = float(obs_cfg_effective.get("size_factor", 0.5))
    obs_min_conf = obs_cfg_effective.get("min_conf", None)  # Optional: lower confidence threshold for observation
    
    size_factor = 1.0
    gate_reason = ""
    
    # Edge gate: must pass regardless of exploration mode
    if regime in obs_regimes:
        # For observation regimes, allow mildly negative edge but not terrible ones
        # Exploration can bypass confidence but NOT edge
        if combined_edge < obs_edge_floor:
            return False, 0.0, (
                f"Blocked: combined edge {combined_edge:.5f} in observational regime={regime} "
                f"(conf_edge={conf_edge:.5f}, regime_edge={regime_edge:.5f}, floor={obs_edge_floor:.5f})"
            )
        else:
            # Slightly negative but allowed as a small "learning" trade
            size_factor = obs_size_factor
            gate_reason = (
                f"Observational trade allowed in {regime} with combined_edge={combined_edge:.5f} "
                f"(conf_edge={conf_edge:.5f}, regime_edge={regime_edge:.5f}), size_factor={size_factor:.2f}"
            )
            if obs_min_conf is not None:
                gate_reason += f", min_conf={obs_min_conf:.2f}"
    else:
        # For high_vol (and any other future "real" regimes), be strict
        if combined_edge < -0.0005:
            return False, 0.0, (
                f"Blocked: combined edge {combined_edge:.5f} "
                f"(conf_edge={conf_edge:.5f}, regime_edge={regime_edge:.5f})"
            )
        gate_reason = (
            f"Trade allowed in {regime} with combined_edge={combined_edge:.5f} "
            f"(conf_edge={conf_edge:.5f}, regime_edge={regime_edge:.5f})"
        )
    
    # Confidence gate: can be bypassed by exploration mode
    confidence_pass = True  # Default: pass (exploration can bypass)
    if not exploration_pass:
        # Only check confidence if NOT in exploration mode
        if regime in obs_regimes:
            if obs_min_conf is not None and confidence < obs_min_conf:
                confidence_pass = False
                return False, 0.0, (
                    f"Blocked: confidence {confidence:.4f} below observation min_conf={obs_min_conf:.4f} "
                    f"for regime={regime} (symbol={symbol})"
                )
    
    # Update gate_reason to indicate exploration_pass if applicable
    if exploration_pass:
        gate_reason += f", exploration_pass=True (bypassed confidence gate)"
        # Cap size for exploration trades
        expl_max_size = expl_cfg.get("max_size_factor", 0.15)
        size_factor = min(size_factor, expl_max_size)

    # 5) compute quant position size from PF_local & risk
    notional = compute_quant_position_size(
        base_notional=base_notional,
        regime=regime,
        confidence=confidence,
        volatility_norm=volatility_norm,
    )

    # 6) apply Profit Amplifier multiplier and observation/exploration size factor
    pa_mult = _lookup_pa_multiplier()
    final_notional = notional * pa_mult * size_factor
    
    # Final gate check: exploration_pass can bypass confidence but not regime/edge
    # At this point, regime and edge have passed, so we can allow the trade

    return True, final_notional, (
        f"{gate_reason}, sanity={sanity.severity}, "
        f"pa_mult={pa_mult:.2f}, size_factor={size_factor:.2f}, "
        f"base_notional={base_notional:.4f}, final_notional={final_notional:.4f}"
    )


def open_if_allowed(
    final_dir: int,
    final_conf: float,
    entry_min_conf: float,
    risk_mult: float = 1.0,
    regime: str = None,
    risk_band: str = None,
    symbol: str = "ETHUSDT",
    timeframe: str = None,
    strategy: str = None,
    exploration_pass: bool = False,
    disable_softening: bool = False,
    signal_dict: Dict[str, Any] = None,
    persist_position: bool = True,
    trade_kind_override: Optional[str] = None,
) -> bool:
    """
    PAPER-only open. final_dir ∈ {-1,0,+1}. Blocks duplicate direction.
    Logs an 'open' event including 'risk_mult', 'regime', and 'risk_band' for observability.
    """
    if DEBUG_SIGNALS:
        print(f"OPEN_IF_ALLOWED: symbol={symbol} risk_mult={risk_mult} type={type(risk_mult)}")
    if timeframe is None:
        timeframe = _get_default_timeframe()
    timeframe = timeframe.lower()
    symbol = symbol.upper()
    capital_mode = None
    try:
        cp = _load_json(REPORTS / "risk" / "capital_protection.json")
        capital_mode = (cp.get("global") or {}).get("mode") or cp.get("mode")
    except Exception:
        capital_mode = None
    review_bootstrap = {}
    try:
        cfg_rb = load_engine_config()
        review_bootstrap = cfg_rb.get("review_bootstrap") or {}
    except Exception:
        review_bootstrap = {}
    rb_enabled = bool(review_bootstrap.get("enabled", False))
    rb_rmult_cap = float(review_bootstrap.get("risk_mult_cap", 0.02))
    
    trade_kind = trade_kind_override or ("exploration" if exploration_pass else "normal")
    if strategy == "recovery_v2":
        trade_kind = "recovery_v2"
    lane = "exploration" if trade_kind == "exploration" else ("recovery" if trade_kind == "recovery_v2" else "core")

    if DEBUG_SIGNALS:
        print(
            f"OPEN-LOG ATTEMPT symbol={symbol} tf={timeframe} trade_kind={trade_kind} "
            f"dir={final_dir} conf={final_conf:.4f} entry_min={entry_min_conf:.4f}"
        )
    
    # Symbol policy + quarantine (single source of truth)
    try:
        symbol_states = load_symbol_states()
        sym_policy_map = symbol_states.get("symbols") if isinstance(symbol_states, dict) else {}
        sym_policy = sym_policy_map.get(symbol, {}) if isinstance(sym_policy_map, dict) else {}
        caps_by_lane = sym_policy.get("caps_by_lane") or {}
        lane_caps = caps_by_lane.get(lane, {})

        if sym_policy.get("quarantined"):
            if DEBUG_SIGNALS:
                print(f"ENTRY-DEBUG: {symbol} blocked by symbol_policy quarantine")
            return False

        # Enforce lane permissions even in review/unknown modes; default block if missing policy
        allow_map = {
            "core": sym_policy.get("allow_core", False),
            "exploration": sym_policy.get("allow_exploration", False),
            "recovery": sym_policy.get("allow_recovery", False),
        }
        if not allow_map.get(lane, False):
            if DEBUG_SIGNALS:
                print(
                    f"POLICY_BLOCK_OPEN symbol={symbol} lane={lane} "
                    f"allow_core={allow_map.get('core')} allow_expl={allow_map.get('exploration')} "
                    f"allow_rec={allow_map.get('recovery')}"
                )
            return False

        # Apply per-lane risk cap
        if isinstance(lane_caps, dict) and "risk_mult_cap" in lane_caps:
            try:
                risk_cap = float(lane_caps.get("risk_mult_cap", risk_mult))
                risk_mult = min(risk_mult, risk_cap)
            except Exception:
                pass

        # Exploration risk-off cap: keep exploration alive at tiny size in risk-off modes
        if trade_kind == "exploration" and capital_mode in {"halt_new_entries", "de_risk"}:
            risk_mult = min(risk_mult, 0.05)
            if DEBUG_SIGNALS:
                print(f"EXPL_RISKOFF_CAP symbol={symbol} risk_mult={risk_mult:.3f} capital_mode={capital_mode}")

        # Review bootstrap: force exploration only, cap risk, block recovery/core
        if capital_mode == "review" and rb_enabled:
            if lane == "recovery":
                if DEBUG_SIGNALS:
                    print(f"POLICY_BLOCK_OPEN symbol={symbol} lane=recovery review_mode_block=True")
                return False
            if lane != "exploration":
                lane = "exploration"
                trade_kind = "exploration"
            risk_mult = min(risk_mult, rb_rmult_cap)
            if DEBUG_SIGNALS:
                print(f"EXPL_REVIEW_CAP symbol={symbol} risk_mult={risk_mult:.3f} capital_mode={capital_mode}")

        # Review mode: block core/recovery opens; exploration allowed at micro size
        if capital_mode == "review":
            if lane != "exploration":
                if DEBUG_SIGNALS:
                    print(f"POLICY_BLOCK_OPEN symbol={symbol} lane={lane} review_mode_block=True")
                return False
            risk_mult = min(risk_mult, 0.02)
            if DEBUG_SIGNALS:
                print(f"EXPL_REVIEW_CAP symbol={symbol} risk_mult={risk_mult:.3f} capital_mode={capital_mode}")

        # Apply per-lane max positions to exploration cap if present
        if trade_kind == "exploration" and isinstance(lane_caps, dict) and "max_positions" in lane_caps:
            try:
                sym_cap = int(lane_caps.get("max_positions"))
                if sym_cap > 0:
                    effective_exploration_cap = sym_cap if effective_exploration_cap is None else min(effective_exploration_cap, sym_cap)
            except Exception:
                pass

    except Exception:
        # Fail-safe: do not block on policy load error
        pass

    # Phase 5g: Check quarantine (legacy path; retain for compatibility)
    try:
        quarantine_path = REPORTS / "risk" / "quarantine.json"
        if quarantine_path.exists():
            quarantine = _load_json(quarantine_path)
            if quarantine.get("enabled", False):
                blocked_symbols = quarantine.get("blocked_symbols", [])
                if symbol in blocked_symbols:
                    if DEBUG_SIGNALS:
                        print(f"ENTRY-DEBUG: {symbol} blocked by quarantine (loss contributor)")
                    return False
    except Exception:
        # Fail-safe: if quarantine check fails, allow (don't block on error)
        pass
    
    # Core promotions (Option A safe caps)
    try:
        promos = _load_promotions()
        promo = promos.get(symbol.upper())
        if promo:
            # enforce risk multiplier cap
            promo_risk_cap = promo.get("risk_mult_cap", 0.25)
            risk_mult = min(risk_mult, promo_risk_cap)
            # enforce max_positions=1 for promoted symbols (for normal trades)
            if not exploration_pass:
                pos = get_open_position(symbol=symbol, timeframe=timeframe)
                if pos and pos.get("dir") != 0:
                    if DEBUG_SIGNALS:
                        print(f"ENTRY-DEBUG: promotion active for {symbol}, position exists; max_positions=1 enforced")
                    return False
            if DEBUG_SIGNALS:
                print(f"ENTRY-DEBUG: promotion active for {symbol}, risk_mult capped to {risk_mult}")
    except Exception:
        # Never block entry on promotion load error
        pass

    # Exploration accelerator overrides (cooldown + cap) apply only to exploration_pass trades
    exploration_override = None
    effective_exploration_cap = None
    exploration_cooldown_s = None

    if exploration_pass:
        overrides = _load_exploration_overrides()
        exploration_override = overrides.get(symbol.upper())

        # Load base exploration lane config
        base_cap = 1
        try:
            cfg = load_engine_config()
            lane_cfg = cfg.get("exploration_lane", {}) or {} if isinstance(cfg, dict) else {}
            base_cap = int(lane_cfg.get("max_open_per_symbol", 1))
        except Exception:
            base_cap = 1

        delta_cap = 0
        if exploration_override:
            try:
                delta_cap = int(exploration_override.get("exploration_cap_delta", 0))
            except Exception:
                delta_cap = 0
            delta_cap = max(0, min(1, delta_cap))

        effective_exploration_cap = max(1, base_cap + delta_cap)

        # Cooldown check (override cooldown, floored)
        if exploration_override:
            try:
                cd = int(exploration_override.get("cooldown_seconds", EXPL_COOLDOWN_FLOOR))
            except Exception:
                cd = EXPL_COOLDOWN_FLOOR
            exploration_cooldown_s = max(EXPL_COOLDOWN_FLOOR, cd)
        else:
            exploration_cooldown_s = None

        if exploration_cooldown_s:
            last_ts = _EXPL_COOLDOWN_CACHE.get(symbol.upper())
            if last_ts:
                elapsed = (datetime.now(timezone.utc) - last_ts).total_seconds()
                if elapsed < exploration_cooldown_s:
                    if DEBUG_SIGNALS:
                        print(f"ENTRY-DEBUG: exploration cooldown active for {symbol} ({elapsed:.0f}s<{exploration_cooldown_s}s)")
                    return False

    # Calculate effective entry confidence threshold
    effective_entry_conf = entry_min_conf
    
    # Apply paper tuning overrides (PAPER mode only)
    mode = os.getenv("MODE", "PAPER").upper()
    if mode == "PAPER":
        try:
            from engine_alpha.tuning.paper_tuning_overrides import get_symbol_override
            override = get_symbol_override(symbol)
            if override:
                conf_delta = override.get("conf_min_delta", 0.0)
                effective_entry_conf += conf_delta
                # Clamp to safe bounds
                effective_entry_conf = max(0.0, min(1.0, effective_entry_conf))
                if DEBUG_SIGNALS and abs(conf_delta) > 0.001:
                    print(
                        f"PAPER-TUNING: {symbol} entry_min_conf adjusted by {conf_delta:+.3f} "
                        f"({entry_min_conf:.3f} -> {effective_entry_conf:.3f})"
                    )
        except Exception:
            # Silently ignore override errors (safety first)
            pass
    
    # Soften threshold in defensive mode (risk_mult < 1.0)
    # Phase 5H.2 Conservative Tightening: Disable softening for Recovery V2 (disable_softening=True)
    if risk_mult < 1.0 and not disable_softening:
        effective_entry_conf = max(0.0, effective_entry_conf - 0.07)
        print(
            f"ENTRY-DEBUG: defensive mode (risk_mult={risk_mult}) "
            f"entry_min_conf={entry_min_conf:.2f} -> softened={effective_entry_conf:.2f} "
            f"final_conf={final_conf:.2f}"
        )
    
    if final_dir == 0:
        return False
    
    # Unified entry gate check (all modes use same logic)
    if final_conf < effective_entry_conf:
        if DEBUG_SIGNALS:
            print(f"ENTRY-DEBUG: reject open dir={final_dir} final_conf={final_conf:.2f} "
                  f"< effective_entry_conf={effective_entry_conf:.2f} (risk_mult={risk_mult})")
        return False
    
    # For exploration trades, allow opening even if there's a normal position open
    # (exploration lane caps handle concurrency) - but respect exploration cap override
    if not exploration_pass:
        pos = get_open_position(symbol=symbol, timeframe=timeframe)
        if pos and pos.get("dir") == final_dir:
            # duplicate-direction guard (only for normal trades)
            return False
    else:
        pos = get_open_position(symbol=symbol, timeframe=timeframe)
        if pos and pos.get("dir") != 0 and effective_exploration_cap is not None and effective_exploration_cap <= 1:
            if DEBUG_SIGNALS:
                print(f"ENTRY-DEBUG: exploration cap reached for {symbol} (cap={effective_exploration_cap})")
            return False
    
    # Get entry price from latest bar for price-based PnL calculation
    # This ensures entry_px is set correctly for both live and backtest
    entry_price = None
    try:
        from engine_alpha.data import live_prices
        # Use the symbol/timeframe from the function signature, not hardcoded
        # get_live_ohlcv returns (rows, meta) tuple
        ohlcv_rows, ohlcv_meta = live_prices.get_live_ohlcv(symbol=symbol, timeframe=timeframe, limit=1)
        if ohlcv_rows and len(ohlcv_rows) > 0:
            entry_price = ohlcv_rows[-1].get("close")
            if entry_price is None:
                # Try alternative field names
                entry_price = ohlcv_rows[-1].get("c") or ohlcv_rows[-1].get("close_price")
    except Exception as e:
        # Log the error for debugging but continue with fallback
        if os.getenv("DEBUG_SIGNALS") == "1":
            print(f"ENTRY-PRICE-DEBUG: Failed to fetch entry price: {e}")
    
    # Use fallback only if we couldn't get a real price
    # CRITICAL: Never use 1.0 as fallback - it corrupts PnL/PF calculations
    # Instead, try PriceFeedHealth as a more robust fallback, or fail the open
    if entry_price is None or entry_price <= 0:
        try:
            from engine_alpha.data.price_feed_health import get_latest_price
            price, price_meta = get_latest_price(symbol)
            if price is not None and price > 0:
                entry_price = price
                if os.getenv("DEBUG_SIGNALS") == "1":
                    print(f"ENTRY-PRICE-DEBUG: Using PriceFeedHealth fallback: {price}")
            else:
                # Still no price - this is a real problem, don't open with fake price
                if os.getenv("DEBUG_SIGNALS") == "1":
                    print(f"ENTRY-PRICE-DEBUG: No price available from any source, blocking open")
                # Return False to block the open rather than using fake price
                return False
        except Exception as e:
            if os.getenv("DEBUG_SIGNALS") == "1":
                print(f"ENTRY-PRICE-DEBUG: PriceFeedHealth fallback also failed: {e}")
            # Still no price - block the open
            return False
    
    ts_now = _now()

    # Persist state: in-memory (always) + on-disk (optional)
    position_payload = {
        "dir": final_dir,
        "entry_px": float(entry_price),
        "bars_open": 0,
        "symbol": symbol,
        "timeframe": timeframe,
        "trade_kind": trade_kind,
        "last_ts": ts_now,
        "entry_ts": ts_now,
        "risk_mult": risk_mult,
        "regime": regime,  # Store regime for exit evaluation
        "regime_at_entry": regime,  # For debugging
    }
    # Recovery lane should not touch global position_state.json or shared in-memory slots
    if trade_kind != "recovery_v2":
        set_position(position_payload, symbol=symbol, timeframe=timeframe)
        if persist_position:
            try:
                from engine_alpha.loop.position_manager import set_live_position as _set_live_position

                _set_live_position(position_payload, symbol=symbol, timeframe=timeframe)
            except Exception:
                # Never block an open because persistence failed
                if DEBUG_SIGNALS:
                    print(f"OPEN-LOG WARN: failed to persist live position for {symbol} {timeframe}")
    
    # Diagnostic: try open result
    if os.getenv("BACKTEST_ANALYSIS") == "1":
        print(f"ANALYSIS-TRY-OPEN: dir={final_dir} conf={final_conf:.2f} result=True")
    
    # Build open event with regime and risk info for observability
    open_event = {
        "ts": ts_now,
        "type": "open",
        "symbol": symbol,  # Always include symbol
        "timeframe": timeframe,  # Always include timeframe
        "dir": final_dir,
        "pct": 0.0,
        "risk_mult": float(risk_mult),
        "entry_px": float(entry_price),  # Store entry price for debugging/analysis
        "trade_kind": trade_kind,  # Tag exploration vs normal trades
        "logger_version": "trades_v2",  # Version marker
    }
    if regime is not None:
        open_event["regime"] = str(regime)
    if risk_band is not None:
        open_event["risk_band"] = str(risk_band)
    if strategy is not None:
        open_event["strategy"] = str(strategy)  # Strategy name for per-strategy PF tracking
    
    # Phase 3.1: Add PCI snapshot if available (logging only, no behavior change)
    if signal_dict is not None:
        try:
            from engine_alpha.loop.pci_logging import extract_pci_snapshot
            # Check config for feature inclusion (default: False)
            include_features = False
            try:
                cfg = load_engine_config()
                pci_cfg = cfg.get("pre_candle", {}) if isinstance(cfg, dict) else {}
                include_features = pci_cfg.get("log_features", False)
            except Exception:
                pass
            
            pci_snapshot = extract_pci_snapshot(signal_dict, include_features=include_features)
            if pci_snapshot:
                open_event["pre_candle"] = pci_snapshot
        except Exception:
            # PCI extraction failure shouldn't break trade logging
            pass
    
    # CRITICAL: Runtime assertion to prevent entry_px=1.0 or <=0 corruption
    entry_px_val = open_event.get("entry_px")
    if entry_px_val is None or entry_px_val <= 0 or entry_px_val == 1.0:
        error_msg = (
            f"BLOCKED OPEN: Invalid entry_px={entry_px_val} for {symbol} {timeframe}. "
            f"This would corrupt PnL/PF calculations. Blocking open."
        )
        print(f"❌ {error_msg}")
        if os.getenv("DEBUG_SIGNALS") == "1":
            import traceback
            traceback.print_stack()
        return False
    
    allow_recovery_open_global = os.getenv("ALLOW_RECOVERY_OPEN_GLOBAL", "0") == "1"
    should_write_global_open = (
        TRADE_WRITER is not None
        or trade_kind != "recovery_v2"
        or allow_recovery_open_global
    )

    # Write via TRADE_WRITER if set (backtest), otherwise use default _append_trade (live/paper)
    if TRADE_WRITER is not None:
        TRADE_WRITER.write_open(open_event)
    elif should_write_global_open:
        _append_trade(open_event)
    elif DEBUG_SIGNALS:
        print(f"OPEN-LOG SKIP-GLOBAL symbol={symbol} tf={timeframe} trade_kind={trade_kind} (ALLOW_RECOVERY_OPEN_GLOBAL=0)")

    if DEBUG_SIGNALS:
        print(
            f"OPEN-LOG EXECUTED symbol={symbol} tf={timeframe} trade_kind={trade_kind} "
            f"dir={final_dir} entry_px={entry_price:.6f} risk_mult={risk_mult:.3f}"
        )

    # Record exploration cooldown timestamp only for exploration trades
    if exploration_pass:
        _EXPL_COOLDOWN_CACHE[symbol.upper()] = datetime.now(timezone.utc)
    return True


# PnL pct calculation summary (for close_now):
# - pct = price-based: (exit_price - entry_price) / entry_price * dir (fractional return, e.g., 0.0993 = +9.93%)
# - uses entry_price from position and exit_price from latest bar (or provided)
# - falls back to 0.0 if entry_price or exit_price is missing
# - dir = +1 for LONG, -1 for SHORT (multiplies price change by direction)
def close_now(
    pct: float = None,
    entry_price: float = None,
    exit_price: float = None,
    dir: int = None,
    exit_reason: str = None,
    exit_label: str = None,
    reason: str = None,
    exit_conf: float = None,
    regime: str = None,
    risk_band: str = None,
    risk_mult: float = None,
    max_adverse_pct: float = None,
    symbol: str = None,
    timeframe: str = None,
    **kwargs,
) -> None:
    """
    PAPER close with price-based P&L calculation.
    If entry_price and exit_price are provided, computes pct from actual price movement.
    Falls back to provided pct parameter if prices are missing.
    
    Extended fields for reflection analysis:
    - exit_reason: "tp", "sl", "reverse", "decay", "drop", "manual", etc.
    - exit_conf: final_conf at exit time
    - regime: market regime at exit ("chop", "trend", "high_vol")
    - risk_band: risk band at exit ("A", "B", "C")
    - risk_mult: risk multiplier at exit
    - max_adverse_pct: maximum adverse excursion during trade (optional)
    """
    from engine_alpha.loop.position_manager import clear_position, get_open_position, get_live_position

    # Allow callers to pass these via kwargs too (defensive: avoid surprises)
    if exit_price is None and "exit_price" in kwargs:
        exit_price = kwargs.get("exit_price")
    if entry_price is None and "entry_price" in kwargs:
        entry_price = kwargs.get("entry_price")
    exit_px_source = kwargs.get("exit_px_source")
    
    # === GUARD: no active position, prevent ghost closes ===
    pos = get_live_position(symbol=symbol, timeframe=timeframe) or get_open_position(symbol=symbol, timeframe=timeframe)
    # Fallback to position_state.json if not found in live caches
    if pos is None or not pos.get("dir"):
        try:
            from engine_alpha.loop.position_manager import load_position_state
            payload = load_position_state()
            positions = payload.get("positions", {}) if isinstance(payload, dict) else {}
            # symbol_val/timeframe_val not yet normalized here; use requested args
            sym_key = (symbol or "UNKNOWN").upper()
            tf_key = (timeframe or _get_default_timeframe()).lower()
            key = f"{sym_key}_{tf_key}"
            ps_pos = positions.get(key)
            if isinstance(ps_pos, dict) and (ps_pos.get("dir") or 0) != 0:
                pos = {
                    "dir": int(ps_pos.get("dir", 0)),
                    "bars_open": ps_pos.get("bars_open"),
                    "entry_px": ps_pos.get("entry_px"),
                    "last_ts": ps_pos.get("last_ts"),
                    "entry_ts": ps_pos.get("entry_ts"),
                    "risk_mult": ps_pos.get("risk_mult"),
                    "symbol": ps_pos.get("symbol") or sym_key,
                    "timeframe": ps_pos.get("timeframe") or tf_key,
                    "trade_kind": ps_pos.get("trade_kind", "normal"),
                }
        except Exception:
            pos = pos  # keep as None if fallback fails
    symbol_val = (symbol or (pos or {}).get("symbol") or "UNKNOWN")
    timeframe_val = (timeframe or (pos or {}).get("timeframe") or _get_default_timeframe())
    symbol_val = symbol_val.upper()
    timeframe_val = timeframe_val.lower()

    # Alias: allow reason/exit_label as kwarg for convenience
    if reason and not exit_reason:
        exit_reason = reason
    if exit_label and not exit_reason:
        exit_reason = exit_label

    # Unwrap common caller patterns for prices:
    # - exit_price=(px, meta) where meta has source_used
    # - entry_price=(px, meta) (rare, but handle)
    if isinstance(exit_price, (tuple, list)):
        try:
            px0 = exit_price[0] if len(exit_price) >= 1 else None
            meta0 = exit_price[1] if len(exit_price) >= 2 else None
            if px0 is not None:
                exit_price = float(px0)
            if exit_px_source is None and isinstance(meta0, dict):
                exit_px_source = (
                    meta0.get("source_used")
                    or meta0.get("source")
                    or meta0.get("provider")
                    or "price_feed_health"
                )
        except Exception:
            pass
    if isinstance(entry_price, (tuple, list)):
        try:
            px0 = entry_price[0] if len(entry_price) >= 1 else None
            if px0 is not None:
                entry_price = float(px0)
        except Exception:
            pass

    # If caller provided an exit price but no source, record that truthfully.
    if exit_price is not None and exit_px_source is None:
        exit_px_source = "caller_provided_exit_price"

    if DEBUG_SIGNALS:
        print(
            f"CLOSE-LOG ATTEMPT symbol={symbol_val} tf={timeframe_val} "
            f"trade_kind={(pos or {}).get('trade_kind', 'unknown')} exit_reason={exit_reason} pct_in={pct}"
        )

    if pos is None or not pos.get("dir") or pos.get("dir") == 0:
        if DEBUG_SIGNALS:
            print(f"IGNORED_GHOST_CLOSE symbol={symbol_val} tf={timeframe_val}")
        return None
    
    # Defensive check: ensure position symbol matches requested symbol
    pos_symbol = pos.get("symbol")
    if pos_symbol and pos_symbol.upper() != symbol_val.upper():
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(
            f"CROSS-SYMBOL MISMATCH in close_now: requested_symbol={symbol_val}, pos.symbol={pos_symbol}, "
            f"entry_px={pos.get('entry_px')}, exit_px={exit_price}"
        )
        # Don't close wrong symbol's position
        return None
    
    # Get trade_kind from position for close event
    trade_kind = pos.get("trade_kind", "normal")
    # =======================================================
    
    computed_pct = None
    bootstrap_timeout = False
    if exit_reason and isinstance(exit_reason, str):
        if "review_bootstrap_timeout" in exit_reason:
            bootstrap_timeout = True
    if entry_price is not None and exit_price is not None and dir is not None and entry_price > 0:
        # Price-based calculation: (exit - entry) / entry * dir
        # pct is stored as fractional return (e.g., 0.0993 = +9.93%), NOT percentage
        raw_change = (exit_price - entry_price) / entry_price
        signed_change = raw_change * dir  # dir = +1 for LONG, -1 for SHORT
        computed_pct = signed_change  # Store as fractional return, not percentage
    
    # Fallback: try to get prices from position if not provided
    if computed_pct is None:
        pos = get_live_position(symbol=symbol, timeframe=timeframe) or get_open_position(symbol=symbol, timeframe=timeframe)
        if pos and isinstance(pos, dict):
            # Defensive check: ensure position symbol matches
            pos_symbol = pos.get("symbol")
            if pos_symbol and pos_symbol.upper() != symbol_val.upper():
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(
                    f"CROSS-SYMBOL MISMATCH in close_now fallback: requested_symbol={symbol_val}, "
                    f"pos.symbol={pos_symbol}, entry_px={pos.get('entry_px')}"
                )
            else:
                entry_from_pos = pos.get("entry_px")
                dir_from_pos = pos.get("dir")
                if entry_from_pos is not None and exit_price is not None and dir_from_pos is not None:
                    try:
                        entry_val = float(entry_from_pos)
                        dir_val = int(dir_from_pos)
                        if entry_val > 0:
                            raw_change = (exit_price - entry_val) / entry_val
                            signed_change = raw_change * dir_val
                            computed_pct = signed_change  # Store as fractional return, not percentage
                    except (TypeError, ValueError):
                        pass
                # Fill exit_price from position if still missing
                if exit_price is None:
                    try:
                        exit_price = pos.get("exit_px") or pos.get("entry_px")
                        if exit_price is not None:
                            exit_px_source = exit_px_source or "position_fallback"
                    except Exception:
                        pass
                # Fill risk_mult from position if missing
                if risk_mult is None:
                    try:
                        risk_mult = float(pos.get("risk_mult"))
                    except Exception:
                        pass
    
    # For timeout closes, always prefer price_feed_health MTM price first
    if exit_price is None and (bootstrap_timeout or "timeout" in str(exit_reason or "")):
        print(f"TIMEOUT_CLOSE_MTM_ATTEMPT symbol={symbol_val} exit_reason={exit_reason} bootstrap_timeout={bootstrap_timeout}")
        try:
            from engine_alpha.data.price_feed_health import get_latest_trade_price

            px, meta = get_latest_trade_price(symbol_val)
            print(f"TIMEOUT_CLOSE_MTM_FETCH symbol={symbol_val} px={px} meta={meta}")
            if px is not None and px > 0:
                exit_price = float(px)
                # Properly unwrap meta source
                source_used = meta.get("source_used") or meta.get("source") or "price_feed_health"
                exit_px_source = exit_px_source or source_used

                # Log MTM close for transparency
                if entry_price is not None and dir is not None:
                    pct = ((exit_price - entry_price) / entry_price) * dir
                    print(f"TIMEOUT_MTM_CLOSE symbol={symbol_val} entry={entry_price:.4f} exit={exit_price:.4f} pct={pct:.4f} source={exit_px_source}")
            else:
                exit_px_source = exit_px_source or "price_feed_health:unavailable"
                print(f"TIMEOUT_CLOSE_NO_PRICE symbol={symbol_val} using fallback")
        except Exception as e:
            exit_px_source = exit_px_source or f"price_feed_health:exception:{str(e)}"
            print(f"TIMEOUT_CLOSE_EXCEPTION symbol={symbol_val} error={e}")

    if exit_price is None:
        try:
            from engine_alpha.data import live_prices
            ohlcv_rows, _ = live_prices.get_live_ohlcv(symbol=symbol_val, timeframe=timeframe_val, limit=1)
            if ohlcv_rows and len(ohlcv_rows) > 0:
                px = ohlcv_rows[-1].get("close") or ohlcv_rows[-1].get("c")
                if px and px > 0:
                    exit_price = float(px)
                    exit_px_source = exit_px_source or "current_price"
        except Exception:
            pass
    if exit_price is None:
        # Fallback: try reflection packet market price
        try:
            from pathlib import Path
            refl = Path(__file__).resolve().parents[2] / "reports" / "reflection_packet.json"
            if refl.exists():
                pkt = json.loads(refl.read_text())
                px = pkt.get("market", {}).get("price")
                if px and px > 0:
                    exit_price = float(px)
                    exit_px_source = exit_px_source or "reflection_price"
        except Exception:
            pass
    if exit_price is None:
        if entry_price is not None:
            exit_price = entry_price
            exit_px_source = exit_px_source or "entry_fallback"
        elif pos and isinstance(pos, dict):
            exit_price = pos.get("entry_px")
            exit_px_source = exit_px_source or "position_entry"

    if exit_px_source is None:
        exit_px_source = exit_px_source or "unknown"

    # If still missing pct, try to compute using final exit_price and entry/dir from pos
    if computed_pct is None:
        entry_for_calc = entry_price
        dir_for_calc = dir
        if entry_for_calc is None and pos and isinstance(pos, dict):
            entry_for_calc = pos.get("entry_px")
        if dir_for_calc is None and pos and isinstance(pos, dict):
            dir_for_calc = pos.get("dir")
        try:
            if entry_for_calc is not None and exit_price is not None and dir_for_calc is not None:
                entry_val = float(entry_for_calc)
                exit_val = float(exit_price)
                dir_val_calc = int(dir_for_calc)
                if entry_val > 0:
                    computed_pct = (exit_val - entry_val) / entry_val * dir_val_calc
                    if os.getenv("DEBUG_SIGNALS") == "1":
                        if bootstrap_timeout:
                            print(
                                f"BOOTSTRAP_MTM_CLOSE symbol={symbol_val} entry={entry_val:.6f} exit={exit_val:.6f} "
                                f"dir={dir_val_calc} pct={computed_pct:.6f} source={exit_px_source or 'unknown'}"
                            )
        except Exception:
            pass

    # Final fallback: use provided pct or 0.0
    if computed_pct is None:
        if pct is not None:
            computed_pct = float(pct)
        else:
            computed_pct = 0.0
            print("PNL-DEBUG: missing entry_price/exit_price, pct=0.0 fallback")

    # ------------------------------------------------------------------
    # Sanity checks: detect unrealistic exit prices (data glitches)
    # ------------------------------------------------------------------
    # Check for suspiciously large moves (> 20% absolute) or exit_price anomalies
    MAX_REASONABLE_PCT = 0.20  # 20% absolute move (fractional return)
    SUSPICIOUS_PRICE_RATIO_LOW = 0.05  # Exit price < 5% of entry price is suspicious
    SUSPICIOUS_PRICE_RATIO_HIGH = 20.0  # Exit price > 20x entry price is suspicious
    MAX_ABSOLUTE_PCT = 2.0  # ±200% absolute cap - anything beyond is definitely wrong
    
    if entry_price is not None and exit_price is not None and symbol_val:
        entry_val = float(entry_price)
        exit_val = float(exit_price)
        if entry_val > 0:
            price_ratio = exit_val / entry_val
            
            # Check for extreme price ratios (likely cross-symbol mixing)
            if price_ratio < SUSPICIOUS_PRICE_RATIO_LOW or price_ratio > SUSPICIOUS_PRICE_RATIO_HIGH:
                # Exit price is suspiciously different from entry (likely data glitch or cross-symbol mixing)
                print(
                    f"⚠️  SANITY-CHECK: Suspicious exit price detected! "
                    f"symbol={symbol_val}, entry_px={entry_val:.2f}, exit_px={exit_val:.2f}, ratio={price_ratio:.6f}. "
                    f"Clamping pct to 0.0 (treating as invalid trade - likely cross-symbol price mixing)."
                )
                computed_pct = 0.0  # Treat as invalid/no-op trade
            elif abs(computed_pct) > MAX_ABSOLUTE_PCT:
                # Extremely large move (> ±200%) - definitely wrong, clamp it
                print(
                    f"⚠️  SANITY-CHECK: Extreme move detected (>±200%): pct={computed_pct:.6f} "
                    f"({computed_pct*100:.2f}%), symbol={symbol_val}, entry_px={entry_val:.2f}, exit_px={exit_val:.2f}. "
                    f"Clamping to 0.0 (likely cross-symbol price mixing or data glitch)."
                )
                computed_pct = 0.0  # Clamp extreme values
            elif abs(computed_pct) > MAX_REASONABLE_PCT:
                # Very large move (> 20%) - log warning but don't clamp (could be legitimate)
                print(
                    f"⚠️  SANITY-CHECK: Large move detected: pct={computed_pct:.6f} "
                    f"({computed_pct*100:.2f}%), symbol={symbol_val}, entry_px={entry_val:.2f}, exit_px={exit_val:.2f}. "
                    f"This may be legitimate, but verify data integrity."
                )
    
    # ------------------------------------------------------------------
    # Scratch classification - AIRTIGHT LOGIC
    # ------------------------------------------------------------------
    # 1) Any *effectively zero* move (same entry/exit price) is scratch.
    # 2) Any move smaller than SCRATCH_THRESHOLD on SL / drop / decay / TP
    #    is also scratch. This prevents micro-TPs from polluting PF.
    #
    # NOTE: computed_pct is stored as fractional return (e.g., 0.0993 = +9.93%)
    # SCRATCH_THRESHOLD = 0.0005 means 0.05% = 5 bps in fractional units
    is_scratch = False
    if exit_reason is not None:
        exit_reason_str = str(exit_reason).lower()
        
        # Check for zero moves (handles both 0.0 and -0.0)
        is_zero_move = _is_effectively_zero(computed_pct)
        
        # Check for small moves (micro-moves below threshold)
        small_move = abs(computed_pct) < SCRATCH_THRESHOLD
        
        # Determine if this exit reason is scratchable
        scratchable = exit_reason_str in {"sl", "drop", "decay", "tp"}
        
        # Scratch if: zero move OR (small move AND scratchable exit reason)
        is_scratch = is_zero_move or (small_move and scratchable)
    
    # Build close event with extended fields
    entry_px_log = entry_price if entry_price is not None else pos.get("entry_px") if pos else None
    ts_now = _now()
    close_event = {
        "ts": ts_now,
        "type": "close",
        "symbol": symbol_val if symbol_val else "UNKNOWN",  # Always include symbol
        "timeframe": timeframe_val if timeframe_val else _get_default_timeframe(),  # Always include timeframe
        "pct": computed_pct,
        "fee_bps": ACCOUNTING["taker_fee_bps"] * 2.0,
        "slip_bps": ACCOUNTING["slip_bps"],
        "is_scratch": bool(is_scratch),  # Phase 1: scratch classification
        "entry_px": float(entry_px_log) if entry_px_log is not None else None,  # Store for debugging
        "exit_px": float(exit_price) if exit_price is not None else None,  # Store for debugging
        "exit_px_source": exit_px_source,
        "trade_kind": trade_kind,  # Tag exploration vs normal trades
        "logger_version": "trades_v2",  # Version marker
    }
    
    # Add extended fields if provided (for reflection analysis)
    exit_reason_val = "unknown" if exit_reason is None else str(exit_reason)
    exit_label_val = str(exit_label) if exit_label is not None else exit_reason_val
    close_event["exit_reason"] = exit_reason_val
    close_event["exit_label"] = exit_label_val
    if exit_conf is not None:
        try:
            close_event["exit_conf"] = float(exit_conf)
        except (TypeError, ValueError):
            close_event["exit_conf"] = 0.0  # Default if invalid
    else:
        close_event["exit_conf"] = 0.0  # Default if missing
    
    if regime is not None:
        close_event["regime"] = str(regime)
    else:
        close_event["regime"] = "unknown"  # Default if missing
    
    if risk_band is not None:
        close_event["risk_band"] = str(risk_band)
    else:
        close_event["risk_band"] = "N/A"  # Default if missing
    
    if risk_mult is None and pos is not None:
        try:
            risk_mult = float(pos.get("risk_mult"))
        except Exception:
            risk_mult = None
    if risk_mult is not None:
        try:
            close_event["risk_mult"] = float(risk_mult)
        except (TypeError, ValueError):
            close_event["risk_mult"] = 1.0  # Default if invalid
    else:
        close_event["risk_mult"] = 1.0  # Default if missing
    
    if max_adverse_pct is not None:
        try:
            close_event["max_adverse_pct"] = float(max_adverse_pct)
        except (TypeError, ValueError):
            pass
    
    # Write via TRADE_WRITER if set (backtest), otherwise use default _append_trade (live/paper)
    if TRADE_WRITER is not None:
        TRADE_WRITER.write_close(close_event)
    else:
        _append_trade(close_event)

    # Resolve counterfactual for this closed trade
    try:
        from engine_alpha.reflect.counterfactual_ledger import resolve_trade_counterfactual
        resolve_trade_counterfactual(
            symbol=symbol_val,
            exit_ts=ts_now,
            actual_pnl_pct=computed_pct,
            exit_reason=exit_reason_val,
            regime_at_exit=close_event.get("regime", "unknown")
        )
    except Exception as e:
        # Counterfactual resolution failure shouldn't break trading
        if DEBUG_SIGNALS:
            print(f"COUNTERFACTUAL_RESOLUTION_ERROR: {e}")

    if DEBUG_SIGNALS:
        print(
            f"CLOSE-LOG EXECUTED symbol={symbol_val} tf={timeframe_val} "
            f"trade_kind={trade_kind} pct={computed_pct:.6f} exit_reason={close_event.get('exit_reason')}"
        )

    # Persist state: clear both live and in-memory position records for this symbol/timeframe
    try:
        if (trade_kind or "").lower() != "recovery_v2":
            from engine_alpha.loop.position_manager import clear_live_position as _clear_live_position

            _clear_live_position(symbol=symbol_val, timeframe=timeframe_val)
    except Exception:
        # Never let persistence failures break trading
        pass
    clear_position(symbol=symbol_val, timeframe=timeframe_val)
