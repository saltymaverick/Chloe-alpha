from __future__ import annotations
import json, math
from pathlib import Path
from typing import List, Dict

# Project-root aware paths
ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"
REPORTS.mkdir(parents=True, exist_ok=True)

def pf_from_trades(trades: List[Dict]) -> float:
    wins = sum(float(t.get("pct", 0.0)) for t in trades if float(t.get("pct", 0.0)) > 0)
    losses = -sum(float(t.get("pct", 0.0)) for t in trades if float(t.get("pct", 0.0)) < 0)
    if losses <= 0:
        return float("inf") if wins > 0 else 0.0
    return wins / losses

def _read_trades(trades_path: Path) -> List[Dict]:
    out = []
    if trades_path.exists():
        for line in trades_path.read_text().splitlines():
            line = line.strip()
            if not line: continue
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out

def update_pf_reports(trades_path: Path, out_pf_local: Path, out_pf_live: Path, window: int = 150) -> None:
    trades = _read_trades(trades_path)
    # live: all trades; local: last N
    pf_live = pf_from_trades(trades) if trades else 0.0
    pf_local = pf_from_trades(trades[-window:]) if trades else 0.0

    out_pf_live.write_text(json.dumps({"pf": pf_live, "count": len(trades)}, indent=2))
    out_pf_local.write_text(json.dumps({"pf": pf_local, "window": window, "count": min(len(trades), window)}, indent=2))

def main():
    trades_path = REPORTS / "trades.jsonl"
    update_pf_reports(trades_path, REPORTS / "pf_local.json", REPORTS / "pf_live.json")

if __name__ == "__main__":
    main()
