# Chloe Alpha API

Read-only FastAPI service providing dashboard data for Chloe Alpha.

## Quick Start

### Development
```bash
cd /root/Chloe-alpha
source venv/bin/activate
python -m engine_alpha.api.app
```

API will be available at `http://127.0.0.1:8000`

### Production
```bash
# Install service
sudo cp systemd/chloe_api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable chloe_api
sudo systemctl start chloe_api

# Check status
sudo systemctl status chloe_api
```

## Authentication

Set `CHLOE_API_TOKEN` environment variable to enable authentication:

```bash
# In systemd/chloe_api.env
CHLOE_API_TOKEN=your-secure-token-here
```

Send token in requests:
```bash
curl -H "X-CHLOE-TOKEN: your-secure-token-here" http://localhost:8001/health
```

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Loop health status |
| `/pf` | GET | Profit factor data |
| `/positions` | GET | Current positions |
| `/symbols` | GET | Symbol trading states |
| `/features` | GET | Feature audit data |
| `/promotion/advice` | GET | GPT promotion advice |
| `/promotion/queue` | GET | Shadow promotion queue |
| `/trades/recent` | GET | Recent trades (params: `hours`, `limit`) |
| `/meta/log_sizes` | GET | Log file sizes/metadata |

## API Documentation

When running, visit `/docs` for interactive OpenAPI documentation.

## Security

- **Read-only**: No trading or modification endpoints
- **Whitelisted files**: Only approved report files accessible
- **Rate limiting**: 60 requests/minute per IP
- **Token auth**: Optional but recommended
- **CORS**: Configured for dashboard access

## Dependencies

```bash
pip install fastapi uvicorn python-multipart
```

## Testing

```bash
python -m pytest tests/api/
```
