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

__version__ = "0.7.1"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_CONFIG = "routes.json"
MAX_LATENCY_MS = 60000
DEFAULT_RATE_LIMIT = 100

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
        cls.GREEN = cls.YELLOW = cls.RED = cls.BLUE = ""
        cls.CYAN = cls.MAGENTA = cls.GRAY = cls.RESET = cls.BOLD = ""


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
    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def is_allowed(self, client_ip: str) -> bool:
        now = time.monotonic()
        with self._lock:
            self._requests[client_ip] = [
                t for t in self._requests[client_ip] if now - t < self.window_seconds
            ]
            if len(self._requests[client_ip]) >= self.max_requests:
                return False
            self._requests[client_ip].append(now)
            return True


def validate_route(route: dict, index: int) -> list[str]:
    errors = []
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
    if "match_query" in route and not isinstance(route["match_query"], dict):
        errors.append(f"Route {index}: 'match_query' must be an object")
    if "match_body" in route and not isinstance(route["match_body"], dict):
        errors.append(f"Route {index}: 'match_body' must be an object")
    return errors


def validate_config(config: dict) -> list[str]:
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
    if "defaults" in config:
        if not isinstance(config["defaults"], dict):
            errors.append("config: 'defaults' must be an object")
    return errors


def route_to_pattern(route_path: str) -> re.Pattern:
    pattern = re.escape(route_path)
    pattern = pattern.replace(r"\:", ":")
    pattern = re.sub(r":([a-zA-Z_][a-zA-Z0-9_]*)", r"(?P<\1>[^/]+)", pattern)
    return re.compile(f"^{pattern}$")


