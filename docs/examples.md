# Examples

## REST API Mock

A complete REST API mock with CRUD operations:

```json
{
  "defaults": {
    "status": 200,
    "headers": {"Content-Type": "application/json"}
  },
  "routes": [
    {
      "path": "/api/users",
      "method": "GET",
      "status": 200,
      "body": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
    },
    {
      "path": "/api/users",
      "method": "POST",
      "status": 201,
      "body": {"id": 3, "name": "Charlie"}
    },
    {
      "path": "/api/users/:id",
      "method": "GET",
      "status": 200,
      "body": {"id": "{{path.id}}", "name": "User {{path.id}}"}
    },
    {
      "path": "/api/users/:id",
      "method": "PUT",
      "status": 200,
      "body": {"id": "{{path.id}}", "name": "Updated"}
    },
    {
      "path": "/api/users/:id",
      "method": "DELETE",
      "status": 204
    }
  ]
}
```

## Dynamic Responses with Templating

```json
{
  "routes": [
    {
      "path": "/api/echo",
      "method": "POST",
      "status": 200,
      "body": {"echo": "{{body}}", "type": "{{#if body.admin}}admin{{/if}}"}
    },
    {
      "path": "/api/search",
      "method": "GET",
      "status": 200,
      "body": {"query": "{{query.q}}", "results": []}
    }
  ]
}
```

## Query-Based Routing

```json
{
  "routes": [
    {
      "path": "/api/users",
      "method": "GET",
      "match_query": {"role": "admin"},
      "status": 200,
      "body": [{"id": 1, "name": "Admin User"}]
    },
    {
      "path": "/api/users",
      "method": "GET",
      "status": 200,
      "body": [{"id": 2, "name": "Regular User"}]
    }
  ]
}
```

## Latency and Failure Injection

```json
{
  "routes": [
    {
      "path": "/api/slow",
      "method": "GET",
      "status": 200,
      "body": {"message": "This is slow"},
      "latency_ms": 500
    },
    {
      "path": "/api/unreliable",
      "method": "GET",
      "status": 200,
      "body": {"message": "Sometimes fails"},
      "failure_rate": 0.3
    }
  ]
}
```

## YAML Configuration

```yaml
defaults:
  status: 200
  headers:
    Content-Type: application/json

routes:
  - path: /health
    method: GET
    status: 200
    body:
      status: ok

  - path: /api/users/:id
    method: GET
    status: 200
    body:
      id: "{{path.id}}"
      name: "User {{path.id}}"
```

## OpenAPI Import

```bash
# Import from OpenAPI spec
python mockroute.py --openapi petstore.json --port 8000

# View generated routes
open http://localhost:8000/docs
```
