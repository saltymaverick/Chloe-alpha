# CryptoDataDownload Integration Guide

Download and integrate Binance historical OHLCV data from CryptoDataDownload for all 12 coins.

## Quick Start

### 1. Download and Convert All Coins

```bash
python3 -m tools.download_cryptodatadownload
```

This will:
- Download CSVs from CryptoDataDownload for all 12 coins
- Convert them to Chloe Parquet format
- Save to `data/research_backtest/`

### 2. Run Nightly Research

```bash
python3 -m engine_alpha.reflect.nightly_research
```

Nightly research automatically:
- Detects Parquet files in `data/research_backtest/`
- Merges historical data with live candles
- Builds hybrid research datasets with deep history

### 3. Verify Integration

```bash
# Check hybrid datasets have more rows
python3 -c "
import pandas as pd
for sym in ['ETHUSDT', 'BTCUSDT', 'SOLUSDT']:
    df = pd.read_parquet(f'reports/research/{sym}/hybrid_research_dataset.parquet')
    print(f'{sym}: {len(df)} rows, {df[\"ts\"].min()} to {df[\"ts\"].max()}')
"

# Check asset readiness
python3 -m tools.asset_audit --all
```

## File Structure

```
data/
  raw_cryptodatadownload/     # Original CSVs from CryptoDataDownload
    Binance_BTCUSDT_1h.csv
    Binance_ETHUSDT_1h.csv
    ...
  
  research_backtest/          # Converted Parquet files (used by research)
    BTCUSDT_1h.parquet
    ETHUSDT_1h.parquet
    ...
```

## How It Works

1. **Download**: Script fetches CSVs from CryptoDataDownload URLs
2. **Convert**: Parses CSV (skips comment lines), extracts OHLCV, converts to Parquet
3. **Merge**: Nightly research automatically merges historical + live data
4. **Analyze**: Analyzer sees deep history for better edge estimates

## Supported Symbols

All 12 coins from `asset_registry.json`:
- BTCUSDT, ETHUSDT, SOLUSDT, AVAXUSDT
- LINKUSDT, MATICUSDT, ATOMUSDT, BNBUSDT
- DOTUSDT, ADAUSDT, XRPUSDT, DOGEUSDT

## Troubleshooting

### "Failed to download"

- Check internet connection
- CryptoDataDownload may be temporarily down
- Try again later or download manually

### "Missing volume column"

- CryptoDataDownload format may have changed
- Check CSV manually: `head -5 data/raw_cryptodatadownload/Binance_BTCUSDT_1h.csv`
- Update converter if needed

### "No static datasets found"

- Verify Parquet files exist: `ls -lh data/research_backtest/*.parquet`
- Check nightly research is looking in right place (should auto-detect)

### "Hybrid dataset still only 200 rows"

- Verify Parquet files were created: `ls -lh data/research_backtest/`
- Check Parquet has data: `python3 -c "import pandas as pd; df = pd.read_parquet('data/research_backtest/BTCUSDT_1h.parquet'); print(len(df))"`
- Re-run nightly research: `python3 -m engine_alpha.reflect.nightly_research`

## Manual Download (Alternative)

If automatic download fails, you can download manually:

1. Visit: https://www.cryptodatadownload.com/data/binance/
2. Download CSV files for each symbol
3. Place in `data/raw_cryptodatadownload/`
4. Run converter only: `python3 -m tools.convert_binance_to_chloe --dir data/raw_cryptodatadownload/ --timeframe 1h`

## Next Steps

After integration:

1. ✅ Verify hybrid datasets have deep history
2. ✅ Review analyzer stats: `cat reports/research/BTCUSDT/multi_horizon_stats.json | jq .`
3. ✅ Compare edge estimates across coins
4. ✅ Identify best candidates for paper trading (after ETH proves herself)

## Benefits

- **Deep History**: Years of Binance data for better edge estimates
- **Regime Analysis**: More data for regime-specific edge detection
- **Multi-Asset**: All 12 coins get rich historical context
- **Automatic**: Nightly research handles merging automatically

Your research pipeline now has access to comprehensive historical data! 🚀


