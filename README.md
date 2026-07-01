# AutoClaw Proxy

Proxy server for AutoClaw API with native tool calling support, token rotation, and automatic token refresh.

## Features

- **Tool Calling** - Full function/tool calling support via GLM models
- **Sticky Routing** - Session-based account routing for 96%+ cache hit rates
- **Token Rotation** - Automatic load balancing across multiple accounts
- **Auto-refresh** - Background token refresh every hour
- **Health Monitoring** - Track account health with auto-recovery
- **Docker Ready** - Containerized deployment support

## Quick Start

### Manual Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Run proxy
python proxy.py
```

Server runs on `http://localhost:8070`

### Docker Deployment

```bash
docker-compose up -d
```

## Configuration

### Accounts Setup

Create `autoclaw_accounts.json` file with your account credentials:

```json
[
  {
    "email": "your-email@example.com",
    "device_id": "your-device-id",
    "access_token": "your-access-token",
    "refresh_token": "your-refresh-token",
    "balance": 0
  }
]
```

**To register AutoClaw accounts and generate this file:**
https://github.com/Ryzzkiaa/autoclaw-register

This file is automatically excluded from git tracking.

### API Authentication (Optional)

Enable API key authentication by setting an environment variable:

```bash
export API_KEY="your-secret-key"
python proxy.py
```

If not set, the proxy accepts all requests without authentication.

### Routing Strategy

The proxy supports configurable account routing strategies via the `ROUTING_STRATEGY` environment variable.

#### Sticky Routing (Recommended)

Routes requests from the same session to the same account, maximizing prompt cache hits.

```bash
export ROUTING_STRATEGY=sticky
python proxy.py
```

**Benefits:**
- **96%+ cache hit rate** for repeated contexts
- **64-74% cost savings** on long conversations
- **Faster responses** (cached tokens process instantly)
- **Load balanced** across different sessions/users

**How it works:**
- Uses consistent hashing on the `Authorization` header or `X-Session-ID`
- Same API key/session → same account → cache reused
- Different API keys/sessions → different accounts → load distributed

**Performance:**

| Metric | Sticky Routing | Least-Used |
|--------|----------------|------------|
| Cache hit rate | 96.7% | ~1.7% |
| Cost per 100 requests (500 tokens) | $0.0018 | $0.007 |
| Response latency | Fast (cached) | Normal |
| Use case | Conversations, repeated contexts | Short one-off requests |

#### Least-Used Routing

Distributes load evenly across all accounts (legacy LRU behavior).

```bash
export ROUTING_STRATEGY=least-used
python proxy.py
```

**When to use:**
- Short, non-repetitive prompts
- Maximum load distribution needed
- No conversation context to cache

**Docker Configuration:**

```yaml
environment:
  - ROUTING_STRATEGY=sticky  # or least-used
```

## Usage

### Supported Models

| Model | Internal Name | Tool Calling | Description |
|-------|--------------|--------------|-------------|
| `glm-5.2` | `openrouter_glm-5.2` | Yes | Best quality, recommended |
| `glm-5-turbo` | `zai_glm-5-turbo` | Yes | Faster, more economical |
| `deepseek-v4-pro` | `zai_auto` | Yes | DeepSeek Pro variant |
| `deepseek-v4` | `zai_auto` | Yes | DeepSeek base variant |
| `auto` | `zai_auto` | Yes | Auto mode (free during promo period) |

**Note:** All models support native tool calling. DeepSeek models stream function arguments more granularly.

### Basic Chat Example

```python
import requests

response = requests.post("http://localhost:8070/v1/chat/completions", json={
    "model": "glm-5.2",
    "messages": [
        {"role": "user", "content": "Hello!"}
    ]
})

print(response.json())
```

### Streaming Example

```python
import requests

response = requests.post(
    "http://localhost:8070/v1/chat/completions",
    json={
        "model": "glm-5.2",
        "messages": [{"role": "user", "content": "Count to 10"}],
        "stream": True
    },
    stream=True
)

for line in response.iter_lines():
    if line:
        print(line.decode('utf-8'))
```

## Tool Calling

