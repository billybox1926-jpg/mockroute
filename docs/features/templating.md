# Templating

## Conditionals

Use `{{#if key}}content{{/if}}` to conditionally include content based on request data:

```json
{
  "body": {
    "admin": "{{#if body.user.admin}}yes{{/if}}",
    "role": "{{#if path.id}}user{{/if}}"
  }
}
```

- If the key resolves to a truthy value, the content is included
- If the key is missing or falsy, the content is omitted

## Loops

Use `{{#each items}}content{{/each}}` to iterate over arrays:

```json
{
  "body": {
    "items": "{{#each body.items}}{{this}},{{/each}}"
  }
}
```

- `{{this}}` refers to the current item in the loop
- Each item is rendered with the template content
- Empty arrays render as empty strings

## Combined Example

```json
{
  "body": {
    "message": "Hello {{path.name}}!",
    "items": "{{#each body.items}}{{this}},{{/each}}",
    "admin": "{{#if body.admin}}yes{{/if}}"
  }
}
```

## Nesting

Conditionals and loops can be nested:

```json
{
  "body": {
    "result": "{{#if body.items}}{{#each body.items}}{{this}},{{/each}}{{/if}}"
  }
}
```
