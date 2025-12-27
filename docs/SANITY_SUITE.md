# System Sanity Suite

## Purpose

The System Sanity Suite is a comprehensive integrity check for Chloe-alpha that validates:

1. **Python Import Integrity**: All Python modules can be imported without syntax or circular dependency errors
2. **JSON Contract Validation**: All JSON contract files have correct structure and required fields
3. **Tool Execution**: All major tools can be imported and executed successfully
4. **Shadow Mode Enforcement**: Ensures shadow mode is active and exchange router blocks live orders

## Architecture

### Core Module: `tools/system_sanity.py`

The sanity suite provides:

- **`scan_python_imports()`**: Scans all Python files and attempts safe imports
- **`validate_json_contracts()`**: Validates JSON contract files for structure and completeness
- **`validate_tools()`**: Checks that all major tools can be imported
- **`check_shadow_mode()`**: Verifies shadow mode is enforced

### Output: `reports/system/sanity_report.json`

The sanity suite writes a structured report:

```json
{
  "python_imports": {
    "engine_alpha/evolve/evolver_core.py": "PASS",
    "tools/run_evolver_cycle.py": "PASS",
    ...
  },
  "json_contracts": {
    "reports/gpt/reflection_input.json": "PASS",
    "reports/gpt/reflection_output.json": "PASS",
    ...
  },
  "tools": {
    "run_evolver_cycle": "PASS",
    "run_mutation_preview": "PASS",
    ...
  },
  "shadow_mode": {
    "status": true,
    "env_var_set": true,
    "router_check": true,
    "details": "..."
  },
  "summary": {
    "success": true,
    "errors": [],
    "timestamp": "2025-12-04T22:00:00+00:00"
  }
}
```

## How Chloe Uses Sanity Suite

### Pre-Automation Gate

Before any autonomous tuning loops or automated config changes, Chloe runs the sanity suite to ensure:

1. **System Integrity**: All modules are importable and functional
2. **Data Completeness**: All required JSON contracts exist and are valid
3. **Tool Availability**: All analysis tools are available
4. **Safety Enforcement**: Shadow mode is active and preventing live orders

### Continuous Monitoring

The sanity suite can be run:

- **Before major operations**: Before running reflection/tuner cycles
- **After code changes**: After deploying new modules or tools
- **Periodically**: As part of a scheduled health check

### Failure Handling

If the sanity suite reports failures:

- **Python Import Failures**: Indicates syntax errors or broken dependencies
- **JSON Contract Failures**: Indicates missing or corrupted data files
- **Tool Failures**: Indicates tools cannot be imported or executed
- **Shadow Mode Failures**: Indicates safety layer may be compromised

## Future Autonomous Tuning Loops

The sanity suite is critical for future autonomous tuning loops:

### Pre-Tuning Gate

Before any autonomous tuning cycle:

1. Run sanity suite
2. Verify all checks pass
3. Only proceed if `summary.success == true`

### Post-Tuning Validation

After tuning proposals are generated:

1. Re-run sanity suite
2. Verify no new failures introduced
3. Validate that shadow mode remains active

### Safety Contract

The sanity suite enforces a safety contract:

- ✅ **No config modifications** unless sanity checks pass
- ✅ **No live orders** unless shadow mode is verified active
- ✅ **No tool execution** unless all dependencies are valid
- ✅ **No data corruption** unless JSON contracts are validated

## Usage

Run the sanity suite:

```bash
python3 -m tools.system_sanity
```

This will:
1. Scan all Python files and check imports
2. Validate all JSON contract files
3. Check all major tools
4. Verify shadow mode enforcement
5. Write `reports/system/sanity_report.json`
6. Print summary to stdout

## Integration Points

### CI/CD Pipeline

The sanity suite can be integrated into CI/CD:

```bash
# In CI pipeline
python3 -m tools.system_sanity
if [ $? -ne 0 ]; then
    echo "Sanity checks failed - blocking deployment"
    exit 1
fi
```

### Pre-Deployment Check

Before deploying new code:

```bash
python3 -m tools.system_sanity
# Review sanity_report.json
# Only deploy if summary.success == true
```

### Automated Monitoring

Schedule periodic sanity checks:

```bash
# Cron job: Run sanity check every hour
0 * * * * cd /root/Chloe-alpha && python3 -m tools.system_sanity
```

## Validation Rules

### Python Imports

- ✅ File exists
- ✅ No syntax errors
- ✅ No import errors
- ✅ No circular dependencies

### JSON Contracts

- ✅ File exists
- ✅ Valid JSON syntax
- ✅ Required fields present
- ✅ Data is non-empty

### Tools

- ✅ Module can be imported
- ✅ No import errors
- ✅ Module structure is valid

### Shadow Mode

- ✅ `BYBIT_SHADOW_MODE` environment variable is set to true
- ✅ `exchange_router.py` contains shadow mode logic
- ✅ No live order placement paths are reachable

## Error Reporting

The sanity suite reports errors in a structured format:

```json
{
  "summary": {
    "success": false,
    "errors": [
      "Python import engine_alpha/evolve/mutation_engine.py: FAIL: ImportError: No module named 'xyz'",
      "JSON contract reports/gpt/reflection_input.json: FAIL: Missing required fields: ['symbols']",
      "Tool run_mutation_preview: FAIL: Import failed: ...",
      "Shadow mode check failed: exchange_router.py may not have shadow mode checks"
    ],
    "timestamp": "2025-12-04T22:00:00+00:00"
  }
}
```

## Best Practices

1. **Run Before Major Operations**: Always run sanity suite before reflection/tuner cycles
2. **Fix Errors Immediately**: Address any failures before proceeding
3. **Monitor Shadow Mode**: Ensure shadow mode is always active in production
4. **Validate JSON Contracts**: Ensure all contract files are valid before GPT operations
5. **Check Tool Availability**: Verify all tools are importable before use

## Future Enhancements

Potential future enhancements:

1. **Performance Benchmarks**: Measure tool execution times
2. **Memory Leak Detection**: Check for memory issues in long-running tools
3. **Dependency Graph Validation**: Verify dependency relationships
4. **Config Schema Validation**: Validate config files against schemas
5. **Exchange Connectivity Checks**: Verify exchange API connectivity (read-only)


