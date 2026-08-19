# Path Parameters

Path parameters allow you to define dynamic URL segments that capture values from the request path.

## Basic Usage

Use the `:param` syntax in your route path:

```json
{
  "path": "/api/users/:id",
  "method": "GET",
  "status": 200,
  "body": {"id": "{{path.id}}", "name": "User {{path.id}}"}
}
```

Request: `GET /api/users/123`

Response: `{"id": "123", "name": "User 123"}`

## Multiple Parameters

You can have multiple parameters in a single path:

```json
{
  "path": "/api/users/:id/posts/:postId",
  "method": "GET",
  "status": 200,
  "body": {"userId": "{{path.id}}", "postId": "{{path.postId}}"}
}
```

Request: `GET /api/users/42/posts/7`

Response: `{"userId": "42", "postId": "7"}`

## Naming Conventions

- Must start with a letter or underscore
- Can contain letters, numbers, and underscores
- Case-sensitive

```json
{"path": "/api/:user_id", "method": "GET"}
{"path": "/api/:userId", "method": "GET"}
{"path": "/api/:UserName", "method": "GET"}
```

## How It Works

Path parameters use regex-based pattern matching. When the server starts, each route path is compiled into a regex pattern:

- `/api/users/:id` becomes `^/api/users/(?P<id>[^/]+)$`
- `/api/users/:id/posts/:postId` becomes `^/api/users/(?P<id>[^/]+)/posts/(?P<postId>[^/]+)$`

This means:
- Each parameter matches one or more non-slash characters
- Parameters cannot span across path segments
- The entire path must match (no partial matches)
