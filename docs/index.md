# mockroute

**Zero-dependency local mock API server.**

Point it at a JSON or YAML route file, and it serves fake responses with configurable latency, failure injection, CORS support, path parameters, dynamic responses, templating, Swagger UI documentation, and OpenAPI import.

## Quick Start

```bash
# Clone and run
git clone https://github.com/billybox1926-jpg/mockroute.git
cd mockroute
python mockroute.py --config routes.example.json --port 8000

# Build and install locally
pip install build
python -m build
pip install dist/mockroute-0.7.0-py3-none-any.whl
mockroute --help
```

## Features

- **Zero dependencies** — Python 3.9+ stdlib only
- **Path parameters** — `/users/:id` with regex-based matching
- **Dynamic responses** — `{{param}}` templating with conditionals and loops
- **Query matching** — Route based on query parameters
- **Body matching** — Route based on request body content
- **Rate limiting** — Per-IP, configurable requests per minute
- **CORS configuration** — Configurable allowed origins
- **OpenAPI import** — Generate routes from OpenAPI 3.0 specs
- **Swagger UI** — Interactive API docs at `/docs`
- **YAML support** — Auto-detected by file extension
- **Colored logging** — Method and status code colorized output

## Configuration

```json
{
  "defaults": {
    "status": 200,
    "headers": {"Content-Type": "application/json"},
    "latency_ms": 0,
    "failure_rate": 0.0
  },
  "routes": [
    {
      "path": "/health",
      "method": "GET",
      "status": 200,
      "body": {"status": "ok"}
    },
    {
      "path": "/api/users/:id",
      "method": "GET",
      "status": 200,
      "body": {"id": "{{path.id}}", "name": "User {{path.id}}"}
    }
  ]
}
```

## CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--config` | `routes.json` | Route definition file (JSON or YAML) |
| `--openapi` | `None` | Import routes from OpenAPI 3.0 spec |
| `--port` | `8000` | Port to listen on |
| `--host` | `127.0.0.1` | Bind address |
| `--verbose` | `false` | Extra debug logging |
| `--no-cors` | `false` | Disable CORS headers |
| `--no-color` | `false` | Disable colored output |
| `--no-docs` | `false` | Disable Swagger UI at /docs |
| `--cors-origin` | `*` | Allowed CORS origin |
| `--rate-limit` | `100` | Max requests per minute per IP |
| `--latency` | `None` | Global latency override (ms) |
| `--failure-rate` | `None` | Global failure rate override (0.0-1.0) |

## Documentation

Full documentation is available at [https://billybox1926-jpg.github.io/mockroute/](https://billybox1926-jpg.github.io/mockroute/).

## License

MIT
