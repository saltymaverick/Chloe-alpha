from __future__ import annotations
import json, time, yaml
from engine_alpha.core.paths import REPORTS, CONFIG
from engine_alpha.loop.position_manager import get_open_position, set_position

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


def _append_trade(event: dict):
    path = REPORTS / "trades.jsonl"
    with path.open("a") as f:
        f.write(json.dumps(event) + "\n")


def open_if_allowed(final_dir: int, final_conf: float, entry_min_conf: float, risk_mult: float = 1.0,
                     regime: str = None, risk_band: str = None) -> bool:
    """
    PAPER-only open. final_dir ∈ {-1,0,+1}. Blocks duplicate direction.
    Logs an 'open' event including 'risk_mult', 'regime', and 'risk_band' for observability.
    """
    # Calculate effective entry confidence threshold
    effective_entry_conf = entry_min_conf
    
    # Soften threshold in defensive mode (risk_mult < 1.0)
    if risk_mult < 1.0:
        effective_entry_conf = max(0.0, entry_min_conf - 0.07)
        print(
            f"ENTRY-DEBUG: defensive mode (risk_mult={risk_mult}) "
            f"entry_min_conf={entry_min_conf:.4f} -> softened={effective_entry_conf:.4f} "
            f"final_conf={final_conf:.4f}"
        )
    
    if final_dir == 0:
        return False
    
    if final_conf < effective_entry_conf:
        print(f"ENTRY-DEBUG: reject open dir={final_dir} final_conf={final_conf:.4f} "
              f"< effective_entry_conf={effective_entry_conf:.4f} (risk_mult={risk_mult})")
        return False
    
    pos = get_open_position()
    if pos and pos.get("dir") == final_dir:
        # duplicate-direction guard
        return False
    # PAPER fill proxy (we're not pricing yet)
    set_position({"dir": final_dir, "entry_px": 1.0, "bars_open": 0})
    
    # Build open event with regime and risk info for observability
    open_event = {
        "ts": _now(),
        "type": "open",
        "dir": final_dir,
        "pct": 0.0,
        "risk_mult": float(risk_mult)
    }
    if regime is not None:
        open_event["regime"] = str(regime)
    if risk_band is not None:
        open_event["risk_band"] = str(risk_band)
    
    _append_trade(open_event)
    return True


# PnL pct calculation summary (for close_now):
# - pct = price-based: (exit_price - entry_price) / entry_price * dir * 100.0
# - uses entry_price from position and exit_price from latest bar (or provided)
# - falls back to 0.0 if entry_price or exit_price is missing
# - dir = +1 for LONG, -1 for SHORT (multiplies price change by direction)
def close_now(
    pct: float = None,
    entry_price: float = None,
    exit_price: float = None,
    dir: int = None,
    exit_reason: str = None,
    exit_conf: float = None,
    regime: str = None,
    risk_band: str = None,
    risk_mult: float = None,
    max_adverse_pct: float = None,
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
    
    computed_pct = None
    if entry_price is not None and exit_price is not None and dir is not None and entry_price > 0:
        # Price-based calculation: (exit - entry) / entry * dir * 100
        raw_change = (exit_price - entry_price) / entry_price
        signed_change = raw_change * dir  # dir = +1 for LONG, -1 for SHORT
        computed_pct = signed_change * 100.0
    
    # Fallback: try to get prices from position if not provided
    if computed_pct is None:
        pos = get_live_position() or get_open_position()
        if pos and isinstance(pos, dict):
            entry_from_pos = pos.get("entry_px")
            dir_from_pos = pos.get("dir")
            if entry_from_pos is not None and exit_price is not None and dir_from_pos is not None:
                try:
                    entry_val = float(entry_from_pos)
                    dir_val = int(dir_from_pos)
                    if entry_val > 0:
                        raw_change = (exit_price - entry_val) / entry_val
                        signed_change = raw_change * dir_val
                        computed_pct = signed_change * 100.0
                except (TypeError, ValueError):
                    pass
    
    # Final fallback: use provided pct or 0.0
    if computed_pct is None:
        if pct is not None:
            computed_pct = float(pct)
        else:
            computed_pct = 0.0
            print("PNL-DEBUG: missing entry_price/exit_price, pct=0.0 fallback")
    
    # Build close event with extended fields
    close_event = {
        "ts": _now(),
        "type": "close",
        "pct": computed_pct,
        "fee_bps": ACCOUNTING["taker_fee_bps"] * 2.0,
        "slip_bps": ACCOUNTING["slip_bps"]
    }
    
    # Add extended fields if provided (for reflection analysis)
    if exit_reason is not None:
        close_event["exit_reason"] = str(exit_reason)
    if exit_conf is not None:
        try:
            close_event["exit_conf"] = float(exit_conf)
        except (TypeError, ValueError):
            pass
    if regime is not None:
        close_event["regime"] = str(regime)
    if risk_band is not None:
        close_event["risk_band"] = str(risk_band)
    if risk_mult is not None:
        try:
            close_event["risk_mult"] = float(risk_mult)
        except (TypeError, ValueError):
            pass
    if max_adverse_pct is not None:
        try:
            close_event["max_adverse_pct"] = float(max_adverse_pct)
        except (TypeError, ValueError):
            pass
    
    _append_trade(close_event)
    clear_position()
