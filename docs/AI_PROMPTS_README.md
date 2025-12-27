# AI Prompts for Chloe Alpha

This directory contains reusable prompts for working with AI assistants (Cursor, Claude, GPT, etc.) on the Chloe Alpha codebase.

## Quick Start

1. **First, paste the Master Context** (`MASTER_CONTEXT.md`) into your AI assistant to establish the baseline understanding.

2. **Then, use role-specific prompts** as needed:
   - `ROLE_ALPHA_ENGINEER.md` - For code changes and logic fixes
   - `ROLE_AUDITOR.md` - For health checks and PF analysis
   - `ROLE_TUNER.md` - For threshold tuning using GPT

## Usage Pattern

### Example 1: Fixing a Bug

```
[Paste MASTER_CONTEXT.md]

[Paste ROLE_ALPHA_ENGINEER.md]

Task: Fix the regime gate to allow BACKTEST_FREE_REGIME=1 override.
```

### Example 2: Health Check

```
[Paste MASTER_CONTEXT.md]

[Paste ROLE_AUDITOR.md]

Task: Analyze the current live/paper state and tell me if Chloe is ready to trade.
```

### Example 3: Threshold Tuning

```
[Paste MASTER_CONTEXT.md]

[Paste ROLE_TUNER.md]

Task: Analyze conf_ret_summary.json and propose new entry thresholds.
```

## File Structure

- `MASTER_CONTEXT.md` - Base context (paste once per session)
- `ROLE_ALPHA_ENGINEER.md` - Code engineering role
- `ROLE_AUDITOR.md` - Health auditing role
- `ROLE_TUNER.md` - Threshold tuning role

## Notes

- These prompts are designed to work together. Always start with `MASTER_CONTEXT.md`.
- Role prompts can be mixed and matched based on the task.
- The prompts enforce the "unified code path" constraint - no backtest/live divergence.
- All prompts assume you're working in `/root/Chloe-alpha`.

## Updating These Prompts

If you update the codebase structure or add new tools, update the relevant prompts to reflect:
- New file paths
- New tool names
- Changed behavior or constraints


