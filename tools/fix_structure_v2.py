#!/usr/bin/env python3
import os, pathlib, json, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / "engine_alpha"
DIRS = [
    PKG, PKG/"core", PKG/"signals", PKG/"loop", PKG/"reflect", PKG/"evolve", PKG/"mirror", PKG/"dashboard",
    ROOT/"config", ROOT/"reports", ROOT/"logs",
    ROOT/"data", ROOT/"data"/"ohlcv", ROOT/"data"/"sentiment", ROOT/"data"/"onchain", ROOT/"data"/"cache",
    ROOT/"tools", ROOT/"tests", ROOT/"builds",
]
def touch(p: pathlib.Path, content=""):
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists(): p.write_text(content)
def ensure_inits():
    for p in [PKG, *(d for d in PKG.iterdir() if d.is_dir())]:
        touch(p / "__init__.py", "# init\n")
def ensure_gitkeep(d: pathlib.Path):
    gk = d / ".gitkeep"
    if d.is_dir() and not any(d.iterdir()): touch(gk)
def main():
    created=[]
    for d in DIRS:
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True); created.append(str(d.relative_to(ROOT)))
    ensure_inits()
    for d in [ROOT/"reports", ROOT/"logs", ROOT/"data"/"ohlcv", ROOT/"data"/"sentiment", ROOT/"data"/"onchain", ROOT/"data"/"cache"]:
        ensure_gitkeep(d)
    print(json.dumps({"status":"ok","created":created}, indent=2))
if __name__=="__main__": sys.exit(main())
