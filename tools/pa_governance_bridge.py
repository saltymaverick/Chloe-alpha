import json
from pathlib import Path
from engine_alpha.core.pa_policy import evaluate_policy
R=Path("reports")
def J(n): p=R/n; 
J=lambda n: (lambda p: json.loads(p.read_text()) if p.exists() and p.read_text().strip() else None)(R/n)
gov = J("governance_snapshot.json") or {}
rec = (gov.get("rec") or gov.get("recommendation") or "").upper()
sci = gov.get("sci")
pf  = J("pf_local_live.json") or J("pf_local_norm.json") or {}
pfw = pf.get("pf"); cnt = pf.get("count",0)
# loss streak (simple)
ls = 0
try:
    tail=(R/"trades.jsonl").read_text().strip().splitlines()[-200:] if (R/"trades.jsonl").exists() else []
    for ln in reversed(tail):
        o=json.loads(ln)
        if o.get("type")!="close": continue
        if float(o.get("pct",0))<=0: ls+=1
        else: break
except: pass
orch = J("orchestrator_snapshot.json") or {"inputs":{}}
pol = evaluate_policy(rec, pfw, cnt, ls, sci)
orch["inputs"]=orch.get("inputs",{}); orch["inputs"].update({"rec":rec,"sci":sci,"pf_weighted":pfw,"count":cnt,"loss_streak":ls})
orch["policy"]={"allow_opens": pol["allow_opens"], "allow_pa": pol["allow_pa"]}
orch["notes"]="paper-only; "+pol["reason"]
(R/"orchestrator_snapshot.json").write_text(json.dumps(orch, indent=2))
print(json.dumps({"rec":rec,"sci":sci,"pf_weighted":pfw,"count":cnt,"loss_streak":ls,"policy":orch["policy"],"reason":pol["reason"]}, indent=2))
