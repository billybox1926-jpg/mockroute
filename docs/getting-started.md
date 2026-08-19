# Getting Started

## Installation

### From Source

```bash
git clone https://github.com/billybox1926-jpg/mockroute.git
cd mockroute
python mockroute.py --config routes.example.json --port 8000
```

### Build and Install

```bash
pip install build
python -m build
pip install dist/mockroute-0.7.0-py3-none-any.whl
mockroute --help
```

## Quick Start

1. **Create a route configuration file** (`routes.json`):

```json
{
  "defaults": {
    "status": 200,
    "headers": {"Content-Type": "application/json"}
  },
  "routes": [
    {
      "path": "/health",
      "method": "GET",
      "status": 200,
      "body": {"status": "ok"}
    },
    {
      "path": "/api/users",
      "method": "GET",
      "status": 200,
      "body": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
    },
    {
      "path": "/api/users/:id",
      "method": "GET",
      "status": 200,
      "body": {"id": 1, "name": "Alice"}
    }
  ]
}
```

2. **Start the server**:

```bash
python mockroute.py --config routes.json --port 8000
```

3. **Test it**:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/users
curl http://localhost:8000/api/users/123
```

4. **View Swagger UI**: Open http://localhost:8000/docs in your browser.

## CLI Options

```
--config PATH          Route definition file (JSON or YAML)
--openapi PATH         Import routes from OpenAPI 3.0 spec
--port PORT            Port to listen on (default: 8000)
--host HOST            Bind address (default: 127.0.0.1)
--verbose              Enable debug logging
--no-cors              Disable CORS headers
--no-color             Disable colored output
--no-docs              Disable Swagger UI at /docs
--cors-origin ORIGIN   Allowed CORS origin (default: *)
--rate-limit LIMIT     Max requests per minute per IP (default: 100)
--latency MS           Global latency override in ms
--failure-rate RATE    Global failure rate override (0.0-1.0)
--version              Show version and exit
--help                 Show help and exit
```
