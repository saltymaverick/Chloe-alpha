#!/usr/bin/env python3
from engine_alpha.core.config_loader import load_engine_config
from datetime import datetime


def main() -> int:
    cfg = load_engine_config(strict=True)
    # Validate core_promotions schema (can be empty)
    promos = cfg.get("core_promotions", {})
    if not isinstance(promos, dict):
        raise SystemExit("core_promotions must be a dict if present")
    for sym, entry in promos.items():
        if not isinstance(entry, dict):
            raise SystemExit(f"core_promotions[{sym}] must be a dict")
        if "enabled" not in entry:
            raise SystemExit(f"core_promotions[{sym}] missing enabled")
        if "expires_at" not in entry:
            raise SystemExit(f"core_promotions[{sym}] missing expires_at")
        if "max_positions" not in entry:
            raise SystemExit(f"core_promotions[{sym}] missing max_positions")
        if "risk_mult_cap" not in entry:
            raise SystemExit(f"core_promotions[{sym}] missing risk_mult_cap")
        if "reason" not in entry:
            raise SystemExit(f"core_promotions[{sym}] missing reason")
        try:
            datetime.fromisoformat(str(entry["expires_at"]).replace("Z", "+00:00"))
        except Exception:
            raise SystemExit(f"core_promotions[{sym}].expires_at invalid ISO format")
        try:
            int(entry["max_positions"])
            float(entry["risk_mult_cap"])
        except Exception:
            raise SystemExit(f"core_promotions[{sym}] max_positions/risk_mult_cap invalid types")
    print("OK: engine_config.json loaded keys:", list(cfg.keys())[:30])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

