# OpenAPI Import

Generate mock routes directly from an OpenAPI 3.0 specification.

## Quick Start

```bash
# Import routes from OpenAPI spec
python mockroute.py --openapi api-spec.json --port 8000
```

## Supported Features

- **Paths** — All paths are imported
- **Methods** — GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS
- **Path Parameters** — Converted from `{id}` to `:id` format
- **Response Examples** — Extracted from `example` or `examples` fields
- **Status Codes** — First 2xx response is used
- **Content Types** — JSON and text/plain are supported

## Example OpenAPI Spec

```json
{
  "openapi": "3.0.0",
  "info": {"title": "Pet Store API", "version": "1.0.0"},
  "paths": {
    "/pets": {
      "get": {
        "summary": "List all pets",
        "responses": {
          "200": {
            "description": "A list of pets",
            "content": {
              "application/json": {
                "example": [{"id": 1, "name": "Fluffy"}]
              }
            }
          }
        }
      },
      "post": {
        "summary": "Create a pet",
        "responses": {
          "201": {
            "description": "Pet created",
            "content": {
              "application/json": {
                "example": {"id": 2, "name": "Rex"}
              }
            }
          }
        }
      }
    },
    "/pets/{petId}": {
      "get": {
        "summary": "Get a pet by ID",
        "parameters": [{"name": "petId", "in": "path", "required": true}],
        "responses": {
          "200": {
            "description": "A pet",
            "content": {
              "application/json": {
                "example": {"id": 1, "name": "Fluffy"}
              }
            }
          }
        }
      }
    }
  }
}
```

This generates the following routes:

```json
{
  "routes": [
    {"path": "/pets", "method": "GET", "status": 200, "body": [{"id": 1, "name": "Fluffy"}]},
    {"path": "/pets", "method": "POST", "status": 201, "body": {"id": 2, "name": "Rex"}},
    {"path": "/pets/:petId", "method": "GET", "status": 200, "body": {"id": 1, "name": "Fluffy"}}
  ]
}
```

## Conversion Rules

| OpenAPI Format | mockroute Format |
|----------------|------------------|
| `/pets/{petId}` | `/pets/:petId` |
| `200` response with example | Route with status 200 and body |
| `examples` field (multiple) | First example's `value` is used |
| No example | Body is `null` |

## Limitations

- Only JSON and text/plain content types are imported
- Only the first 2xx response is used
- Request body schemas are not imported
- Authentication is not imported
