#!/usr/bin/env bash
set -e

echo "================ CHLOE CHECK-IN (PF + Recovery) ================"
date -u
echo

# Refresh policy first to ensure fresh data
echo "=== REFRESHING POLICY ==="
python3 -m tools.chloe_orchestrator policy_refresh >/dev/null 2>&1 || true
python3 -m tools.run_pf_local >/dev/null 2>&1 || true
python3 -m tools.run_reflection_packet >/dev/null 2>&1 || true
echo "  Policy refreshed"
echo

if [ -f reports/risk/capital_protection.json ]; then
  echo "=== CORE CAPITAL PROTECTION ==="
  jq '.global.pf_7d, .global.pf_30d, .global.mode, .global.reasons' reports/risk/capital_protection.json 2>/dev/null || echo "  (file exists but unreadable)"
  echo
fi

if [ -f reports/pf_local.json ]; then
  echo "=== PF LOCAL ==="
  jq '.pf_24h, .pf_7d, .pf_30d' reports/pf_local.json 2>/dev/null || echo "  (file exists but unreadable)"
  echo
else
  echo "=== PF LOCAL ==="
  echo "  PF_LOCAL missing (file not generated)"
  echo
fi

if [ -f reports/reflection_packet.json ]; then
  echo "=== REFLECTION SNAPSHOT ==="
  jq '.meta.issues, .primitives.self_trust, .primitives.opportunity' reports/reflection_packet.json 2>/dev/null || echo "  (file exists but unreadable)"
  echo
fi

if [ -f reports/loop_health.json ]; then
  echo "=== LOOP HEALTH ==="
  jq '.last_tick_ok, .last_tick_ts, .last_tick_ms' reports/loop_health.json 2>/dev/null || echo "  (file exists but unreadable)"
  echo
fi

echo "==============================================================="
