#!/usr/bin/env python3
"""
mockroute - Zero-dependency local mock API server.

Point it at a JSON route file, and it serves fake responses with
configurable latency, failure injection, CORS support, path parameters,
dynamic responses, Swagger UI documentation, and OpenAPI import.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import threading
import time
import urllib.parse
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

__version__ = "0.6.0"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_CONFIG = "routes.json"
MAX_LATENCY_MS = 60000  # Cap latency to prevent thread exhaustion (60 seconds)
DEFAULT_RATE_LIMIT = 100  # Requests per minute per IP

# Swagger UI HTML (loads from CDN)
SWAGGER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{title} - API Docs</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
    <style>
        body {{ margin: 0; padding: 0; }}
        .topbar {{ display: none; }}
    </style>
</head>
<body>
    <div id="swagger-ui"></div>
    <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script>
        window.ui = SwaggerUIBundle({{
            url: "/openapi.json",
            dom_id: "#swagger-ui",
            presets: [
                SwaggerUIBundle.presets.apis,
                SwaggerUIBundle.SwaggerUIStandalonePreset,
            ],
            layout: "BaseLayout"
        }});
    </script>
</body>
</html>"""


class Colors:
    """ANSI color codes for terminal output."""

    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"
    GRAY = "\033[90m"
    RESET = "\033[0m"
    BOLD = "\033[1m"

    @classmethod
    def disable(cls) -> None:
        """Disable all colors (for --no-color flag)."""
        cls.GREEN = cls.YELLOW = cls.RED = cls.BLUE = ""
        cls.CYAN = cls.MAGENTA = cls.GRAY = cls.RESET = cls.BOLD = ""


# Method-to-color mapping
METHOD_COLORS = {
    "GET": Colors.GREEN,
    "POST": Colors.BLUE,
    "PUT": Colors.YELLOW,
    "DELETE": Colors.RED,
    "PATCH": Colors.CYAN,
    "HEAD": Colors.MAGENTA,
    "OPTIONS": Colors.GRAY,
}


class RateLimiter:
    """Simple in-memory rate limiter using token bucket algorithm."""

    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def is_allowed(self, client_ip: str) -> bool:
        """Check if request from client_ip is allowed."""
        now = time.monotonic()
        with self._lock:
            # Clean old entries
            self._requests[client_ip] = [
                t for t in self._requests[client_ip] if now - t < self.window_seconds
            ]
            # Check limit
            if len(self._requests[client_ip]) >= self.max_requests:
                return False
            # Record request
            self._requests[client_ip].append(now)
            return True


def validate_route(route: dict, index: int) -> list[str]:
    """Validate a route definition. Returns list of error messages."""
    errors = []

    # Check required fields
    if "path" not in route:
        errors.append(f"Route {index}: missing required field 'path'")
    elif not isinstance(route["path"], str):
        errors.append(f"Route {index}: 'path' must be a string")
    elif not route["path"].startswith("/"):
        errors.append(f"Route {index}: 'path' must start with /")

    if "method" not in route:
        errors.append(f"Route {index}: missing required field 'method'")
    elif not isinstance(route["method"], str):
        errors.append(f"Route {index}: 'method' must be a string")
    elif route["method"].upper() not in (
        "GET",
        "POST",
        "PUT",
        "DELETE",
        "PATCH",
        "HEAD",
        "OPTIONS",
    ):
        errors.append(f"Route {index}: 'method' must be a valid HTTP method")

    # Validate types if present
    if "status" in route:
        if not isinstance(route["status"], int):
            errors.append(f"Route {index}: 'status' must be an integer")
        elif not (100 <= route["status"] <= 599):
            errors.append(f"Route {index}: 'status' must be between 100 and 599")

    if "latency_ms" in route:
        if not isinstance(route["latency_ms"], (int, float)):
            errors.append(f"Route {index}: 'latency_ms' must be a number")
        elif route["latency_ms"] < 0:
            errors.append(f"Route {index}: 'latency_ms' must be >= 0")

    if "failure_rate" in route:
        if not isinstance(route["failure_rate"], (int, float)):
            errors.append(f"Route {index}: 'failure_rate' must be a number")
        elif not (0.0 <= route["failure_rate"] <= 1.0):
            errors.append(f"Route {index}: 'failure_rate' must be between 0.0 and 1.0")

    if "headers" in route and not isinstance(route["headers"], dict):
        errors.append(f"Route {index}: 'headers' must be an object")

    return errors


