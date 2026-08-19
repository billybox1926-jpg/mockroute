# CORS Configuration

mockroute supports Cross-Origin Resource Sharing (CORS) with configurable allowed origins.

## Quick Start

```bash
# Allow all origins (default)
python mockroute.py --config routes.json

# Allow specific origin
python mockroute.py --config routes.json --cors-origin "http://localhost:3000"

# Disable CORS entirely
python mockroute.py --config routes.json --no-cors
```

## CORS Headers

When CORS is enabled, the following headers are included in responses:

```
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, PUT, DELETE, PATCH, OPTIONS
Access-Control-Allow-Headers: Content-Type, Authorization
```

## Preflight Requests

mockroute handles `OPTIONS` preflight requests automatically:

- Returns 204 No Content
- Includes all CORS headers
- No body in response

## Configuration

| Flag | Default | Description |
|------|---------|-------------|
| `--cors-origin` | `*` | Allowed CORS origin |
| `--no-cors` | `false` | Disable CORS headers |

## Example: Development Setup

```bash
# Allow your frontend dev server
python mockroute.py --config routes.json --cors-origin "http://localhost:5173"

# Or allow all origins (default, suitable for local dev)
python mockroute.py --config routes.json
```
