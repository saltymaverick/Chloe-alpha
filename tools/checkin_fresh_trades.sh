#!/bin/bash
# Quick check-in script for fresh trades after reset
# Run this after letting Chloe accumulate trades for a few hours

set -e

cd /root/Chloe-alpha
source venv/bin/activate
export PYTHONPATH=/root/Chloe-alpha

echo "======================================================================"
echo "Chloe Fresh Trades Check-in"
echo "======================================================================"
echo ""

echo "📊 Check-in Summary:"
echo "---"
python3 -m tools.chloe_checkin

echo ""
echo "📈 Filtered PF (TP/SL, |pct| >= 0.0005):"
echo "---"
python3 -m tools.pf_doctor_filtered --threshold 0.0005 --reasons tp,sl

echo ""
echo "📋 Recent Trades (last 20 closes):"
echo "---"
grep '"type": "close"' reports/trades.jsonl | tail -n 20 | while read line; do
    echo "$line" | python3 -c "
import json, sys
try:
    t = json.loads(sys.stdin.read())
    ts = t.get('ts', 'N/A')
    pct = t.get('pct', 0.0)
    exit_reason = t.get('exit_reason', 'unknown')
    is_scratch = t.get('is_scratch', False)
    print(f'{ts} | pct={pct:.6f}% | {exit_reason} | scratch={is_scratch}')
except:
    print(sys.stdin.read())
"
done

echo ""
echo "======================================================================"
echo "✅ Check-in complete"
echo "======================================================================"


