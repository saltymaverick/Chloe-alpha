#!/usr/bin/env python3
import json, os, sys, pathlib, importlib, datetime
ROOT = pathlib.Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"; LOGS = ROOT / "logs"; CONFIG = ROOT / "config" / "engine_config.json"
def is_writable(p: pathlib.Path)->bool:
    try: p.mkdir(parents=True, exist_ok=True); t=p/".wtest"; t.write_text("ok"); t.unlink(); return True
    except Exception: return False
def main():
    r={"ts": datetime.datetime.utcnow().isoformat()+"Z","root":str(ROOT),"checks":[]}; ok=True
    py_ok = (sys.version_info.major==3 and sys.version_info.minor>=10); r["checks"].append({"name":"python_version","value":sys.version.split()[0],"ok":py_ok}); ok&=py_ok
    for name, path in [("reports_writable",REPORTS),("logs_writable",LOGS),("data_writable",ROOT/"data")]:
        w=is_writable(path); r["checks"].append({"name":name,"path":str(path),"ok":w}); ok&=w
    cfg_ok=mode_ok=False; mode_val=None
    try: cfg=json.loads(CONFIG.read_text()); cfg_ok=True; mode_val=cfg.get("mode"); mode_ok=(mode_val=="PAPER")
    except Exception as e: r["config_error"]=str(e)
    r["checks"].append({"name":"config_present","path":str(CONFIG),"ok":cfg_ok})
    r["checks"].append({"name":"mode_paper","value":mode_val,"ok":mode_ok}); ok&=cfg_ok and mode_ok
    sys.path.insert(0,str(ROOT))
    try: importlib.invalidate_caches(); importlib.import_module("engine_alpha"); pkg_ok=True
    except Exception as e: pkg_ok=False; r["import_error"]=repr(e)
    r["checks"].append({"name":"package_import","ok":pkg_ok}); ok&=pkg_ok
    r["ok"]=bool(ok); REPORTS.mkdir(parents=True, exist_ok=True); (REPORTS/"boot_report.json").write_text(json.dumps(r,indent=2))
    print(json.dumps(r,indent=2)); return 0 if ok else 1
if __name__=="__main__": raise SystemExit(main())
