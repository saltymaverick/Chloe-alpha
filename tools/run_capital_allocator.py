"""
CLI wrapper for Capital Allocator V1 (Phase 4a).

Usage:
    python3 -m tools.run_capital_allocator

This is ADVISORY-ONLY and PAPER-SAFE.
It recomputes the capital plan and prints a brief summary.
"""

from __future__ import annotations

from engine_alpha.risk.capital_allocator import compute_capital_plan


def main() -> None:
    plan = compute_capital_plan()
    meta = plan.get("meta", {})
    syms = plan.get("symbols", {})
    top = plan.get("marksman_top5", [])

    print("CAPITAL ALLOCATOR V1 (Marksman Edition)")
    print("======================================================================")
    print(f"Engine      : {meta.get('engine')}")
    print(f"Version     : {meta.get('version')}")
    print(f"GeneratedAt : {meta.get('generated_at')}")
    print()
    print("Top 5 Symbols by Score:")
    print("----------------------------------------------------------------------")
    for s in top:
        sym_alloc = syms.get(s, {})
        w = sym_alloc.get("weight")
        score = sym_alloc.get("score")
        tier = sym_alloc.get("tier")
        print(f"{s:8s}  score={score:.4f}  weight={w:.4f}  tier={tier}")
    print()
    print("Full plan written to: reports/risk/capital_plan.json")
    print("======================================================================")


if __name__ == "__main__":
    main()

