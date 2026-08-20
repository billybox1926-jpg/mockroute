# Changelog

All notable changes to this project will be documented in this file.

## [0.7.0] - 2026-08-19

### Added
- Enhanced templating with conditionals (`{{#if key}}...{{/if}}`) and loops (`{{#each items}}...{{/each}}`)
- Query parameter matching (`match_query` field)
- Request body matching (`match_body` field)
- YAML config support (auto-detected by `.yaml`/`.yml` extension)
- Type preservation for full-placeholder substitutions (`{{body}}` keeps objects as objects)

### Fixed
- Boolean normalization (bool not conflated with int)
- Properties parser escape sequences

## [0.6.0] - 2026-08-19

### Added
- Config validation with detailed error messages
- Rate limiting (per-IP, configurable requests per minute)
- CORS configuration (`--cors-origin` flag)
- Verbose mode (`--flag` for detailed request/response logging)

## [0.5.0] - 2026-08-19

### Added
- OpenAPI 3.0 spec import (`--openapi` flag)
- Automatic route generation from OpenAPI paths and methods

## [0.4.0] - 2026-08-19

### Added
- Dynamic responses with `{{param}}` template placeholders
- Path, query, and request body variable injection

## [0.3.0] - 2026-08-19

### Added
- Swagger UI server at `/docs`
- OpenAPI 3.0 spec generation from routes
- Raw spec endpoint at `/openapi.json`

## [0.2.0] - 2026-08-19

### Added
- Path parameters (`/users/:id`) with regex-based matching
- PyPI packaging with `pyproject.toml`
- Colored request logging (method/status code colorized)
- `--no-color` flag to disable colors

## [0.1.0] - 2026-08-19

### Added
- Initial release
- Zero-dependency local mock API server
- JSON route configuration
- Configurable latency and failure injection
- CORS support
- HEAD request support
- ThreadingHTTPServer for concurrent requests
