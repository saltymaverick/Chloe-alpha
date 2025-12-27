# SWARM Operational Guide

**Complete guide to Chloe's SWARM supervisory layer**

---

## Overview

SWARM is Chloe's independent oversight committee that runs automatically alongside her trading operations. It provides:

- **Health monitoring** (PF, drawdown, blind spots)
- **Research verification** (outputs present, consistent)
- **Decision auditing** (challenges every trade decision)
- **Periodic audits** (comprehensive state checks)

---

## Components

### 1. SWARM Sentinel
**Purpose:** Health + invariants monitoring

**Runs:**
- Nightly (with research)
- Every 5 minutes (via audit loop)

**Checks:**
- PF_local < 0.90 → Critical
- PF_local < 0.95 → Warning
- Drawdown > 25% → Critical
- Drawdown > 15% → Warning
- Blind spots count
- Average edge (warns if negative)

**Output:** `reports/research/swarm_sentinel_report.json`

---

### 2. SWARM Audit Loop
**Purpose:** Periodic comprehensive audit

**Runs:** Every 5 minutes (systemd timer)

**Checks:**
- Sentinel health status
- Analyzer output present
- Strengths file present
- Confidence map present
- Thresholds file present

**Output:** `reports/research/swarm_audit_log.jsonl`

---

### 3. SWARM Research Verifier
**Purpose:** Nightly consistency checks

**Runs:** Nightly (with research pipeline)

**Checks:**
- Analyzer output valid (has horizons, stats)
- Strengths file present
- Thresholds file present
- Confidence map present
- Cross-checks regime names match

**Output:** `reports/research/swarm_research_verifier.jsonl`

---

### 4. SWARM Challenger
**Purpose:** Independent decision audit

**Runs:** On every trade decision (live loop)

**Logic:**
- Uses confidence map + regime strengths
- Computes combined edge
- Compares with Chloe's decision
- Verdict: "agree", "disagree", or "warning"

**Output:** `reports/research/swarm_challenger_log.jsonl`

---

### 5. SWARM Dashboard Panel
**Purpose:** Visual oversight

**Shows:**
- Last sentinel snapshot
- Recent audit logs (last 5)
- Research verification records (last 5)
- Challenger decisions (last 20)

**Location:** Dashboard → Feeds/Health tab

---

## Integration Points

### ✅ Nightly Research (`engine_alpha/reflect/nightly_research.py`)

At the end of the research pipeline:

```python
# SWARM research verifier
verify_research_outputs()

# SWARM sentinel snapshot
run_sentinel_checks()
```

**Runs:** Every night at 03:05 UTC (systemd timer)

---

### ✅ Live Loop (`engine_alpha/loop/autonomous_trader.py`)

After trade opens:

```python
# SWARM Challenger: independent decision audit
evaluate_decision(
    symbol=symbol,
    regime=regime,
    confidence=confidence,
    chloe_decision=side,  # "long", "short", or "flat"
)
```

**Runs:** On every trade decision (non-blocking)

---

### ✅ Dashboard (`engine_alpha/dashboard/dashboard.py`)

In Feeds/Health tab:

```python
from engine_alpha.dashboard.swarm_panel import swarm_panel
swarm_panel()
```

**Updates:** Real-time (every dashboard refresh)

---

## Systemd Services

### SWARM Audit Loop

**Service:** `chloe-swarm-audit.service`
**Timer:** `chloe-swarm-audit.timer`
**Frequency:** Every 5 minutes
**First Run:** 3 minutes after boot

**Enable:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now chloe-swarm-audit.timer
```

---

### Nightly Research

**Service:** `chloe-nightly-research.service`
**Timer:** `chloe-nightly-research.timer`
**Frequency:** Every night at 03:05 UTC
**Persistent:** Yes (catches up if system was down)

**Enable:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now chloe-nightly-research.timer
```

---

## Quick Setup

Run the setup script:

```bash
sudo bash /tmp/swarm_setup.sh
```

Or manually:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now chloe-swarm-audit.timer
sudo systemctl enable --now chloe-nightly-research.timer
```

---

## Monitoring

### Check Timer Status

```bash
# SWARM audit timer
sudo systemctl status chloe-swarm-audit.timer

# Nightly research timer
sudo systemctl status chloe-nightly-research.timer
```

### Check Last Run

```bash
# SWARM audit service
sudo systemctl status chloe-swarm-audit.service

# Nightly research service
sudo systemctl status chloe-nightly-research.service
```

### View Logs

```bash
# SWARM audit logs (last 20)
journalctl -u chloe-swarm-audit.service -n 20

# Follow SWARM audit logs
journalctl -u chloe-swarm-audit.service -f

# Nightly research logs (last 50)
journalctl -u chloe-nightly-research.service -n 50

# Follow nightly research logs
journalctl -u chloe-nightly-research.service -f
```

### View SWARM Status (JSON)

```bash
python3 -c "from engine_alpha.dashboard.swarm_panel import get_swarm_status; import json; print(json.dumps(get_swarm_status(), indent=2))"
```

---

## Operational Flow

### Every 5 Minutes
1. SWARM Audit Loop runs
2. Checks health + research outputs
3. Logs to `swarm_audit_log.jsonl`

### Every Night (03:05 UTC)
1. Nightly research runs
2. Hybrid dataset building
3. Weighted analyzer
4. GPT tuner
5. Confidence map update
6. Strategy strength update
7. Quant monitor tiles
8. **SWARM research verifier**
9. **SWARM sentinel snapshot**

### Every Trade Decision
1. Chloe decides (regime/side/confidence)
2. Trade opens (if allowed)
3. **SWARM Challenger evaluates**
4. Logs agreement/disagreement
5. Non-blocking (doesn't affect trading)

### Dashboard (Real-time)
1. Shows sentinel status
2. Shows audit logs
3. Shows research checks
4. Shows challenger decisions
5. Updates every ~10 seconds

---

## Output Files

All SWARM outputs are in `reports/research/`:

- `swarm_sentinel_report.json` - Latest health snapshot
- `swarm_audit_log.jsonl` - Periodic audit history
- `swarm_research_verifier.jsonl` - Research verification history
- `swarm_challenger_log.jsonl` - Decision audit history

---

## Troubleshooting

### SWARM Audit Not Running

```bash
# Check timer status
sudo systemctl status chloe-swarm-audit.timer

# Check service logs
journalctl -u chloe-swarm-audit.service -n 50

# Manually trigger
sudo systemctl start chloe-swarm-audit.service
```

### Nightly Research Not Running

```bash
# Check timer status
sudo systemctl status chloe-nightly-research.timer

# Check service logs
journalctl -u chloe-nightly-research.service -n 50

# Manually trigger
sudo systemctl start chloe-nightly-research.service
```

### Challenger Not Logging

- Check that trades are actually opening
- Check `reports/research/swarm_challenger_log.jsonl` exists
- Check live loop logs for SWARM errors (should be non-blocking)

---

## Summary

**Chloe trades.**
**The SWARM watches.**
**You just read the reports.**

All SWARM components run automatically:
- ✅ Sentinel monitoring health
- ✅ Audit loop checking state
- ✅ Research verifier validating outputs
- ✅ Challenger auditing decisions
- ✅ Dashboard showing everything

No manual intervention required. SWARM is fully operational.


