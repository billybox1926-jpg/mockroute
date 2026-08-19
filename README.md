# mockroute

**Zero-dependency local mock API server.**

Point it at a JSON route file, and it serves fake responses with configurable latency, failure injection, CORS support, and path parameters. Ideal for frontend development, agent-driven tests, and prototyping without a real backend.

## Features

- **Zero dependencies** — Python 3.9+ stdlib only
- **Single-file CLI** — `mockroute.py`
- **JSON route configuration** — define paths, methods, status codes, headers, and response bodies
- **Path parameters** — use `:id` syntax to capture URL segments (`/users/:id`)
- **Configurable latency** — per-route or global override
- **Failure injection** — randomly return 500 errors at a configurable rate
- **CORS support** — automatic preflight handling and permissive headers
- **Threaded server** — handles concurrent requests
- **Colored output** — method and status codes colorized for readability

## Quick Start

```bash
# Clone the repo
git clone https://github.com/billybox1926-jpg/mockroute.git
cd mockroute

# Create a route config (or use the example)
cp routes.example.json routes.json

# Start the server
python mockroute.py --config routes.json --port 8000
```

## PyPI Installation

```bash
# Build the package
pip install build
python -m build

# Install locally
pip install dist/mockroute-0.2.0-py3-none-any.whl

# Run from anywhere
mockroute --help
```

## Usage

```bash
python mockroute.py --help
python mockroute.py --version
python mockroute.py --config routes.json --port 8000
python mockroute.py --config routes.json --port 8000 --verbose
python mockroute.py --config routes.json --port 8000 --no-cors
python mockroute.py --config routes.json --port 8000 --no-color
python mockroute.py --config routes.json --port 8000 --latency 100
python mockroute.py --config routes.json --port 8000 --failure-rate 0.1
```

### CLI Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--config` | `routes.json` | Route definition file |
| `--port` | `8000` | Port to listen on |
| `--host` | `127.0.0.1` | Bind address |
| `--verbose` | `false` | Extra debug logging |
| `--no-cors` | `false` | Disable CORS headers |
| `--no-color` | `false` | Disable colored output |
| `--latency` | `None` | Global latency override (ms) |
| `--failure-rate` | `None` | Global failure rate override (0.0–1.0) |

## Route Configuration

Create a `routes.json` file:

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
      "body": {"status": "ok"},
      "headers": {"Content-Type": "application/json"},
      "latency_ms": 50,
      "failure_rate": 0.0
    },
    {
      "path": "/api/users",
      "method": "GET",
      "status": 200,
      "body": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}],
      "latency_ms": 200,
      "failure_rate": 0.1
    },
    {
      "path": "/api/users/:id",
      "method": "GET",
      "status": 200,
      "body": {"id": 1, "name": "Alice"},
      "latency_ms": 100,
      "failure_rate": 0.0
    }
  ]
}
```

### Configuration Options

- **`defaults`** (optional) — applied to routes that don't override the field
- **`routes`** — array of route definitions
  - `path` — URL path (use `:param` for path parameters)
  - `method` — HTTP method (GET, POST, PUT, DELETE, PATCH, OPTIONS, HEAD)
  - `status` — HTTP status code (default: 200)
  - `body` — response body (any JSON value; strings sent as text, others as JSON)
  - `headers` — additional response headers
  - `latency_ms` — artificial delay in milliseconds
  - `failure_rate` — probability of returning 500 (0.0 to 1.0)

### Path Parameters

Use `:param` syntax in paths to capture dynamic segments:

```json
{"path": "/api/users/:id", "method": "GET"}
{"path": "/api/users/:id/posts/:postId", "method": "GET"}
```

Captured parameters are logged alongside the request.

## Example Session

```bash
$ python mockroute.py --config routes.json --port 8000
mockroute v0.2.0 serving on http://127.0.0.1:8000
Loaded 4 routes from routes.json
Press Ctrl+C to stop

GET     /health                              200    50ms   50.2ms
GET     /api/users                           200   200ms  200.5ms
GET     /api/users/123                       200   100ms  100.3ms  /api/users/:id (id=123)
POST    /api/users                           201   300ms  300.3ms
GET     /unknown                             404     0ms    0.1ms
```

## Testing

```bash
python -m pytest tests/ -v
```

## License

MIT License. See [LICENSE](LICENSE) for details.
