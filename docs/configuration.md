# Configuration

## Route Configuration File

The route configuration file can be in **JSON** or **YAML** format. YAML files are automatically detected by their `.yaml` or `.yml` extension.

### Top-Level Structure

```json
{
  "defaults": {
    "status": 200,
    "headers": {"Content-Type": "application/json"},
    "latency_ms": 0,
    "failure_rate": 0.0
  },
  "routes": [...]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `defaults` | object | Default values applied to all routes |
| `routes` | array | Array of route definitions |

### Route Definition

```json
{
  "path": "/api/users/:id",
  "method": "GET",
  "status": 200,
  "body": {"id": 1, "name": "Alice"},
  "headers": {"X-Custom": "value"},
  "latency_ms": 100,
  "failure_rate": 0.1
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | string | Yes | URL path, can include `:param` placeholders |
| `method` | string | Yes | HTTP method (GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS) |
| `status` | integer | No | HTTP status code (default: 200) |
| `body` | any | No | Response body (object, array, string, number, etc.) |
| `headers` | object | No | Additional response headers |
| `latency_ms` | number | No | Simulated latency in milliseconds (capped at 60000) |
| `failure_rate` | number | No | Probability of returning 500 error (0.0-1.0) |

### Defaults

```json
{
  "defaults": {
    "status": 200,
    "headers": {"Content-Type": "application/json"},
    "latency_ms": 50,
    "failure_rate": 0.0
  }
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `status` | 200 | Default HTTP status code |
| `headers` | `{"Content-Type": "application/json"}` | Default response headers |
| `latency_ms` | 0 | Default latency in milliseconds |
| `failure_rate` | 0.0 | Default failure injection rate |

### Global CLI Overrides

Command-line flags override per-route settings:

- `--latency MS` — Overrides all per-route `latency_ms`
- `--failure-rate RATE` — Overrides all per-route `failure_rate`
