# Systemd Service Files for Chloe Alpha Automation (Templates)

This directory contains **template** systemd unit files and environment templates.

Note: this repo’s `.cursorignore` blocks editing real `*.service` / `*.timer` files, so these are shipped as `*.service.example` / `*.timer.example`. When installing, copy + rename them to `/etc/systemd/system/*.service` and `/etc/systemd/system/*.timer`.

## Files

- `chloe-policy-refresh.service` / `chloe-policy-refresh.timer` (legacy docs; prefer orchestrator)
- `chloe-reflect-performance.service.example` / `chloe-reflect-performance.timer.example`
- `chloe-reflection-v4.service.example` / `chloe-reflection-v4.timer.example` (full narrative reflection via `tools.run_reflection_cycle`)
- `nightly_research.service.example` / `nightly_research.timer.example`
- `chloe.env.example` (EnvironmentFile template)

## Installation

### 0) Create a systemd EnvironmentFile (IMPORTANT)

Systemd **does not support** `export KEY=VALUE` inside `EnvironmentFile`.

Create:
- `/root/Chloe-alpha/systemd/chloe.env` (copy from `systemd/chloe.env.example`)

### 1) Copy service and timer files

Copy the `*.example` templates to `/etc/systemd/system/` **and rename**:

```bash
sudo cp systemd/chloe-reflect-performance.service.example /etc/systemd/system/chloe-reflect-performance.service
sudo cp systemd/chloe-reflect-performance.timer.example /etc/systemd/system/chloe-reflect-performance.timer

sudo cp systemd/nightly_research.service.example /etc/systemd/system/nightly_research.service
sudo cp systemd/nightly_research.timer.example /etc/systemd/system/nightly_research.timer

# Optional: full narrative GPT reflection v4 (writes reports/gpt/reflection_output.json)
sudo cp systemd/chloe-reflection-v4.service.example /etc/systemd/system/chloe-reflection-v4.service
sudo cp systemd/chloe-reflection-v4.timer.example /etc/systemd/system/chloe-reflection-v4.timer
```

### 2) Reload systemd daemon

```bash
sudo systemctl daemon-reload
```

### 3) Enable and start timers

```bash
sudo systemctl enable --now chloe-reflect-performance.timer
sudo systemctl enable --now nightly_research.timer
# Optional:
sudo systemctl enable --now chloe-reflection-v4.timer
```

## Verification

Check timer status:

```bash
sudo systemctl status chloe-reflect-performance.timer --no-pager
sudo systemctl status nightly_research.timer --no-pager
```

Run manually (oneshot) to confirm it executes:

```bash
sudo systemctl start chloe-reflect-performance.service
sudo systemctl start nightly_research.service
```

View recent logs:

```bash
journalctl -u chloe-reflect-performance.service -n 200 --no-pager -o cat
journalctl -u nightly_research.service -n 200 --no-pager -o cat
```

## Configuration

To change cadence, edit the timer files in `/etc/systemd/system/`:

- `chloe-reflect-performance.timer` uses `OnUnitActiveSec=` (interval)
- `nightly_research.timer` uses `OnCalendar=` (daily schedule)

After editing, reload and restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart chloe-reflect-performance.timer
sudo systemctl restart nightly_research.timer
```

## Manual Execution

You can run these jobs directly (same command the service uses):

```bash
cd /root/Chloe-alpha
source venv/bin/activate
python3 -m engine_alpha.reflect.gpt_reflection_runner
python3 -m engine_alpha.reflect.nightly_research
```

## What It Does

Every 5 minutes (or your configured interval), the service:

1. Recomputes PF time-series (`reports/pf/pf_timeseries.json`)
2. Recomputes Capital Protection (`reports/risk/capital_protection.json`)
3. Recomputes Exploration Policy V3 (`reports/research/exploration_policy_v3.json`)

This keeps the exploration gate (`exploration_policy_gate.py`) current with recent performance data, allowing symbols to move between `full`/`reduced`/`blocked` states based on recent PF windows without waiting for the nightly research cycle.