def validate_config(config: dict) -> list[str]:
    """Validate entire config. Returns list of error messages."""
    errors = []

    if "routes" not in config:
        errors.append("config: missing required field 'routes'")
    elif not isinstance(config["routes"], list):
        errors.append("config: 'routes' must be an array")
    else:
        for i, route in enumerate(config["routes"]):
            if not isinstance(route, dict):
                errors.append(f"config: route[{i}] must be an object")
            else:
                errors.extend(validate_route(route, i))

    # Validate defaults if present
    if "defaults" in config:
        if not isinstance(config["defaults"], dict):
            errors.append("config: 'defaults' must be an object")

    return errors


def route_to_pattern(route_path: str) -> re.Pattern:
    """Convert /users/:id to regex that captures :id as named group."""
    pattern = re.escape(route_path)
    pattern = pattern.replace(r"\:", ":")
    pattern = re.sub(r":([a-zA-Z_][a-zA-Z0-9_]*)", r"(?P<\1>[^/]+)", pattern)
    return re.compile(f"^{pattern}$")


def generate_openapi_spec(
    routes: list[dict], title: str = "Mock API", version: str = "0.6.0"
) -> dict:
    """Generate OpenAPI 3.0 spec from route configuration."""
    spec = {
        "openapi": "3.0.0",
        "info": {
            "title": title,
            "version": version,
            "description": "Generated from mockroute configuration",
        },
        "paths": {},
    }

    for route in routes:
        path = route.get("path", "")
        method = route.get("method", "GET").lower()

        openapi_path = re.sub(r":([a-zA-Z_][a-zA-Z0-9_]*)", r"{\1}", path)

        if openapi_path not in spec["paths"]:
            spec["paths"][openapi_path] = {}

        params = []
        for match in re.finditer(r":([a-zA-Z_][a-zA-Z0-9_]*)", path):
            param_name = match.group(1)
            params.append(
                {
                    "name": param_name,
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            )

        status_code = str(route.get("status", 200))
        response_obj = {"description": f"Response for {method.upper()} {path}"}

        body = route.get("body")
        if body is not None:
            content_type = "application/json"
            if isinstance(body, str):
                content_type = "text/plain"
            response_obj["content"] = {content_type: {"example": body}}

        route_entry = {
            "summary": f"{method.upper()} {path}",
            "responses": {status_code: response_obj},
        }

        if params:
            route_entry["parameters"] = params

        spec["paths"][openapi_path][method] = route_entry

    return spec


def load_config(path: str) -> dict:
    """Load route configuration from a JSON file with validation."""
    config_path = Path(path)
    if not config_path.exists():
        print(f"Error: config file not found: {path}", file=sys.stderr)
        sys.exit(1)
    try:
        with config_path.open("r", encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON in {path}: {e}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(config, dict):
        print("Error: config must be a JSON object", file=sys.stderr)
        sys.exit(1)

    # Validate config
    errors = validate_config(config)
    if errors:
        for error in errors:
            print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)

    # Pre-compile regex patterns for path parameter matching
    defaults = config.get("defaults", {})
    for route in config.get("routes", []):
        route_defaults = dict(defaults)
        route_defaults.update(route)
        route["_pattern"] = route_to_pattern(route.get("path", ""))
        route["_path"] = route.get("path", "")
        route["_has_params"] = ":" in route.get("path", "")

    return config


def import_openapi_spec(path: str) -> dict:
    """Import an OpenAPI 3.0 specification and convert to mockroute config."""
    spec_path = Path(path)
    if not spec_path.exists():
        print(f"Error: OpenAPI spec file not found: {path}", file=sys.stderr)
        sys.exit(1)

    try:
        with spec_path.open("r", encoding="utf-8") as f:
            spec = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON in {path}: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(spec, dict):
        print("Error: OpenAPI spec must be a JSON object", file=sys.stderr)
        sys.exit(1)

    if spec.get("openapi") != "3.0.0":
        print("Warning: Only OpenAPI 3.0.0 is fully supported", file=sys.stderr)

    routes = []
    paths = spec.get("paths", {})

    for path_template, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue

        mockroute_path = re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", r":\1", path_template)

        for method in ["get", "post", "put", "delete", "patch", "head", "options"]:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue

            responses = operation.get("responses", {})
            status_code = "200"
            response_body = None
            content_type = "application/json"

            for code in sorted(responses.keys()):
                if code.startswith("2"):
                    status_code = code
                    response = responses[code]
                    if isinstance(response, dict):
                        content = response.get("content", {})
                        if "application/json" in content:
                            json_content = content["application/json"]
                            if "example" in json_content:
                                response_body = json_content["example"]
                            elif "examples" in json_content:
                                examples = json_content["examples"]
                                if examples:
                                    first_example = next(iter(examples.values()))
                                    if (
                                        isinstance(first_example, dict)
                                        and "value" in first_example
                                    ):
                                        response_body = first_example["value"]
                        elif "text/plain" in content:
                            text_content = content["text/plain"]
                            if "example" in text_content:
                                response_body = text_content["example"]
                                content_type = "text/plain"
                    break

            route = {
                "path": mockroute_path,
                "method": method.upper(),
                "status": int(status_code),
                "body": response_body,
                "latency_ms": 0,
                "failure_rate": 0.0,
            }

            if content_type != "application/json":
                route["headers"] = {"Content-Type": content_type}

            routes.append(route)

    config = {
        "defaults": {
            "status": 200,
            "headers": {"Content-Type": "application/json"},
            "latency_ms": 0,
            "failure_rate": 0.0,
        },
        "routes": routes,
    }

    for route in config["routes"]:
        route["_pattern"] = route_to_pattern(route.get("path", ""))
        route["_path"] = route.get("path", "")
        route["_has_params"] = ":" in route.get("path", "")

    return config


def find_route(
    routes: list[dict], method: str, path: str
) -> tuple[dict | None, dict[str, str]]:
    """Find a matching route for the given method and path."""
    for route in routes:
        if route.get("method", "").upper() != method.upper():
            continue
        pattern = route.get("_pattern")
        if pattern is None:
            pattern = route_to_pattern(route.get("path", ""))
        match = pattern.match(path)
        if match:
            return route, match.groupdict()
    return None, {}


def apply_defaults(route: dict, defaults: dict) -> dict:
    """Apply default values to a route for fields not explicitly set."""
    merged = dict(defaults)
    merged.update(route)
    if "headers" in defaults and "headers" in route:
        merged["headers"] = {**defaults["headers"], **route["headers"]}
    return merged


def format_body(body: Any) -> tuple[bytes, str]:
    """Format response body and return (encoded_bytes, content_type)."""
    if body is None:
        return b"", "application/json"
    if isinstance(body, str):
        return body.encode("utf-8"), "text/plain; charset=utf-8"
    return json.dumps(body).encode("utf-8"), "application/json"


def render_template(template: Any, context: dict[str, Any]) -> Any:
    """Render a template by replacing {{param}} placeholders."""
    if isinstance(template, str):
        full_match = re.fullmatch(r"\{\{([^}]+)\}\}", template)
        if full_match:
            key = full_match.group(1).strip()
            value = _resolve_key(key, context)
            if value is not None:
                return value
            return template

        result = template
        for match in re.finditer(r"\{\{([^}]+)\}\}", template):
            placeholder = match.group(0)
            key = match.group(1).strip()
            value = _resolve_key(key, context)
            if value is not None:
                result = result.replace(placeholder, str(value))
        return result
    elif isinstance(template, dict):
        return {k: render_template(v, context) for k, v in template.items()}
    elif isinstance(template, list):
        return [render_template(item, context) for item in template]
    else:
        return template


def _resolve_key(key: str, context: dict[str, Any]) -> Any:
    """Resolve a dotted key like 'user.name' or 'items.0' from context."""
    parts = key.split(".")
    current = context

    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None

        if current is None:
            return None

    return current


def parse_query_string(path: str) -> dict[str, list[str]]:
    """Parse query string from URL path."""
    if "?" not in path:
        return {}
    query_string = path.split("?", 1)[1]
    return urllib.parse.parse_qs(query_string)


def parse_request_body(method: str, headers: dict, rfile) -> Any:
    """Parse request body based on content type."""
    if method not in ("POST", "PUT", "PATCH"):
        return None

    content_length = int(headers.get("Content-Length", 0))
    if content_length == 0:
        return None

    content_type = headers.get("Content-Type", "")
    body = rfile.read(content_length)

    if "application/json" in content_type:
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return body.decode("utf-8")
    elif "application/x-www-form-urlencoded" in content_type:
        return urllib.parse.parse_qs(body.decode("utf-8"))
    else:
        return body.decode("utf-8")


class MockRouteHandler(BaseHTTPRequestHandler):
    """HTTP request handler for mock routes."""

    config: ClassVar[dict] = {}
    global_latency: int | None = None
    global_failure_rate: float | None = None
    enable_cors: bool = True
    enable_docs: bool = True
    enable_colors: bool = True
    verbose: bool = False
    cors_origins: ClassVar[str] = "*"
    rate_limiter: ClassVar[RateLimiter | None] = None

    def log_message(self, format: str, *args: Any) -> None:
        """Override to suppress default logging; we log in handle_request."""

    def _get_client_ip(self) -> str:
        """Get client IP address."""
        return self.client_address[0]

    def _check_rate_limit(self) -> bool:
        """Check if request is within rate limit."""
        if self.rate_limiter is None:
            return True
        return self.rate_limiter.is_allowed(self._get_client_ip())

    def _get_cors_headers(self) -> dict[str, str]:
        """Get CORS headers based on configuration."""
        if not self.enable_cors:
            return {}
        return {
            "Access-Control-Allow-Origin": self.cors_origins,
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, PATCH, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        }

    def _get_routes(self) -> list[dict]:
        return self.config.get("routes", [])

    def _get_defaults(self) -> dict:
        return self.config.get("defaults", {})

    def _send_response(
        self,
        status: int,
        body: Any = None,
        headers: dict | None = None,
        skip_body: bool = False,
    ) -> None:
        """Send an HTTP response with optional CORS headers."""
        encoded_body, content_type = format_body(body)
        self.send_response(status)
        for key, value in self._get_cors_headers().items():
            self.send_header(key, value)
        self.send_header("Content-Type", content_type)
        if headers:
            for key, value in headers.items():
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(encoded_body)))
        self.end_headers()
        if encoded_body and not skip_body:
            self.wfile.write(encoded_body)

    def _handle_request(self, method: str) -> None:
        """Core request handling logic."""
        # Strip query string for route matching
        path = self.path.split("?")[0]

        # Rate limiting
        if not self._check_rate_limit():
            self._send_response(429, {"error": "rate limit exceeded"})
            if self.verbose:
                print(f"RATE LIMITED: {self._get_client_ip()} {method} {path}")
            return

        # Handle Swagger UI requests
        if self.enable_docs:
            if path == "/docs" or path == "/docs/":
                if method == "GET":
                    html = SWAGGER_HTML.format(title="mockroute")
                    encoded = html.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(encoded)))
                    self.end_headers()
                    self.wfile.write(encoded)
                    return
                elif method == "OPTIONS":
                    self._send_response(204, None)
                    return

            if path == "/openapi.json":
                if method == "GET":
                    routes = self._get_routes()
                    spec = generate_openapi_spec(routes)
                    encoded = json.dumps(spec, indent=2).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(encoded)))
                    self.end_headers()
                    self.wfile.write(encoded)
                    return
                elif method == "OPTIONS":
                    self._send_response(204, None)
                    return

        routes = self._get_routes()
        defaults = self._get_defaults()

        start_time = time.monotonic()

        # Handle CORS preflight
        if method == "OPTIONS":
            self._send_response(204, None)
            elapsed = (time.monotonic() - start_time) * 1000
            self._log_request(method, path, None, {}, 204, elapsed, 0)
            return

        # Find matching route (with path parameter extraction)
        route, path_params = find_route(routes, method, path)
        if route is None:
            self._send_response(404, {"error": "not found", "path": path})
            elapsed = (time.monotonic() - start_time) * 1000
            self._log_request(method, path, None, {}, 404, elapsed, 0)
            return

        # Store path params for logging
        self.path_params = path_params

        # Apply defaults
        route = apply_defaults(route, defaults)

        # Parse query parameters
        query_params = parse_query_string(self.path)

        # Parse request body
        request_body = parse_request_body(method, dict(self.headers), self.rfile)

        # Build template context
        context = {
            "path": path_params,
            "query": {k: v[0] if len(v) == 1 else v for k, v in query_params.items()},
            "body": request_body,
        }

        # Determine latency
        if self.global_latency is not None:
            latency_ms = self.global_latency
        else:
            latency_ms = route.get("latency_ms", 0) or 0
        latency_ms = min(latency_ms, MAX_LATENCY_MS)

        # Determine failure rate
        if self.global_failure_rate is not None:
            failure_rate = self.global_failure_rate
        else:
            failure_rate = route.get("failure_rate", 0.0) or 0.0

        # Apply latency
        if latency_ms > 0:
            time.sleep(latency_ms / 1000.0)

        # Roll for failure
        if failure_rate > 0 and random.random() < failure_rate:
            self._send_response(
                500, {"error": "internal server error (injected failure)"}
            )
            elapsed = (time.monotonic() - start_time) * 1000
            self._log_request(
                method, path, route.get("_path"), path_params, 500, elapsed, latency_ms
            )
            return

        # Send successful response
        status = route.get("status", 200)
        body = route.get("body")

        # Render template if body contains {{}} placeholders
        if body is not None and _has_template(body):
            body = render_template(body, context)

        route_headers = route.get("headers", {})
        skip_body = method == "HEAD"
        self._send_response(status, body, route_headers, skip_body=skip_body)
        elapsed = (time.monotonic() - start_time) * 1000
        self._log_request(
            method, path, route.get("_path"), path_params, status, elapsed, latency_ms
        )

    def _log_request(
        self,
        method: str,
        path: str,
        matched_route: str | None,
        path_params: dict[str, str],
        status: int,
        elapsed_ms: float,
        latency_ms: int,
    ) -> None:
        """Log a compact, colored request line."""
        if not self.enable_colors:
            log_line = (
                f"{method:7} {path:30} {status:3} "
                f"{latency_ms:4}ms | {elapsed_ms:6.1f}ms"
            )
            if matched_route:
                log_line += f" | {matched_route}"
            if path_params:
                params_str = " ".join(f"{k}={v}" for k, v in path_params.items())
                log_line += f" ({params_str})"
            print(log_line)
            return

        method_color = METHOD_COLORS.get(method.upper(), Colors.GRAY)
        status_color = Colors.GREEN if status < 400 else Colors.RED

        parts = [
            f"{method_color}{method.upper():<6}{Colors.RESET}",
            f"{path}",
            f"{status_color}{status}{Colors.RESET}",
        ]

        if latency_ms > 0:
            parts.append(f"{Colors.GRAY}{latency_ms}ms{Colors.RESET}")

        parts.append(f"{Colors.GRAY}{elapsed_ms:.1f}ms{Colors.RESET}")

        if matched_route:
            parts.append(f"{Colors.GRAY}{matched_route}{Colors.RESET}")

        if path_params:
            params_str = " ".join(f"{k}={v}" for k, v in path_params.items())
            parts.append(f"{Colors.GRAY}({params_str}){Colors.RESET}")

        print(" ".join(parts))

        # Verbose logging
        if self.verbose:
            verbose_parts = [f"{Colors.BOLD}Details:{Colors.RESET}"]
            if path_params:
                verbose_parts.append(f"path_params={path_params}")
            verbose_parts.append(f"status={status}")
            verbose_parts.append(f"latency={latency_ms}ms")
            verbose_parts.append(f"elapsed={elapsed_ms:.1f}ms")
            print("  " + " | ".join(verbose_parts))

    def do_GET(self) -> None:
        self._handle_request("GET")

    def do_POST(self) -> None:
        self._handle_request("POST")

    def do_PUT(self) -> None:
        self._handle_request("PUT")

    def do_DELETE(self) -> None:
        self._handle_request("DELETE")

    def do_PATCH(self) -> None:
        self._handle_request("PATCH")

    def do_HEAD(self) -> None:
        self._handle_request("HEAD")

    def do_OPTIONS(self) -> None:
        self._handle_request("OPTIONS")


