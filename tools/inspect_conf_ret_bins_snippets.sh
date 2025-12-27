#!/bin/bash
# Quick shell snippets for inspecting conf_ret_summary_multi.json
# These are one-off scripts that can be run directly in the Chloe venv

cd /root/Chloe-alpha
export PYTHONPATH=/root/Chloe-alpha

# A. Trend_down: all horizons, conf >= 0.60
echo "=== trend_down: conf >= 0.60 across horizons ==="
python3 - << 'EOF'
import json
from pathlib import Path

path = Path("reports/analysis/conf_ret_summary_multi.json")
data = json.loads(path.read_text())
bins = data["bins"]

print("regime   h  conf_range    count   pf    mean     p50      p75      p90")
print("-----------------------------------------------------------------------")
for b in bins:
    if b["regime"] != "trend_down":
        continue
    if b["conf_min"] < 0.60:
        continue
    h = b["horizon"]
    cmin, cmax = b["conf_min"], b["conf_max"]
    count = b["count"]
    pf = b["pf"]
    mean_ret = b["mean_ret"]
    p50 = b["p50"]
    p75 = b["p75"]
    p90 = b["p90"]
    print(f"{b['regime']:<10} {h:<2} [{cmin:.2f},{cmax:.2f}) "
          f"{count:6d}  {pf:5.2f}  {mean_ret:7.5f}  {p50:7.5f}  {p75:7.5f}  {p90:7.5f}")
EOF

echo ""
echo "=== high_vol: conf >= 0.50 across horizons ==="
python3 - << 'EOF'
import json
from pathlib import Path

path = Path("reports/analysis/conf_ret_summary_multi.json")
data = json.loads(path.read_text())
bins = data["bins"]

print("regime   h  conf_range    count   pf    mean     p50      p75      p90")
print("-----------------------------------------------------------------------")
for b in bins:
    if b["regime"] != "high_vol":
        continue
    if b["conf_min"] < 0.50:
        continue
    h = b["horizon"]
    cmin, cmax = b["conf_min"], b["conf_max"]
    count = b["count"]
    pf = b["pf"]
    mean_ret = b["mean_ret"]
    p50 = b["p50"]
    p75 = b["p75"]
    p90 = b["p90"]
    print(f"{b['regime']:<10} {h:<2} [{cmin:.2f},{cmax:.2f}) "
          f"{count:6d}  {pf:5.2f}  {mean_ret:7.5f}  {p50:7.5f}  {p75:7.5f}  {p90:7.5f}")
EOF

echo ""
echo "=== trend_up: conf >= 0.60 across horizons ==="
python3 - << 'EOF'
import json
from pathlib import Path

path = Path("reports/analysis/conf_ret_summary_multi.json")
data = json.loads(path.read_text())
bins = data["bins"]

print("regime   h  conf_range    count   pf    mean     p50      p75      p90")
print("-----------------------------------------------------------------------")
for b in bins:
    if b["regime"] != "trend_up":
        continue
    if b["conf_min"] < 0.60:
        continue
    h = b["horizon"]
    cmin, cmax = b["conf_min"], b["conf_max"]
    count = b["count"]
    pf = b["pf"]
    mean_ret = b["mean_ret"]
    p50 = b["p50"]
    p75 = b["p75"]
    p90 = b["p90"]
    print(f"{b['regime']:<10} {h:<2} [{cmin:.2f},{cmax:.2f}) "
          f"{count:6d}  {pf:5.2f}  {mean_ret:7.5f}  {p50:7.5f}  {p75:7.5f}  {p90:7.5f}")
EOF


