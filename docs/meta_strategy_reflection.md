# Meta-Strategy Reflection Module

## Overview

The Meta-Strategy Reflection module gives Chloe a "macro brain" that reflects on broader market behavior and strategic patterns, beyond simple parameter tuning.

**Unlike threshold tuning** (which adjusts `entry_min_conf`, enables/disables regimes), this module identifies high-level patterns and proposes strategic ideas:

- "High-vol is the only regime with edge; maybe specialize in volatility breakouts"
- "Trend-down shorts behave like mean-reversion; stop treating as trend strategy"
- "Winning trades cluster around certain times; consider time-of-day filter"

## Current Status

**Advisory Mode Only** - The module writes structured reflections to a JSONL log file. It does NOT automatically modify trading behavior or thresholds.

Later, reflections can be:
- Reviewed manually and implemented
- Wired into `strategy_evolver.py` for automated strategy evolution
- Displayed in the dashboard for operator review

## Usage

### Manual Run

```bash
# Run meta-strategy reflection
python3 -m tools.run_meta_strategy_reflection

# View last reflection
tail -n 1 reports/research/meta_strategy_reflections.jsonl | jq .

# View all reflections
cat reports/research/meta_strategy_reflections.jsonl | jq .
```

### Programmatic Usage

```python
from engine_alpha.reflect.meta_strategy_reflection import run_meta_strategy_reflection

log_path = run_meta_strategy_reflection()
# Reflection written to log_path
```

## What Data Chloe Sees

The module builds a `MetaContext` from:

1. **PF Local** (`reports/pf_local.json`)
   - Current profit factor
   - Trade count
   - Performance summary

2. **Strategy Strength** (`reports/research/strategy_strength.json`)
   - Per-regime edge and strength
   - Sample counts per regime
   - Hit rates

3. **Confidence Map** (`config/confidence_map.json`)
   - Expected returns per confidence bucket
   - Sample counts per bucket

4. **Regime Thresholds** (`config/regime_thresholds.json`)
   - Which regimes are enabled/disabled
   - Entry confidence thresholds per regime

5. **SWARM Sentinel** (`reports/research/swarm_sentinel_report.json`)
   - High-level health signals
   - PF, drawdown, blind spots

6. **Observation Mode** (`config/observation_mode.json`)
   - Which regimes are in observation mode
   - Edge floor and size factor settings

## Output Format

Each reflection is written as a JSONL record:

```json
{
  "ts": "2025-11-25T23:00:00Z",
  "context": {
    "pf_local": {...},
    "strategy_strength": {...},
    "confidence_map": {...},
    "regime_thresholds": {...},
    "swarm_sentinel": {...},
    "observation_mode": {...}
  },
  "prompt": "...",
  "reflection": {
    "patterns": [
      {
        "description": "High-level pattern",
        "evidence": "Supporting data",
        "implications": "What this means"
      }
    ],
    "strategic_ideas": [
      {
        "name": "Idea name",
        "intuition": "Why this might help",
        "conditions": "When/where it applies",
        "implementation_sketch": "Rough approach",
        "risk_considerations": "What could go wrong",
        "priority": "high|medium|low"
      }
    ],
    "summary": "Executive summary"
  },
  "gpt_metadata": {
    "tokens": 1234,
    "cost_usd": 0.001
  }
}
```

## Scheduling

### Weekly Timer (Recommended)

Create systemd timer for weekly runs:

**File:** `/etc/systemd/system/chloe-meta-strategy.service`

```ini
[Unit]
Description=Chloe Meta-Strategy Reflection
After=network.target

[Service]
Type=oneshot
User=root
WorkingDirectory=/root/Chloe-alpha
Environment="PATH=/root/Chloe-alpha/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/root/Chloe-alpha/venv/bin/python3 -m tools.run_meta_strategy_reflection
StandardOutput=journal
StandardError=journal
```

**File:** `/etc/systemd/system/chloe-meta-strategy.timer`

```ini
[Unit]
Description=Weekly Meta-Strategy Reflection Timer
Requires=chloe-meta-strategy.service

[Timer]
OnCalendar=Sun 03:15
Persistent=true

[Install]
WantedBy=timers.target
```

**Enable:**

```bash
sudo systemctl daemon-reload
sudo systemctl enable chloe-meta-strategy.timer
sudo systemctl start chloe-meta-strategy.timer
sudo systemctl status chloe-meta-strategy.timer
```

### Integration with Nightly Research

Alternatively, add to `tools/nightly_research.py`:

```python
# At end of nightly research, run meta-strategy reflection every 7 days
from datetime import datetime
from engine_alpha.reflect.meta_strategy_reflection import run_meta_strategy_reflection

if datetime.now().weekday() == 6:  # Sunday
    run_meta_strategy_reflection()
```

## Future Enhancements

1. **Dashboard Panel**
   - Display last few reflections
   - Show strategic ideas with status (considered/accepted/rejected)
   - Allow operator to mark ideas for implementation

2. **Strategy Evolver Integration**
   - Automatically implement low-risk ideas
   - A/B test strategic variations
   - Track performance of implemented ideas

3. **Multi-Asset Awareness**
   - Extend context to include per-symbol stats
   - Identify cross-asset patterns
   - Propose portfolio-level strategies

4. **Glassnode Integration**
   - Include on-chain metrics in context
   - Propose macro filters based on chain data
   - Identify regime shifts from on-chain signals

## Safety

- **No Automatic Changes** - Module only writes reflections, never modifies configs
- **Budget Controlled** - Uses GPT budget system (see `engine_alpha/core/gpt_client.py`)
- **Reviewable** - All reflections logged with full context for human review
- **Fail-Safe** - If GPT call fails, module logs warning and continues

## Examples

### Example Reflection Output

```json
{
  "patterns": [
    {
      "description": "High-vol is the only regime with positive edge",
      "evidence": "high_vol edge=+0.00083, trend_down=-0.00028, trend_up=-0.00040",
      "implications": "Consider specializing in volatility breakouts"
    }
  ],
  "strategic_ideas": [
    {
      "name": "High-Vol Breakout Micro-Strategy",
      "intuition": "High-vol shows consistent positive edge; focus resources here",
      "conditions": "When volatility regime is high_vol and confidence >= 0.6",
      "implementation_sketch": "Increase size factor for high_vol, add volatility breakout filter",
      "risk_considerations": "Over-concentration risk if high_vol regime disappears",
      "priority": "high"
    }
  ],
  "summary": "Chloe's edge is concentrated in high-volatility regimes. Consider building dedicated vol-breakout strategy."
}
```

## Troubleshooting

**No reflections generated:**
- Check GPT budget: `cat reports/gpt_budget.json`
- Verify research outputs exist: `ls reports/research/strategy_strength.json`
- Check logs: `journalctl -u chloe-meta-strategy.service`

**Reflections seem generic:**
- Ensure sufficient trade history (20+ trades recommended)
- Check that strategy_strength has non-zero sample counts
- Verify confidence_map has meaningful expected returns

**GPT call fails:**
- Verify `OPENAI_API_KEY` environment variable is set
- Check network connectivity
- Review GPT budget limits


