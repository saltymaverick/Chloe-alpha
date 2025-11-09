#!/usr/bin/env bash
# Ops health wrapper — runs ops health and restarts dashboard if needed.

set -euo pipefail

ROOT="/root/Chloe-alpha"
DASH_MATCH="streamlit run engine_alpha/dashboard/dashboard.py"

cd "$ROOT"

# Run ops health (already appends status into logs/ops.log internally)
python3 -m tools.ops_health || true

if ! pgrep -f "$DASH_MATCH" >/dev/null 2>&1; then
  nohup python3 -m tools.run_dashboard >/dev/null 2>&1 &
  TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  mkdir -p "$ROOT/logs"
  printf '{"ts":"%s","event":"dashboard_restart","source":"ops_health_restart"}\n' "$TS" >> "$ROOT/logs/ops.log"
fi

