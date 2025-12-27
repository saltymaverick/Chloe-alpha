from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRADES_PATH = ROOT / "reports" / "trades.jsonl"
BACKUP_PATH = TRADES_PATH.with_suffix(".jsonl.bak")


def _load_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text().splitlines()


def sanitize_trades() -> dict[str, int]:
    lines = _load_lines(TRADES_PATH)
    opens: dict[tuple[str, str], dict[str, float | None]] = {}

    fixed_exit_px = 0
    fixed_risk_mult = 0
    total_close = 0

    out_lines: list[str] = []

    for line in lines:
        try:
            obj = json.loads(line)
        except Exception:
            continue

        t = (obj.get("type") or "").lower()
        sym = (obj.get("symbol") or "").upper()
        tf = (obj.get("timeframe") or "").lower()
        key = (sym, tf)

        if t == "open":
            opens[key] = {
                "risk_mult": obj.get("risk_mult"),
                "entry_px": obj.get("entry_px"),
            }
            out_lines.append(json.dumps(obj))
            continue

        if t == "close":
            total_close += 1
            modified = False

            # Fill exit_px if missing/None
            exit_px = obj.get("exit_px")
            if exit_px in (None, ""):
                candidate_px = obj.get("entry_px")
                if candidate_px is None and key in opens:
                    candidate_px = opens[key].get("entry_px")
                if candidate_px is not None:
                    try:
                        obj["exit_px"] = float(candidate_px)
                        modified = True
                        fixed_exit_px += 1
                    except Exception:
                        pass

            # Normalize risk_mult using matching open if the close has missing/default value
            rm = obj.get("risk_mult")
            if (rm is None or rm == 1.0) and key in opens:
                open_rm = opens[key].get("risk_mult")
                try:
                    if open_rm is not None:
                        obj["risk_mult"] = float(open_rm)
                        modified = True
                        fixed_risk_mult += 1
                except Exception:
                    pass

            out_lines.append(json.dumps(obj))
            continue

        # passthrough anything else
        out_lines.append(json.dumps(obj))

    # Write backup then replace
    TRADES_PATH.parent.mkdir(parents=True, exist_ok=True)
    if TRADES_PATH.exists():
        shutil.copyfile(TRADES_PATH, BACKUP_PATH)

    tmp = TRADES_PATH.with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(out_lines) + ("\n" if out_lines else ""))
    tmp.replace(TRADES_PATH)

    return {
        "fixed_exit_px": fixed_exit_px,
        "fixed_risk_mult": fixed_risk_mult,
        "total_close_seen": total_close,
        "backup": str(BACKUP_PATH),
    }


if __name__ == "__main__":
    result = sanitize_trades()
    print(json.dumps(result, indent=2))

