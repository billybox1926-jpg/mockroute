#!/usr/bin/env python3
"""Test suite for mockroute - zero-dependency local mock API server."""

import json
import threading
import time
import unittest
from http.client import HTTPConnection
from unittest.mock import patch

import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

import mockroute


class TestLoadConfig(unittest.TestCase):
    """Tests for load_config() function."""

    def test_load_valid_config(self, tmp_path=None):
        """Load a valid JSON config file."""
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"routes": [{"path": "/test", "method": "GET"}]}, f)
            f.flush()
            config = mockroute.load_config(f.name)
            self.assertEqual(config["routes"][0]["path"], "/test")

    def test_load_missing_file(self):
        """Missing config file should exit with error."""
        with self.assertRaises(SystemExit):
            mockroute.load_config("/nonexistent/path/routes.json")

    def test_load_invalid_json(self):
        """Invalid JSON should exit with error."""
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{invalid json}")
            f.flush()
            with self.assertRaises(SystemExit):
                mockroute.load_config(f.name)


class TestFindRoute(unittest.TestCase):
    """Tests for find_route() function."""

    def test_exact_match(self):
        """Find route with exact path and method match."""
        routes = [
            {"path": "/health", "method": "GET"},
            {"path": "/api/users", "method": "GET"},
            {"path": "/api/users", "method": "POST"},
        ]
        result = mockroute.find_route(routes, "GET", "/health")
        self.assertEqual(result["path"], "/health")
        self.assertEqual(result["method"], "GET")

    def test_method_mismatch(self):
        """No match when method differs."""
        routes = [{"path": "/api/users", "method": "GET"}]
        result = mockroute.find_route(routes, "POST", "/api/users")
        self.assertIsNone(result)

    def test_path_mismatch(self):
        """No match when path differs."""
        routes = [{"path": "/health", "method": "GET"}]
        result = mockroute.find_route(routes, "GET", "/unknown")
        self.assertIsNone(result)

    def test_empty_routes(self):
        """No match in empty routes list."""
        result = mockroute.find_route([], "GET", "/test")
        self.assertIsNone(result)


class TestApplyDefaults(unittest.TestCase):
    """Tests for apply_defaults() function."""

    def test_apply_missing_fields(self):
        """Defaults applied for fields not in route."""
        defaults = {"status": 200, "latency_ms": 50}
        route = {"path": "/test", "method": "GET"}
        result = mockroute.apply_defaults(route, defaults)
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["latency_ms"], 50)

    def test_route_overrides_defaults(self):
        """Route values override defaults."""
        defaults = {"status": 200, "latency_ms": 50}
        route = {"path": "/test", "method": "GET", "status": 201}
        result = mockroute.apply_defaults(route, defaults)
        self.assertEqual(result["status"], 201)
        self.assertEqual(result["latency_ms"], 50)

    def test_empty_defaults(self):
        """Empty defaults don't change route."""
        route = {"path": "/test", "method": "GET", "status": 200}
        result = mockroute.apply_defaults(route, {})
        self.assertEqual(result["status"], 200)


class TestFormatBody(unittest.TestCase):
    """Tests for format_body() function."""

    def test_json_object(self):
        """JSON object encoded with application/json."""
        body = {"key": "value"}
        encoded, content_type = mockroute.format_body(body)
        self.assertEqual(content_type, "application/json")
        self.assertEqual(json.loads(encoded), body)

    def test_json_array(self):
        """JSON array encoded with application/json."""
        body = [1, 2, 3]
        encoded, content_type = mockroute.format_body(body)
        self.assertEqual(content_type, "application/json")
        self.assertEqual(json.loads(encoded), body)

    def test_string_body(self):
        """String body sent as text/plain."""
        body = "Hello, World!"
        encoded, content_type = mockroute.format_body(body)
        self.assertEqual(content_type, "text/plain; charset=utf-8")
        self.assertEqual(encoded, b"Hello, World!")

    def test_null_body(self):
        """Null body returns empty bytes."""
        encoded, content_type = mockroute.format_body(None)
        self.assertEqual(content_type, "application/json")
        self.assertEqual(encoded, b"")

    def test_number_body(self):
        """Number body encoded as JSON."""
        body = 42
        encoded, content_type = mockroute.format_body(body)
        self.assertEqual(content_type, "application/json")
        self.assertEqual(json.loads(encoded), 42)

    def test_boolean_body(self):
        """Boolean body encoded as JSON."""
        body = True
        encoded, content_type = mockroute.format_body(body)
        self.assertEqual(content_type, "application/json")
        self.assertEqual(json.loads(encoded), True)


