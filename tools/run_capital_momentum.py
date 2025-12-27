"""
Run Capital Momentum Engine (Phase 4c)
--------------------------------------

Usage:
    python3 -m tools.run_capital_momentum
"""

from __future__ import annotations

from engine_alpha.risk.capital_momentum import compute_capital_momentum


def main() -> None:
    snapshot = compute_capital_momentum()
    meta = snapshot.get("meta", {})
    syms = snapshot.get("symbols", {})

    print("CAPITAL MOMENTUM (Phase 4c - PAPER ONLY)")
    print("======================================================================")
    print(f"Engine      : {meta.get('engine')}")
    print(f"Version     : {meta.get('version')}")
    print(f"GeneratedAt : {meta.get('generated_at')}")
    print(f"Alpha       : {meta.get('alpha')}")
    print()
    if not syms:
        print("No capital momentum data (no capital plan yet).")
        print("======================================================================")
        return

    print("Symbol  RawW   Smoothed  Delta   Churn")
    print("----------------------------------------------------------------------")
    items = sorted(
        syms.items(),
        key=lambda kv: kv[1].get("smoothed_weight", 0.0),
        reverse=True,
    )
    for sym, info in items:
        rw = info.get("raw_weight", 0.0)
        sw = info.get("smoothed_weight", 0.0)
        delta = info.get("delta", 0.0)
        churn = info.get("churn_tag") or "—"
        print(f"{sym:7s} {rw:5.3f}  {sw:7.3f}  {delta:6.3f}  {churn}")

    print("======================================================================")


if __name__ == "__main__":
    main()