All supported models include native function calling capabilities.

### Complete Example

```python
import requests
import json

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather information",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City name"
                    }
                },
                "required": ["location"]
            }
        }
    }
]

response = requests.post(
    "http://localhost:8070/v1/chat/completions",
    json={
        "model": "glm-5.2",
        "messages": [
            {"role": "user", "content": "What's the weather in Jakarta?"}
        ],
        "tools": tools,
        "stream": True
    },
    stream=True
)

# Parse Server-Sent Events stream
for line in response.iter_lines():
    if line:
        line = line.decode('utf-8')
        if line.startswith('data: '):
            data_str = line[6:]
            if data_str == '[DONE]':
                break
            try:
                data = json.loads(data_str)
                delta = data['choices'][0].get('delta', {})
                
                if 'tool_calls' in delta:
                    print("Tool call detected:", delta['tool_calls'])
            except json.JSONDecodeError:
                pass
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/chat/completions` | POST | Chat completions with tool calling support |
| `/v1/models` | GET | List available models |
| `/health` | GET | Health check and account statistics |
| `/` | GET | Service information |

### Health Check

```bash
curl http://localhost:8070/health
```

Example response:
```json
{
  "status": "healthy",
  "accounts": {
    "total": 10,
    "healthy": 10,
    "unhealthy": 0
  },
  "total_balance": 50000
}
```

## Architecture

```
Client Application
    |
    v
Proxy Server (Flask) - Port 8070
    |-- Token Rotation (least recently used)
    |-- Health Monitoring (automatic failure detection)
    |-- Auto-refresh (background worker thread)
    |-- Tool Calling (native pass-through)
    |-- Load Balancing (round-robin distribution)
    v
AutoClaw API
    |
    v
GLM-5.2 / GLM-5-turbo / DeepSeek Models
```

## Docker Deployment

### Build and Start

```bash
docker-compose build
docker-compose up -d
```

### View Logs

```bash
docker-compose logs -f
```

### Stop Services

```bash
docker-compose down
```

### Update Account Configuration

After editing `autoclaw_accounts.json`:

```bash
docker-compose restart
```

## Advanced Configuration

Modify `proxy.py` for custom settings:

```python
# Token refresh interval (seconds)
TOKEN_REFRESH_INTERVAL = 3600  # 1 hour default

# Custom model mapping
MODEL_MAP = {
    "glm-5.2": "openrouter_glm-5.2",
    "glm-5-turbo": "zai_glm-5-turbo",
    "custom-model": "internal-model-name",
}
```

## Troubleshooting

### Tool Calling Issues

Verify the following:
1. Using a supported model (`glm-5.2`, `glm-5-turbo`, `deepseek-v4-pro`, `deepseek-v4`)
2. Request payload includes `tools` parameter
3. Server-Sent Events stream is parsed correctly

### Account Health Problems

Check proxy health status:
```bash
curl http://localhost:8070/health
```

Restart the proxy to trigger recovery:
```bash
pkill -f proxy.py
python proxy.py
```

### Token Expiration

Tokens refresh automatically every hour. For manual refresh:
```bash
python refresh_all.py
```

### Port Conflicts

Check for processes using port 8070:
```bash
lsof -i :8070
```

Terminate conflicting process:
```bash
kill <PID>
```

## Project Structure

| File | Purpose |
|------|---------|
| `proxy.py` | Main proxy server implementation |
| `autoclaw_accounts.json` | Account credentials (not tracked by git) |
| `refresh_all.py` | Manual token refresh utility |
| `requirements.txt` | Python dependencies |
| `.env.example` | Environment variable template |
| `.gitignore` | Git exclusion rules |
| `Dockerfile` | Container build configuration |
| `docker-compose.yml` | Docker Compose orchestration |

## Technical Notes

- Automatic token refresh runs every hour via background thread
- Accounts failing 3 consecutive requests are marked unhealthy
- Unhealthy accounts automatically recover during next refresh cycle
- Account credentials file updates automatically on successful token refresh
- All supported models (GLM-5.2, GLM-5-turbo, DeepSeek v4 variants) include native tool calling

## License

MIT License
