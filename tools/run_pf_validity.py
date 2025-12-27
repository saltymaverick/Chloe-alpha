"""
Run PF Validity Engine (Phase 4d)
---------------------------------

Usage:
    python3 -m tools.run_pf_validity
"""

from __future__ import annotations

from engine_alpha.risk.pf_validity import compute_pf_validity


def main() -> None:
    snap = compute_pf_validity()
    meta = snap.get("meta", {})
    syms = snap.get("symbols", {})

    print("PF VALIDITY (Phase 4d - PAPER ONLY)")
    print("======================================================================")
    print(f"Engine      : {meta.get('engine')}")
    print(f"GeneratedAt : {meta.get('generated_at')}")
    print()
    print("Symbol  Score  Label      Sample  Stable  Drift  Exec  Consist")
    print("----------------------------------------------------------------------")
    for sym, info in sorted(
        syms.items(),
        key=lambda kv: kv[1].get("validity_score", 0.0),
        reverse=True,
    ):
        score = info.get("validity_score", 0.0)
        label = info.get("label", "")
        comps = info.get("components", {})
        ss = comps.get("sample_size_score", 0.0)
        st = comps.get("stability_score", 0.0)
        ds = comps.get("drift_score", 0.0)
        es = comps.get("exec_score", 0.0)
        cs = comps.get("consistency_score", 0.0)
        print(
            f"{sym:7s} {score:5.3f}  {label:9s} {ss:5.2f}  {st:5.2f}  "
            f"{ds:5.2f}  {es:5.2f}  {cs:7.2f}"
        )
    print("======================================================================")


if __name__ == "__main__":
    main()
