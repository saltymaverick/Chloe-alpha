"""
Run Live-Candidate Scan (Phase 4b)
----------------------------------

Convenience CLI wrapper for live_candidate_scanner.

Usage:
    python3 -m tools.run_live_candidate_scan
"""

from __future__ import annotations

from engine_alpha.risk.live_candidate_scanner import compute_live_candidates


def main() -> None:
    snapshot = compute_live_candidates()
    meta = snapshot.get("meta", {})
    symbols = snapshot.get("symbols", {})

    print("LIVE-CANDIDATE READINESS (Phase 4b - PAPER ONLY)")
    print("======================================================================")
    print(f"Engine      : {meta.get('engine')}")
    print(f"Version     : {meta.get('version')}")
    print(f"GeneratedAt : {meta.get('generated_at')}")
    print()
    print("Symbol  Tier  PF30   PF7   Drift      ExecQL   Policy   Block  Score  ReadyNow LiveReady")
    print("----------------------------------------------------------------------")

    items = sorted(
        symbols.items(),
        key=lambda kv: kv[1].get("score", 0.0),
        reverse=True,
    )

    for sym, info in items:
        tier = info.get("tier") or "—"
        pf30 = info.get("pf_30d")
        pf7 = info.get("pf_7d")
        drift = info.get("drift") or "—"
        execql = info.get("execql") or "—"
        policy_level = info.get("policy_level") or "—"
        blocked = info.get("blocked")
        score = info.get("score", 0.0)
        ready_now = info.get("ready_now")
        live_ready = info.get("live_ready")

        pf30_str = f"{pf30:.3f}" if isinstance(pf30, (int, float)) else "—"
        pf7_str = f"{pf7:.3f}" if isinstance(pf7, (int, float)) else "—"

        print(
            f"{sym:7s} {tier:4s} {pf30_str:>5} {pf7_str:>5} "
            f"{drift:10s} {execql:8s} {policy_level:7s} "
            f"{'Y' if blocked else 'N':5s} {score:6.3f} "
            f"{'Y' if ready_now else 'N':8s} {'Y' if live_ready else 'N':9s}"
        )

    print("======================================================================")


if __name__ == "__main__":
    main()
