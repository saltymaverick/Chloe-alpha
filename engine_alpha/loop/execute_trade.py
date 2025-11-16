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


def open_if_allowed(final_dir: int, final_conf: float, entry_min_conf: float, risk_mult: float = 1.0) -> bool:
    """
    PAPER-only open. final_dir ∈ {-1,0,+1}. Blocks duplicate direction.
    Logs an 'open' event including 'risk_mult'.
    """
    if final_dir == 0 or final_conf < entry_min_conf:
        return False
    pos = get_open_position()
    if pos and pos.get("dir") == final_dir:
        # duplicate-direction guard
        return False
    # PAPER fill proxy (we're not pricing yet)
    set_position({"dir": final_dir, "entry_px": 1.0, "bars_open": 0})
    _append_trade({
        "ts": _now(),
        "type": "open",
        "dir": final_dir,
        "pct": 0.0,
        "risk_mult": float(risk_mult)
    })
    return True


# PnL pct calculation summary (for close_now):
# - pct = price-based: (exit_price - entry_price) / entry_price * dir * 100.0
# - uses entry_price from position and exit_price from latest bar (or provided)
# - falls back to 0.0 if entry_price or exit_price is missing
# - dir = +1 for LONG, -1 for SHORT (multiplies price change by direction)
def close_now(pct: float = None, entry_price: float = None, exit_price: float = None, dir: int = None) -> None:
    """
    PAPER close with price-based P&L calculation.
    If entry_price and exit_price are provided, computes pct from actual price movement.
    Falls back to provided pct parameter if prices are missing.
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
    
    _append_trade({
        "ts": _now(),
        "type": "close",
        "pct": computed_pct,
        "fee_bps": ACCOUNTING["taker_fee_bps"] * 2.0,
        "slip_bps": ACCOUNTING["slip_bps"]
    })
    clear_position()
