# Swagger UI

mockroute automatically generates an OpenAPI 3.0 specification from your routes and serves it via Swagger UI.

## Quick Start

```bash
# Start the server (docs enabled by default)
python mockroute.py --config routes.json --port 8000

# View docs
open http://localhost:8000/docs
```

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/docs` | GET | Swagger UI interface |
| `/docs/` | GET | Swagger UI interface (trailing slash) |
| `/openapi.json` | GET | Raw OpenAPI 3.0 specification |

## Disabling Docs

```bash
python mockroute.py --config routes.json --no-docs
```

## What's Included

The generated OpenAPI spec includes:

- All routes with their paths, methods, and status codes
- Path parameters with proper OpenAPI parameter definitions
- Response examples from route body definitions
- Proper content types (application/json or text/plain)

## Example

Given this route configuration:

```json
{
  "routes": [
    {
      "path": "/api/users/:id",
      "method": "GET",
      "status": 200,
      "body": {"id": 1, "name": "Alice"}
    }
  ]
}
```

The generated OpenAPI spec will include:

```json
{
  "openapi": "3.0.0",
  "info": {"title": "Mock API", "version": "0.7.0"},
  "paths": {
    "/api/users/{id}": {
      "get": {
        "summary": "GET /api/users/:id",
        "parameters": [
          {"name": "id", "in": "path", "required": true, "schema": {"type": "string"}}
        ],
        "responses": {
          "200": {
            "description": "Response for GET /api/users/:id",
            "content": {
              "application/json": {
                "example": {"id": 1, "name": "Alice"}
              }
            }
          }
        }
      }
    }
  }
}
```

## Hosting on GitHub Pages

You can host your API documentation alongside your GitHub Pages site. The Swagger UI loads from CDN, so no build step is required for the UI itself.
