#!/usr/bin/env bash
set -euo pipefail

echo "=== Chloe Soft Reset (LIVE/PAPER loop) ==="

ROOT="/root/Chloe-alpha"
REPORTS="$ROOT/reports"

cd "$ROOT"

echo "[1/5] Stopping live/paper services (if running)..."
sudo systemctl stop chloe-live 2>/dev/null || true
sudo systemctl stop chloe-paper 2>/dev/null || true
sudo systemctl stop chloe.service 2>/dev/null || true
sudo systemctl stop chloe-live-loop.service 2>/dev/null || true

echo "[2/5] Archiving current live trades.jsonl..."
TRADES="$REPORTS/trades.jsonl"
TS=$(date -u +"%Y%m%dT%H%M%SZ")

if [ -f "$TRADES" ] && [ -s "$TRADES" ]; then
  ARCHIVE="$REPORTS/trades_pre_reset_$TS.jsonl"
  mv "$TRADES" "$ARCHIVE"
  echo "     Archived live trades to: $ARCHIVE"
else
  echo "     No non-empty trades.jsonl to archive."
fi

# create fresh empty ledger
: > "$TRADES"
echo "     Created fresh empty trades.jsonl"

echo "[3/5] Clearing loop health, positions, incidents, and PF files..."
: > "$REPORTS/loop_health.json" 2>/dev/null || true
: > "$REPORTS/positions.json"    2>/dev/null || true
: > "$REPORTS/incidents.jsonl"   2>/dev/null || true

: > "$REPORTS/pf_local.json"     2>/dev/null || true
: > "$REPORTS/pf_live.json"      2>/dev/null || true

echo "[4/5] Reminder: clear any BACKTEST/LAB env vars in your shell:"
echo "     Run this in your (venv) shell if you haven't already:"
echo "       unset BACKTEST_MIN_CONF"
echo "       unset BACKTEST_SIMPLE_EXITS"
echo "       unset DEBUG_SIGNALS"
echo

echo "[5/5] Starting PAPER mode clean..."
# chloe.service runs in PAPER mode (MODE=PAPER env var)
sudo systemctl start chloe.service
sudo systemctl status chloe.service --no-pager -n 5 || true

echo
echo "=== Reset complete ==="
echo "Now run:"
echo "  python3 -m tools.status"
echo "  python3 -m tools.pf_doctor"
echo "to confirm: Trades=0, PF=0.0 and Risk band should be A or C with no junk trades."