def _has_template(value: Any) -> bool:
    """Check if a value contains {{}} template placeholders."""
    if isinstance(value, str):
        return bool(re.search(r"\{\{[^}]+\}\}", value))
    elif isinstance(value, dict):
        return any(_has_template(v) for v in value.values())
    elif isinstance(value, list):
        return any(_has_template(item) for item in value)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="mockroute - Zero-dependency local mock API server"
    )
    parser.add_argument(
        "--version", action="version", version=f"mockroute {__version__}"
    )
    parser.add_argument(
        "--config",
        type=str,
        default=DEFAULT_CONFIG,
        help=f"route definition file (default: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--openapi",
        type=str,
        default=None,
        help="import routes from OpenAPI 3.0 spec (JSON)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"port to listen on (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=DEFAULT_HOST,
        help=f"bind address (default: {DEFAULT_HOST})",
    )
    parser.add_argument("--verbose", action="store_true", help="extra debug logging")
    parser.add_argument("--no-cors", action="store_true", help="disable CORS headers")
    parser.add_argument(
        "--no-color", action="store_true", help="disable colored output"
    )
    parser.add_argument(
        "--no-docs", action="store_true", help="disable Swagger UI at /docs"
    )
    parser.add_argument(
        "--cors-origin",
        type=str,
        default="*",
        help="allowed CORS origin (default: *)",
    )
    parser.add_argument(
        "--rate-limit",
        type=int,
        default=DEFAULT_RATE_LIMIT,
        help=f"max requests per minute per IP (default: {DEFAULT_RATE_LIMIT})",
    )
    parser.add_argument(
        "--latency",
        type=int,
        default=None,
        help="global latency override in ms (overrides per-route)",
    )
    parser.add_argument(
        "--failure-rate",
        type=float,
        default=None,
        help="global failure rate override (0.0 to 1.0)",
    )
    args = parser.parse_args()

    if args.no_color:
        Colors.disable()

    # Load config
    if args.openapi:
        config = import_openapi_spec(args.openapi)
    else:
        config = load_config(args.config)

    # Set handler class attributes
    MockRouteHandler.config = config
    MockRouteHandler.global_latency = args.latency
    MockRouteHandler.global_failure_rate = args.failure_rate
    MockRouteHandler.enable_cors = not args.no_cors
    MockRouteHandler.enable_docs = not getattr(args, "no_docs", False)
    MockRouteHandler.verbose = args.verbose
    MockRouteHandler.cors_origins = args.cors_origin
    MockRouteHandler.rate_limiter = RateLimiter(max_requests=args.rate_limit)

    # Start server
    server = ThreadingHTTPServer((args.host, args.port), MockRouteHandler)
    print(
        f"{Colors.BOLD}mockroute v{__version__}{Colors.RESET} serving on http://{args.host}:{args.port}"
    )
    print(f"Loaded {len(config.get('routes', []))} routes")
    if MockRouteHandler.enable_docs:
        print(f"API docs at http://{args.host}:{args.port}/docs")
    print("Press Ctrl+C to stop")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
