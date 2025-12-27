# Glassnode On-Chain Data Integration

Chloe now supports Glassnode on-chain metrics integrated into the research pipeline.

## Quick Start

### 1. Configure API Key

Edit `config/glassnode_config.json` and replace `YOUR_GLASSNODE_API_KEY_HERE` with your actual API key:

```json
{
  "api_key": "your-actual-api-key-here",
  ...
}
```

### 2. Fetch Initial Data

For ETHUSDT and BTCUSDT:

```bash
python3 -m tools.fetch_glassnode_data --symbol ETHUSDT
python3 -m tools.fetch_glassnode_data --symbol BTCUSDT
```

Or fetch for all enabled assets:

```bash
python3 -m tools.fetch_glassnode_data --all
```

This will:
- Fetch 365 days of configured metrics
- Cache to `data/glassnode/{SYMBOL}_glassnode.parquet`
- Metrics are automatically merged into hybrid research datasets

### 3. Automatic Updates

Glassnode metrics are automatically fetched during nightly research:

```bash
python3 -m engine_alpha.reflect.nightly_research
```

The nightly pipeline will:
1. Fetch fresh Glassnode data for each symbol
2. Build hybrid datasets (which include Glassnode columns)
3. Run analyzer/tuner with on-chain context

## Configuration

### Adding More Metrics

Edit `config/glassnode_config.json`:

```json
{
  "metrics": {
    "exchange_netflow": "/flow/exchange/net",
    "addresses_active": "/addresses/active_count",
    "your_new_metric": "/path/to/glassnode/endpoint"
  }
}
```

### Adding More Assets

Edit `config/glassnode_config.json`:

```json
{
  "assets": {
    "BTCUSDT": "BTC",
    "ETHUSDT": "ETH",
    "SOLUSDT": "SOL"
  }
}
```

## How It Works

1. **Fetch**: `glassnode_fetcher.py` calls Glassnode API and caches to Parquet
2. **Merge**: `research_dataset_builder.py` automatically merges cached metrics into hybrid datasets
3. **Analyze**: Analyzer sees `gn_exchange_netflow`, `gn_addresses_active` columns
4. **Learn**: Chloe can discover patterns like "high exchange netflow + high_vol = bad for longs"

## File Structure

```
config/
  glassnode_config.json          # API key + asset/metric mappings

data/
  glassnode/
    ETHUSDT_glassnode.parquet     # Cached metrics per symbol
    BTCUSDT_glassnode.parquet

engine_alpha/data/
  glassnode_client.py             # Thin API client
  glassnode_fetcher.py            # Fetch + cache logic

reports/research/{SYMBOL}/
  hybrid_research_dataset.parquet # Includes Glassnode columns
```

## Column Naming

Glassnode metrics are prefixed with `gn_`:
- `gn_exchange_netflow` - Exchange net flow
- `gn_addresses_active` - Active addresses count

## Troubleshooting

### "API key is missing"
- Check `config/glassnode_config.json` has a valid API key
- Ensure the key is not the placeholder `YOUR_GLASSNODE_API_KEY_HERE`

### "No Glassnode asset mapping found"
- Add your symbol to `assets` mapping in `glassnode_config.json`
- Use Glassnode's asset code (BTC, ETH, etc.)

### "No Glassnode metrics available"
- Metrics are optional - research still works without them
- Check API key is valid and has access to requested metrics
- Verify metric endpoints exist in Glassnode API

## Next Steps

Once Glassnode data is flowing:

1. **Extend Strategy Cards**: Add `onchain_filter` blocks to strategies
2. **Quant Gate Integration**: Use on-chain signals in `gate_and_size_trade()`
3. **Meta-Strategy Reflection**: Include on-chain context in strategic analysis

Example future strategy filter:

```json
{
  "onchain_filter": {
    "gn_exchange_netflow": "< 0",
    "gn_addresses_active": "> 10000"
  }
}
```


