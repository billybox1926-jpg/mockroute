#!/usr/bin/env python3
"""
mockroute - Zero-dependency local mock API server.

Point it at a JSON route file, and it serves fake responses with
configurable latency, failure injection, and CORS support.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

__version__ = "0.1.0"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_CONFIG = "routes.json"
MAX_LATENCY_MS = 10000  # Cap latency to prevent thread exhaustion

# Maximum allowed latency in ms (prevents thread exhaustion)
MAX_LATENCY_MS = 60000

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, PATCH, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}


def load_config(path: str) -> dict:
    """Load route configuration from a JSON file."""
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
    return config


def find_route(routes: list[dict], method: str, path: str) -> dict | None:
    """Find a matching route for the given method and path (exact match)."""
    # Strip query string before matching
    clean_path = path.split("?")[0]
    for route in routes:
        if route.get("method") == method and route.get("path") == clean_path:
            return route
    return None


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
            self._log_request(method, path, None, 204, elapsed, 0)
            return

        # Find matching route
        route = find_route(routes, method, path)
        if route is None:
            self._send_response(404, {"error": "not found", "path": path})
            elapsed = (time.monotonic() - start_time) * 1000
            self._log_request(method, path, None, 404, elapsed, 0)
            return

        # Apply defaults
        route = apply_defaults(route, defaults)

        # Determine latency
        if self.global_latency is not None:
            latency_ms = self.global_latency
        else:
            latency_ms = route.get("latency_ms", 0) or 0
        latency_ms = min(latency_ms, MAX_LATENCY_MS)

        # Cap latency to prevent thread exhaustion
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
            self._log_request(method, path, route.get("path"), 500, elapsed, latency_ms)
            return

        # Send successful response
        status = route.get("status", 200)
        body = route.get("body")
        route_headers = route.get("headers", {})
        # HEAD requests must not include a response body
        skip_body = method == "HEAD"
        self._send_response(status, body, route_headers, skip_body=skip_body)
        elapsed = (time.monotonic() - start_time) * 1000
        self._log_request(method, path, route.get("path"), status, elapsed, latency_ms)

    def _log_request(
        self,
        method: str,
        path: str,
        matched_route: str | None,
        status: int,
        elapsed_ms: float,
        latency_ms: int,
    ) -> None:
        """Log a compact request line."""
        log_line = (
            f"{method:7} {path:30} {status:3} "
            f"{latency_ms:4}ms sleep | {elapsed_ms:6.1f}ms total"
        )
        if self.verbose:
            log_line += f" | remote={self.client_address[0]}"
        print(log_line)

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
    print(f"mockroute v{__version__} serving on http://{args.host}:{args.port}")
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