def generate_openapi_spec(
    routes: list[dict], title: str = "Mock API", version: str = "0.7.0"
) -> dict:
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
            params.append(
                {
                    "name": match.group(1),
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            )
        status_code = str(route.get("status", 200))
        response_obj = {"description": f"Response for {method.upper()} {path}"}
        body = route.get("body")
        if body is not None:
            ct = "text/plain" if isinstance(body, str) else "application/json"
            response_obj["content"] = {ct: {"example": body}}
        route_entry = {
            "summary": f"{method.upper()} {path}",
            "responses": {status_code: response_obj},
        }
        if params:
            route_entry["parameters"] = params
        spec["paths"][openapi_path][method] = route_entry
    return spec


def _yaml_value(s: str) -> Any:
    s = s.strip()
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    if s.startswith("'") and s.endswith("'"):
        return s[1:-1]
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    if s.lower() == "null" or s == "~" or s == "":
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _parse_yaml_simple(text: str) -> dict:
    """Simple YAML parser for flat/nested structures."""
    lines = text.split("\n")
    root: dict = {}
    stack: list[tuple[int, Any, str | None]] = [(-1, root, None)]

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        i += 1

        if not line or line.strip().startswith("#"):
            continue

        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        while len(stack) > 1 and stack[-1][0] > indent:
            stack.pop()

        _, parent, _ = stack[-1]

        if stripped.startswith("- "):
            content = stripped[2:].strip()

            if ":" in content:
                key, _, value = content.partition(":")
                key = key.strip().strip('"').strip("'")
                value = value.strip()

                new_dict: dict = {}

                if i < len(lines):
                    next_line = lines[i].rstrip()
                    next_stripped = next_line.lstrip()
                    next_indent = len(next_line) - len(next_stripped)

                    if next_indent > indent and not next_stripped.startswith("- "):
                        if isinstance(parent, list):
                            parent.append(new_dict)
                        stack.append((next_indent, new_dict, None))
                        new_dict[key] = _yaml_value(value)
                        continue
                    else:
                        if value:
                            new_dict[key] = _yaml_value(value)
                        if isinstance(parent, list):
                            parent.append(new_dict)
                else:
                    if value:
                        new_dict[key] = _yaml_value(value)
                    if isinstance(parent, list):
                        parent.append(new_dict)
            else:
                value = _yaml_value(content)
                if isinstance(parent, list):
                    parent.append(value)
        else:
            key, _, value = stripped.partition(":")
            key = key.strip().strip('"').strip("'")
            value = value.strip()

            if value == "":
                if i < len(lines):
                    next_line = lines[i].rstrip()
                    next_stripped = next_line.lstrip()
                    next_indent = len(next_line) - len(next_stripped)

                    if next_stripped.startswith("- "):
                        new_list: list = []
                        if isinstance(parent, dict):
                            parent[key] = new_list
                        stack.append((next_indent, new_list, None))
                    elif next_indent > indent:
                        new_dict = {}
                        if isinstance(parent, dict):
                            parent[key] = new_dict
                        stack.append((next_indent, new_dict, None))
                    else:
                        if isinstance(parent, dict):
                            parent[key] = None
                else:
                    if isinstance(parent, dict):
                        parent[key] = None
            else:
                if isinstance(parent, dict):
                    parent[key] = _yaml_value(value)

    return root


def load_config(path: str) -> dict:
    """Load route configuration from a JSON or YAML file with validation."""
    config_path = Path(path)
    if not config_path.exists():
        print(f"Error: config file not found: {path}", file=sys.stderr)
        sys.exit(1)

    try:
        with config_path.open("r", encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        print(f"Error: cannot read {path}: {e}", file=sys.stderr)
        sys.exit(1)

    if config_path.suffix.lower() in (".yaml", ".yml"):
        try:
            config = _parse_yaml_simple(text)
        except (ValueError, TypeError, AttributeError) as e:
            print(f"Error: invalid YAML in {path}: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        try:
            config = json.loads(text)
        except json.JSONDecodeError as e:
            print(f"Error: invalid JSON in {path}: {e}", file=sys.stderr)
            sys.exit(1)

    if not isinstance(config, dict):
        print("Error: config must be a JSON object", file=sys.stderr)
        sys.exit(1)

    errors = validate_config(config)
    if errors:
        for error in errors:
            print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)

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
    for path_template, path_item in spec.get("paths", {}).items():
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
                            jc = content["application/json"]
                            if "example" in jc:
                                response_body = jc["example"]
                            elif "examples" in jc:
                                examples = jc["examples"]
                                if examples:
                                    first = next(iter(examples.values()))
                                    if isinstance(first, dict) and "value" in first:
                                        response_body = first["value"]
                        elif "text/plain" in content:
                            tp = content["text/plain"]
                            if "example" in tp:
                                response_body = tp["example"]
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
    routes: list[dict],
    method: str,
    path: str,
    query_params: dict[str, list[str]] | None = None,
    request_body: Any = None,
) -> tuple[dict | None, dict[str, str]]:
    """Find matching route with optional query/body matchers."""
    for route in routes:
        if route.get("method", "").upper() != method.upper():
            continue
        pattern = route.get("_pattern")
        if pattern is None:
            pattern = route_to_pattern(route.get("path", ""))
        match = pattern.match(path)
        if not match:
            continue

        # Check query parameter matching
        if "match_query" in route:
            if query_params is None:
                continue
            query_match = True
            for k, v in route["match_query"].items():
                if k not in query_params:
                    query_match = False
                    break
                query_vals = query_params[k]
                if isinstance(v, list):
                    if query_vals != v:
                        query_match = False
                        break
                else:
                    if query_vals != [v]:
                        query_match = False
                        break
            if not query_match:
                continue

        # Check body matching
        if "match_body" in route:
            if request_body is None:
                continue
            if not _match_body(request_body, route["match_body"]):
                continue

        return route, match.groupdict()
    return None, {}


def _match_body(body: Any, match_spec: dict) -> bool:
    """Check if request body matches the spec (shallow key-value matching)."""
    if not isinstance(body, dict):
        return False
    for k, v in match_spec.items():
        if k not in body:
            return False
        if body[k] != v:
            return False
    return True


def apply_defaults(route: dict, defaults: dict) -> dict:
    merged = dict(defaults)
    merged.update(route)
    if "headers" in defaults and "headers" in route:
        merged["headers"] = {**defaults["headers"], **route["headers"]}
    return merged


def format_body(body: Any) -> tuple[bytes, str]:
    if body is None:
        return b"", "application/json"
    if isinstance(body, str):
        return body.encode("utf-8"), "text/plain; charset=utf-8"
    return json.dumps(body).encode("utf-8"), "application/json"


def render_template(template: Any, context: dict[str, Any]) -> Any:
    """Render a template with {{param}} placeholders, conditionals, and loops.

    When the entire string is a single placeholder, the original type is preserved.
    """
    if isinstance(template, str):
        # Check if entire string is a single placeholder
        full_match = re.fullmatch(r"\{\{([^}]+)\}\}", template)
        if full_match:
            key = full_match.group(1).strip()
            # Skip conditional/loop markers
            if key.startswith("#"):
                pass
            else:
                value = _resolve_key(key, context)
                if value is not None:
                    return value

        result = _render_conditionals(template, context)
        result = _render_loops(result, context)
        result = _render_placeholders(result, context)
        return result
    elif isinstance(template, dict):
        return {k: render_template(v, context) for k, v in template.items()}
    elif isinstance(template, list):
        return [render_template(item, context) for item in template]
    else:
        return template


def _render_placeholders(text: str, context: dict[str, Any]) -> str:
    """Replace {{key}} placeholders with values from context."""
    result = text
    for match in re.finditer(r"\{\{([^}#\/]+)\}\}", text):
        placeholder = match.group(0)
        key = match.group(1).strip()
        value = _resolve_key(key, context)
        if value is not None:
            result = result.replace(placeholder, str(value))
    return result


def _render_conditionals(text: str, context: dict[str, Any]) -> str:
    """Process {{#if key}}content{{/if}} blocks."""
    result = text
    pattern = r"\{\{#if\s+([^}]+)\}\}(.*?)\{\{/if\}\}"
    for match in re.finditer(pattern, text, re.DOTALL):
        full = match.group(0)
        key = match.group(1).strip()
        content = match.group(2)
        value = _resolve_key(key, context)
        if value:
            result = result.replace(full, content)
        else:
            result = result.replace(full, "")
    return result


def _render_loops(text: str, context: dict[str, Any]) -> str:
    """Process {{#each items}}content{{/each}} blocks."""
    result = text
    pattern = r"\{\{#each\s+([^}]+)\}\}(.*?)\{\{/each\}\}"
    for match in re.finditer(pattern, text, re.DOTALL):
        full = match.group(0)
        key = match.group(1).strip()
        content = match.group(2)
        items = _resolve_key(key, context)
        if isinstance(items, list):
            rendered = []
            for item in items:
                item_context = {**context, "this": item}
                rendered.append(_render_placeholders(content, item_context))
            result = result.replace(full, "".join(rendered))
        else:
            result = result.replace(full, "")
    return result


def _resolve_key(key: str, context: dict[str, Any]) -> Any:
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
    if "?" not in path:
        return {}
    return urllib.parse.parse_qs(path.split("?", 1)[1])


def parse_request_body(method: str, headers: dict, rfile) -> Any:
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
        pass

    def _get_client_ip(self) -> str:
        return self.client_address[0]

    def _check_rate_limit(self) -> bool:
        if self.rate_limiter is None:
            return True
        return self.rate_limiter.is_allowed(self._get_client_ip())

    def _get_cors_headers(self) -> dict[str, str]:
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
        path = self.path.split("?")[0]

        if not self._check_rate_limit():
            self._send_response(429, {"error": "rate limit exceeded"})
            if self.verbose:
                print(f"RATE LIMITED: {self._get_client_ip()} {method} {path}")
            return

        if self.enable_docs:
            if path in ("/docs", "/docs/"):
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

        if method == "OPTIONS":
            self._send_response(204, None)
            elapsed = (time.monotonic() - start_time) * 1000
            self._log_request(method, path, None, {}, 204, elapsed, 0)
            return

        query_params = parse_query_string(self.path)
        request_body = parse_request_body(method, dict(self.headers), self.rfile)

        route, path_params = find_route(
            routes, method, path, query_params, request_body
        )
        if route is None:
            self._send_response(404, {"error": "not found", "path": path})
            elapsed = (time.monotonic() - start_time) * 1000
            self._log_request(method, path, None, {}, 404, elapsed, 0)
            return

        self.path_params = path_params
        route = apply_defaults(route, defaults)

        context = {
            "path": path_params,
            "query": {k: v[0] if len(v) == 1 else v for k, v in query_params.items()},
            "body": request_body,
        }

        latency_ms = (
            self.global_latency
            if self.global_latency is not None
            else route.get("latency_ms", 0) or 0
        )
        latency_ms = min(latency_ms, MAX_LATENCY_MS)

        failure_rate = (
            self.global_failure_rate
            if self.global_failure_rate is not None
            else route.get("failure_rate", 0.0) or 0.0
        )

        if latency_ms > 0:
            time.sleep(latency_ms / 1000.0)

        if failure_rate > 0 and random.random() < failure_rate:
            self._send_response(
                500, {"error": "internal server error (injected failure)"}
            )
            elapsed = (time.monotonic() - start_time) * 1000
            self._log_request(
                method, path, route.get("_path"), path_params, 500, elapsed, latency_ms
            )
            return

        status = route.get("status", 200)
        body = route.get("body")
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
    if isinstance(value, str):
        return bool(re.search(r"\{\{[#\/]?\s*[^}]+\}\}", value))
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
        "--cors-origin", type=str, default="*", help="allowed CORS origin (default: *)"
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

    if args.openapi:
        config = import_openapi_spec(args.openapi)
    else:
        config = load_config(args.config)

    MockRouteHandler.config = config
    MockRouteHandler.global_latency = args.latency
    MockRouteHandler.global_failure_rate = args.failure_rate
    MockRouteHandler.enable_cors = not args.no_cors
    MockRouteHandler.enable_docs = not getattr(args, "no_docs", False)
    MockRouteHandler.verbose = args.verbose
    MockRouteHandler.cors_origins = args.cors_origin
    MockRouteHandler.rate_limiter = RateLimiter(max_requests=args.rate_limit)

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
