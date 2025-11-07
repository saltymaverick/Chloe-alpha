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


def close_now(pct: float) -> None:
    """
    PAPER close with provided pct P&L proxy.
    """
    from engine_alpha.loop.position_manager import clear_position
    _append_trade({
        "ts": _now(),
        "type": "close",
        "pct": float(pct),
        "fee_bps": ACCOUNTING["taker_fee_bps"] * 2.0,
        "slip_bps": ACCOUNTING["slip_bps"]
    })
    clear_position()
