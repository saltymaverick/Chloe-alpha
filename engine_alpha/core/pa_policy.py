from __future__ import annotations
from typing import Dict, Any

DEFAULTS = {"min_sample":30,"arm_pf":1.02,"arm_count":50,"hold_pf":1.00,"disarm_pf":0.98,"max_loss_streak":7}

def evaluate_policy(rec: str|None, pf_weighted: float|None, count: int|None, loss_streak: int|None, sci: float|None) -> Dict[str, Any]:
    out = {"allow_opens": True, "allow_pa": False, "reason": "", "inputs":{"rec":rec,"pf_weighted":pf_weighted,"count":count,"loss_streak":loss_streak,"sci":sci}}
    try:
        r=(rec or "").upper(); cnt=int(count or 0); ls=int(loss_streak or 0)
        pf=None if (pf_weighted is None or pf_weighted==float("inf")) else float(pf_weighted); rsn=[]
        if cnt<DEFAULTS["min_sample"] or pf is None: rsn.append("insufficient sample")
        else:
            if pf<DEFAULTS["disarm_pf"]: rsn.append(f"pf<{DEFAULTS['disarm_pf']}")
            if ls>=DEFAULTS["max_loss_streak"]: rsn.append(f"loss_streak>={DEFAULTS['max_loss_streak']}")
            if not rsn:
                if r=="PAUSE": out["allow_opens"]=out["allow_pa"]=False; rsn.append("REC=PAUSE")
                elif r=="GO":
                    if pf>=DEFAULTS["arm_pf"] and cnt>=DEFAULTS["arm_count"]: out["allow_pa"]=True; rsn.append("arm: pf&count OK")
                    elif pf>=DEFAULTS["hold_pf"]: rsn.append("hold: pf>=hold_pf but below arm thresholds")
                    else: rsn.append("GO but below thresholds")
                else: rsn.append("REC!=GO")
        out["reason"]="; ".join(rsn) if rsn else "ok"; return out
    except Exception as e:
        out["allow_opens"]=True; out["allow_pa"]=False; out["reason"]=f"fail-soft: {e}"; return out
