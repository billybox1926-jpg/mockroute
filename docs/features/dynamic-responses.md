# Dynamic Responses

Dynamic responses allow you to use request data in your mock responses using template placeholders.

## Basic Placeholders

Use `{{param}}` syntax to inject values from the request:

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

## Available Context

| Context | Description | Example |
|---------|-------------|---------|
| `path` | Path parameters | `{{path.id}}` |
| `query` | Query parameters | `{{query.q}}` |
| `body` | Request body | `{{body}}` |

## Nested Access

Use dot notation to access nested values:

```json
{
  "path": "/api/echo",
  "method": "POST",
  "status": 200,
  "body": {"user": "{{body.user.name}}", "email": "{{body.user.email}}"}
}
```

## Array Index Access

Access array elements by index:

```json
{
  "body": {"first": "{{body.items.0}}", "second": "{{body.items.1}}"}
}
```

## Type Preservation

When the entire string is a single placeholder, the original type is preserved:

```json
{"body": {"echo": "{{body}}"}}
```

If `body` is an object, it remains an object. If it's a number, it remains a number.

When the placeholder is embedded in a string, the value is converted to a string:

```json
{"body": {"message": "Hello {{path.name}}!"}}
```

## Missing Parameters

If a parameter is not found, the placeholder is left unchanged:

```json
{"body": {"msg": "Hello {{unknown}}!"}}
```

Response: `{"msg": "Hello {{unknown}}!"}`
