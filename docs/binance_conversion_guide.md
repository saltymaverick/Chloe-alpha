# Binance CSV to Chloe Parquet Conversion Guide

Convert Binance historical OHLCV data to Chloe's Parquet format for multi-asset research.

## Quick Start

### Single File Conversion

```bash
python3 -m tools.convert_binance_to_chloe \
  --input binance_data/BTCUSDT_1h.csv \
  --symbol BTCUSDT \
  --timeframe 1h
```

### Batch Conversion (All Files in Directory)

```bash
python3 -m tools.convert_binance_to_chloe \
  --dir binance_data/ \
  --timeframe 1h
```

## Supported Binance CSV Formats

The converter automatically detects common Binance CSV formats:

### Format 1: Standard Binance Export
```csv
timestamp,open,high,low,close,volume
1609459200000,29350.5,29400.2,29300.1,29380.3,1234.56
```

### Format 2: With Column Headers
```csv
open_time,open,high,low,close,volume
2020-12-31 00:00:00,29350.5,29400.2,29300.1,29380.3,1234.56
```

### Format 3: ISO Timestamps
```csv
date,open,high,low,close,vol
2020-12-31T00:00:00Z,29350.5,29400.2,29300.1,29380.3,1234.56
```

## Output Format

Converted files are written to:
```
data/ohlcv/{symbol}_{timeframe}_historical.parquet
```

Example:
- `data/ohlcv/btcusdt_1h_historical.parquet`
- `data/ohlcv/ethusdt_1h_historical.parquet`

## Column Structure

Chloe's Parquet format includes:
- `ts` - ISO8601 timestamp with timezone (UTC)
- `symbol` - Trading pair (e.g., BTCUSDT)
- `timeframe` - Timeframe (e.g., 1h)
- `open`, `high`, `low`, `close`, `volume` - OHLCV data
- `source` - "binance_historical"
- `source_tag` - "static"

## Usage Examples

### Convert All 12 Coins

If you have CSV files named like `BTCUSDT_1h.csv`, `ETHUSDT_1h.csv`, etc.:

```bash
# Put all CSVs in a directory
mkdir -p binance_data
# Copy your CSV files there

# Convert all at once
python3 -m tools.convert_binance_to_chloe \
  --dir binance_data/ \
  --timeframe 1h
```

### Custom Output Path

```bash
python3 -m tools.convert_binance_to_chloe \
  --input BTC.csv \
  --symbol BTCUSDT \
  --timeframe 1h \
  --output data/ohlcv/custom_btc.parquet
```

### Different File Patterns

If your files use a different naming pattern:

```bash
python3 -m tools.convert_binance_to_chloe \
  --dir binance_data/ \
  --timeframe 1h \
  --pattern "*.csv"  # Matches all CSV files
```

## After Conversion

### 1. Verify Files

```bash
ls -lh data/ohlcv/*_historical.parquet
```

### 2. Check Data Quality

```python
import pandas as pd

df = pd.read_parquet("data/ohlcv/btcusdt_1h_historical.parquet")
print(f"Rows: {len(df)}")
print(f"Date range: {df['ts'].min()} to {df['ts'].max()}")
print(f"Columns: {list(df.columns)}")
```

### 3. Run Nightly Research

The hybrid dataset builder will automatically use historical data:

```bash
python3 -m engine_alpha.reflect.nightly_research
```

This will:
- Merge historical Parquet files with live candles
- Build hybrid research datasets
- Run analyzer and tuner with richer history

## Troubleshooting

### "Could not detect timestamp column"

Your CSV might use non-standard column names. Check:
```bash
head -1 your_file.csv
```

Common fixes:
- Rename columns to: `timestamp`, `open`, `high`, `low`, `close`, `volume`
- Or modify the converter to handle your format

### "Could not parse timestamp"

The converter handles:
- Unix timestamps (seconds or milliseconds)
- ISO8601 strings
- Common date formats

If your format is different, you may need to pre-process the CSV.

### "CSV is empty"

Check that:
- File exists and is readable
- File has data rows (not just headers)
- File encoding is UTF-8

### Symbol Extraction Failed

If using `--dir`, the converter tries to extract symbol from filename:
- `BTCUSDT_1h.csv` → BTCUSDT ✅
- `BTC-USDT_1h.csv` → BTCUSDT ✅
- `BTC.csv` → BTCUSDT ✅

If extraction fails, use `--input` with explicit `--symbol`.

## Integration with Research Pipeline

Once converted, historical data is automatically used:

1. **Hybrid Dataset Builder** checks for `*_historical.parquet` files
2. Merges historical + live candles
3. Analyzer sees richer history
4. Tuner gets better edge estimates

No additional configuration needed - just convert and run nightly research!

## File Naming Conventions

Chloe expects historical files named:
```
{symbol}_{timeframe}_historical.parquet
```

Examples:
- `btcusdt_1h_historical.parquet`
- `ethusdt_1h_historical.parquet`
- `solusdt_1h_historical.parquet`

The converter automatically generates these names from your input.

## Next Steps

After converting Binance data:

1. ✅ Verify files exist: `ls -lh data/ohlcv/*_historical.parquet`
2. ✅ Run nightly research: `python3 -m engine_alpha.reflect.nightly_research`
3. ✅ Check hybrid datasets: `ls -lh reports/research/*/hybrid_research_dataset.parquet`
4. ✅ Review analyzer stats: `cat reports/research/BTCUSDT/multi_horizon_stats.json | jq .`

Your coins now have rich historical context for better research and tuning!


