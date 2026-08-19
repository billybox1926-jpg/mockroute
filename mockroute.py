#!/usr/bin/env python3
"""
mockroute - Zero-dependency local mock API server.

Point it at a JSON route file, and it serves fake responses with
configurable latency, failure injection, CORS support, and path parameters.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

__version__ = "0.2.0"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_CONFIG = "routes.json"
MAX_LATENCY_MS = 60000  # Cap latency to prevent thread exhaustion (60 seconds)

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, PATCH, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}


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


def route_to_pattern(route_path: str) -> re.Pattern:
    """Convert /users/:id to regex that captures :id as named group.

    Escapes literal characters, then replaces :param with (?P<param>[^/]+).
    """
    # Escape everything, then unescape colons (we want : to be special)
    pattern = re.escape(route_path)
    pattern = pattern.replace(r"\:", ":")
    # Replace :param with named capture group matching anything except /
    pattern = re.sub(r":([a-zA-Z_][a-zA-Z0-9_]*)", r"(?P<\1>[^/]+)", pattern)
    return re.compile(f"^{pattern}$")


def load_config(path: str) -> dict:
    """Load route configuration from a JSON file.

    Also pre-compiles regex patterns for routes with path parameters.
    """
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

    # Pre-compile regex patterns for path parameter matching
    defaults = config.get("defaults", {})
    for route in config.get("routes", []):
        route_defaults = dict(defaults)
        route_defaults.update(route)
        route["_pattern"] = route_to_pattern(route.get("path", ""))
        route["_path"] = route.get("path", "")  # keep original for display
        # Also store whether this route has path parameters
        route["_has_params"] = ":" in route.get("path", "")

    return config


def find_route(
    routes: list[dict], method: str, path: str
) -> tuple[dict | None, dict[str, str]]:
    """Find a matching route for the given method and path.

    Returns (route, path_params) or (None, {}).
    Path parameters are extracted from the regex match.
    """
    for route in routes:
        if route.get("method", "").upper() != method.upper():
            continue
        # Use compiled _pattern if available, otherwise compile on the fly
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
    # Ensure headers are merged, not overwritten
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


class MockRouteHandler(BaseHTTPRequestHandler):
    """HTTP request handler for mock routes."""

    config: ClassVar[dict] = {}
    global_latency: int | None = None
    global_failure_rate: float | None = None
    enable_cors: bool = True
    enable_colors: bool = True
    verbose: bool = False

    def log_message(self, format: str, *args: Any) -> None:
        """Override to suppress default logging; we log in handle_request."""

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
        if self.enable_cors:
            for key, value in CORS_HEADERS.items():
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
        route_headers = route.get("headers", {})
        # HEAD requests must not include a response body
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

        # Colored output
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

    # Handle --no-color
    if args.no_color:
        Colors.disable()

    # Load config
    config = load_config(args.config)

    # Set handler class attributes
    MockRouteHandler.config = config
    MockRouteHandler.global_latency = args.latency
    MockRouteHandler.global_failure_rate = args.failure_rate
    MockRouteHandler.enable_cors = not args.no_cors
    MockRouteHandler.verbose = args.verbose

    # Start server
    server = ThreadingHTTPServer((args.host, args.port), MockRouteHandler)
    print(
        f"{Colors.BOLD}mockroute v{__version__}{Colors.RESET} serving on http://{args.host}:{args.port}"
    )
    print(f"Loaded {len(config.get('routes', []))} routes from {args.config}")
    print("Press Ctrl+C to stop")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
