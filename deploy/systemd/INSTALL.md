# Systemd Service Installation for Chloe Automation

## Orchestrator Installation (Recommended - Phase 5b)

The orchestrator provides unified automation with three cadences:
- **fast**: Every 5 minutes (policy refresh, shadow exploit, gate test)
- **slow**: Hourly (drift scan, execution quality, policy refresh)
- **nightly**: Daily at 03:05 UTC (full research cycle, hindsight, thaw audit)

### Quick Install

```bash
# Copy orchestrator service and timer files
sudo cp deploy/systemd/chloe-orchestrator-*.service /etc/systemd/system/
sudo cp deploy/systemd/chloe-orchestrator-*.timer /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable and start all orchestrator timers
sudo systemctl enable --now chloe-orchestrator-fast.timer
sudo systemctl enable --now chloe-orchestrator-slow.timer
sudo systemctl enable --now chloe-orchestrator-nightly.timer
```

### Verify Installation

```bash
# Check timer status
systemctl list-timers --all | grep chloe-orchestrator

# Check service logs
journalctl -u chloe-orchestrator-fast.service -n 50 --no-pager
journalctl -u chloe-orchestrator-slow.service -n 50 --no-pager
journalctl -u chloe-orchestrator-nightly.service -n 50 --no-pager

# Run timer audit
python3 -m tools.timer_audit
```

### Disable Old Timers (After Orchestrator is Active)

Once orchestrator timers are running, you can safely disable old overlapping timers:

```bash
# Disable old per-task timers (orchestrator replaces these)
sudo systemctl disable --now chloe-policy-refresh.timer || true
sudo systemctl disable --now chloe-shadow-exploit.timer || true
sudo systemctl disable --now chloe-hindsight-reflection.timer || true

# Keep other timers if you want them separate from orchestrator
# (e.g., chloe-nightly-research.timer, chloe-dream.timer)
```

**Note**: Disabling timers does NOT delete the files. You can re-enable them later if needed.

### Manual Run

```bash
# Run orchestrator modes manually
python3 -m tools.chloe_orchestrator fast
python3 -m tools.chloe_orchestrator slow
python3 -m tools.chloe_orchestrator nightly

# Or via systemd
sudo systemctl start chloe-orchestrator-fast.service
sudo systemctl start chloe-orchestrator-slow.service
sudo systemctl start chloe-orchestrator-nightly.service
```

### Configuration

Edit timer files in `/etc/systemd/system/` to change intervals:

- **Fast timer**: `OnCalendar=*:0/5` → change to `*:0/10` for 10-minute cadence
- **Slow timer**: `OnCalendar=hourly` → change to `daily` for daily cadence
- **Nightly timer**: `OnCalendar=03:05` → change to `04:00` for different time

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl restart chloe-orchestrator-<mode>.timer
```

---

## Legacy: Policy Refresh Timer (Deprecated - Use Orchestrator Instead)

The standalone policy refresh timer is deprecated in favor of the orchestrator.
If you need to install it separately:

```bash
# Copy service and timer files
sudo cp deploy/systemd/chloe-policy-refresh.service /etc/systemd/system/
sudo cp deploy/systemd/chloe-policy-refresh.timer /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable and start timer
sudo systemctl enable chloe-policy-refresh.timer
sudo systemctl start chloe-policy-refresh.timer
```

**Note**: The orchestrator fast mode includes policy refresh, so running both creates conflicts.
Use the orchestrator instead.

---

## Phase 5b Verification Commands

After Phase 5b (Shadow Exploit Scoring + Promotion Gate) is installed:

```bash
# Run shadow exploit scorer manually
python3 -m tools.run_shadow_exploit_score

# Run shadow promotion gate manually
python3 -m tools.run_shadow_promotion_gate

# View dashboard with Phase 5b sections
python3 -m tools.intel_dashboard | tail -n 260

# Check new artifacts exist
ls -lah reports/reflect/ | grep shadow
ls -lah reports/evolver/ | grep shadow

# Run safety test
python3 -m tools.run_shadow_promotion_safety_test

# Check orchestrator logs (should show Phase 5b steps)
journalctl -u chloe-orchestrator-fast.service -n 80 --no-pager
journalctl -u chloe-orchestrator-nightly.service -n 80 --no-pager
```

Expected outputs:
- `reports/reflect/shadow_exploit_scores.json` - Per-symbol and global metrics
- `reports/reflect/shadow_exploit_pf.json` - PF snapshot (1D/7D/30D)
- `reports/evolver/shadow_promotion_candidates.json` - Promotion-eligible symbols
- `reports/evolver/shadow_promotion_history.jsonl` - Historical promotion evaluations