class TestMockRouteHandler(unittest.TestCase):
    """Integration tests using a real HTTP server."""

    @classmethod
    def setUpClass(cls):
        """Start a test server in a background thread."""
        cls.config = {
            "defaults": {
                "status": 200,
                "headers": {"Content-Type": "application/json"},
                "latency_ms": 0,
                "failure_rate": 0.0,
            },
            "routes": [
                {
                    "path": "/health",
                    "method": "GET",
                    "status": 200,
                    "body": {"status": "ok"},
                    "latency_ms": 0,
                    "failure_rate": 0.0,
                },
                {
                    "path": "/api/users",
                    "method": "GET",
                    "status": 200,
                    "body": [{"id": 1, "name": "Alice"}],
                    "latency_ms": 0,
                    "failure_rate": 0.0,
                },
                {
                    "path": "/api/users",
                    "method": "POST",
                    "status": 201,
                    "body": {"created": True},
                    "latency_ms": 0,
                    "failure_rate": 0.0,
                },
            ],
        }
        mockroute.MockRouteHandler.config = cls.config
        mockroute.MockRouteHandler.global_latency = None
        mockroute.MockRouteHandler.global_failure_rate = None
        mockroute.MockRouteHandler.enable_cors = True
        mockroute.MockRouteHandler.verbose = False

        cls.server = mockroute.ThreadingHTTPServer(
            ("127.0.0.1", 0), mockroute.MockRouteHandler
        )
        cls.port = cls.server.server_address[1]
        cls.server_thread = threading.Thread(
            target=cls.server.serve_forever, daemon=True
        )
        cls.server_thread.start()
        time.sleep(0.1)  # Give server time to start

    @classmethod
    def tearDownClass(cls):
        """Shut down the test server."""
        cls.server.shutdown()
        cls.server_thread.join(timeout=5)

    def _request(self, method, path, headers=None):
        """Make an HTTP request and return response."""
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, path, headers=headers or {})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp, body

    def test_get_health(self):
        """GET /health returns 200 with correct body."""
        resp, body = self._request("GET", "/health")
        self.assertEqual(resp.status, 200)
        self.assertEqual(json.loads(body), {"status": "ok"})

    def test_get_users(self):
        """GET /api/users returns user list."""
        resp, body = self._request("GET", "/api/users")
        self.assertEqual(resp.status, 200)
        self.assertEqual(json.loads(body), [{"id": 1, "name": "Alice"}])

    def test_post_users(self):
        """POST /api/users returns 201."""
        resp, body = self._request("POST", "/api/users")
        self.assertEqual(resp.status, 201)
        self.assertEqual(json.loads(body), {"created": True})

    def test_404_for_unknown_path(self):
        """Unknown path returns 404."""
        resp, body = self._request("GET", "/unknown")
        self.assertEqual(resp.status, 404)
        self.assertIn("not found", json.loads(body)["error"])

    def test_cors_headers_present(self):
        """CORS headers present in response."""
        resp, body = self._request("GET", "/health")
        self.assertEqual(resp.getheader("Access-Control-Allow-Origin"), "*")
        self.assertIn("GET", resp.getheader("Access-Control-Allow-Methods"))

    def test_options_preflight(self):
        """OPTIONS request returns 204 with CORS headers."""
        resp, body = self._request("OPTIONS", "/health")
        self.assertEqual(resp.status, 204)
        self.assertEqual(resp.getheader("Access-Control-Allow-Origin"), "*")

    def test_content_type_json(self):
        """JSON responses have correct Content-Type."""
        resp, body = self._request("GET", "/health")
        self.assertIn("application/json", resp.getheader("Content-Type"))

    def test_method_mismatch_returns_404(self):
        """Wrong method for known path returns 404."""
        resp, body = self._request("DELETE", "/health")
        self.assertEqual(resp.status, 404)

    def test_custom_headers(self):
        """Custom headers from route config are included."""
        # /health has Content-Type header in config
        resp, body = self._request("GET", "/health")
        self.assertIn("application/json", resp.getheader("Content-Type"))


