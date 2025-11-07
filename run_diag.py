from engine_alpha.loop.diagnostic_loop import run_batch
from engine_alpha.core.paths import REPORTS
from engine_alpha.reflect.trade_analysis import update_pf_reports
import json, time

if __name__ == "__main__":
    run_batch(25)
    (REPORTS / "loop_health.json").write_text(json.dumps({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": "runner"
    }, indent=2))
    update_pf_reports(REPORTS / "trades.jsonl", REPORTS / "pf_local.json", REPORTS / "pf_live.json")
    print("✅ wrote reports to:", REPORTS)
