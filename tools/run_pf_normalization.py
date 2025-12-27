"""
Run PF Normalization Engine (Phase 4e)
--------------------------------------

Usage:
    python3 -m tools.run_pf_normalization
"""

from __future__ import annotations

from engine_alpha.risk.pf_normalization import compute_pf_normalized


def main() -> None:
    snap = compute_pf_normalized()
    meta = snap.get("meta", {})
    syms = snap.get("symbols", {})

    print("PF NORMALIZATION (Phase 4e - PAPER ONLY)")
    print("======================================================================")
    print(f"Engine          : {meta.get('engine')}")
    print(f"GeneratedAt     : {meta.get('generated_at')}")
    print(f"Slippage factor : {meta.get('slippage_factor')}")
    print()
    print("Symbol  Validity  RawShort  NormShort  RawLong  NormLong")
    print("----------------------------------------------------------------------")

    def _fmt(x):
        return f"{x:.2f}" if isinstance(x, (int, float)) else "—"

    for sym, info in sorted(
        syms.items(),
        key=lambda kv: kv[1].get("validity_score", 0.0),
        reverse=True,
    ):
        v = info.get("validity_score", 0.0)
        rs = info.get("short_exp_pf_raw")
        ns = info.get("short_exp_pf_norm")
        rl = info.get("long_exp_pf_raw")
        nl = info.get("long_exp_pf_norm")

        print(
            f"{sym:7s} {v:8.3f}  {_fmt(rs):>7}   {_fmt(ns):>8}   {_fmt(rl):>7}   {_fmt(nl):>8}"
        )

    print("======================================================================")


if __name__ == "__main__":
    main()