class TestFailureInjection(unittest.TestCase):
    """Test failure injection behavior."""

    def test_failure_rate_zero(self):
        """0% failure rate never fails."""
        config = {
            "routes": [
                {
                    "path": "/test",
                    "method": "GET",
                    "status": 200,
                    "body": {"ok": True},
                    "latency_ms": 0,
                    "failure_rate": 0.0,
                }
            ]
        }
        mockroute.MockRouteHandler.config = config
        mockroute.MockRouteHandler.global_failure_rate = None

        server = mockroute.ThreadingHTTPServer(
            ("127.0.0.1", 0), mockroute.MockRouteHandler
        )
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            for _ in range(10):
                conn = HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("GET", "/test")
                resp = conn.getresponse()
                self.assertEqual(resp.status, 200)
                conn.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)

    def test_failure_rate_one(self):
        """100% failure rate always fails."""
        config = {
            "routes": [
                {
                    "path": "/test",
                    "method": "GET",
                    "status": 200,
                    "body": {"ok": True},
                    "latency_ms": 0,
                    "failure_rate": 1.0,
                }
            ]
        }
        mockroute.MockRouteHandler.config = config
        mockroute.MockRouteHandler.global_failure_rate = None

        server = mockroute.ThreadingHTTPServer(
            ("127.0.0.1", 0), mockroute.MockRouteHandler
        )
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            for _ in range(10):
                conn = HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("GET", "/test")
                resp = conn.getresponse()
                self.assertEqual(resp.status, 500)
                conn.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)


class TestGlobalOverrides(unittest.TestCase):
    """Test global latency and failure rate overrides."""

    def test_global_latency_override(self):
        """Global latency overrides per-route latency."""
        config = {
            "routes": [
                {
                    "path": "/test",
                    "method": "GET",
                    "status": 200,
                    "body": {"ok": True},
                    "latency_ms": 0,
                    "failure_rate": 0.0,
                }
            ]
        }
        mockroute.MockRouteHandler.config = config
        mockroute.MockRouteHandler.global_latency = 50
        mockroute.MockRouteHandler.global_failure_rate = None

        server = mockroute.ThreadingHTTPServer(
            ("127.0.0.1", 0), mockroute.MockRouteHandler
        )
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            start = time.monotonic()
            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/test")
            resp = conn.getresponse()
            elapsed = (time.monotonic() - start) * 1000
            self.assertEqual(resp.status, 200)
            self.assertGreaterEqual(elapsed, 40)  # Allow small timing variance
            conn.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)

    def test_global_failure_rate_override(self):
        """Global failure rate overrides per-route rate."""
        config = {
            "routes": [
                {
                    "path": "/test",
                    "method": "GET",
                    "status": 200,
                    "body": {"ok": True},
                    "latency_ms": 0,
                    "failure_rate": 0.0,
                }
            ]
        }
        mockroute.MockRouteHandler.config = config
        mockroute.MockRouteHandler.global_failure_rate = 1.0

        server = mockroute.ThreadingHTTPServer(
            ("127.0.0.1", 0), mockroute.MockRouteHandler
        )
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            for _ in range(5):
                conn = HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("GET", "/test")
                resp = conn.getresponse()
                self.assertEqual(resp.status, 500)
                conn.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)


class TestNoCors(unittest.TestCase):
    """Test --no-cors flag behavior."""

    def test_no_cors_headers_when_disabled(self):
        """When CORS is disabled, headers are not present."""
        config = {
            "routes": [
                {
                    "path": "/test",
                    "method": "GET",
                    "status": 200,
                    "body": {"ok": True},
                    "latency_ms": 0,
                    "failure_rate": 0.0,
                }
            ]
        }
        mockroute.MockRouteHandler.config = config
        mockroute.MockRouteHandler.enable_cors = False

        server = mockroute.ThreadingHTTPServer(
            ("127.0.0.1", 0), mockroute.MockRouteHandler
        )
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/test")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            self.assertIsNone(resp.getheader("Access-Control-Allow-Origin"))
            conn.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)


class TestDefaultsApplication(unittest.TestCase):
    """Test that defaults are properly applied to routes."""

    def test_defaults_applied_to_route(self):
        """Route without status uses default status."""
        config = {
            "defaults": {"status": 201, "latency_ms": 0, "failure_rate": 0.0},
            "routes": [
                {
                    "path": "/test",
                    "method": "GET",
                    "body": {"ok": True},
                    "latency_ms": 0,
                    "failure_rate": 0.0,
                }
            ],
        }
        mockroute.MockRouteHandler.config = config

        server = mockroute.ThreadingHTTPServer(
            ("127.0.0.1", 0), mockroute.MockRouteHandler
        )
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/test")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 201)  # From defaults
            conn.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
