from __future__ import annotations
from engine_alpha.evolve.promotion_manager import run_once
from engine_alpha.core.paths import REPORTS

if __name__ == "__main__":
    summary = run_once()
    print("Promotion summary:", summary)
    p = REPORTS / "promotion_proposals.jsonl"
    if p.exists():
        print("Last proposals:")
        lines = p.read_text().splitlines()[-5:]
        for ln in lines:
            print(ln)
    else:
        print("No proposals yet")
