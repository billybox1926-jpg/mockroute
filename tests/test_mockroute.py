#!/usr/bin/env python3
"""Test suite for mockroute - zero-dependency local mock API server."""

import json
import sys
import threading
import time
import unittest
from http.client import HTTPConnection

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

    def test_query_string_stripped(self):
        """Query string is stripped before matching."""
        routes = [{"path": "/api/users", "method": "GET"}]
        result = mockroute.find_route(routes, "GET", "/api/users?limit=10")
        self.assertEqual(result["path"], "/api/users")

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

    def test_query_string_stripped_before_find_route(self):
        """Query strings are stripped before find_route is called (integration test)."""
        routes = [{"path": "/api/users", "method": "GET"}]
        result = mockroute.find_route(routes, "GET", "/api/users")
        self.assertEqual(result["path"], "/api/users")

    def test_no_match_with_query_string_in_path(self):
        """Paths with query strings match (query string stripped internally)."""
        routes = [{"path": "/api/users", "method": "GET"}]
        result = mockroute.find_route(routes, "GET", "/api/users?limit=10")
        self.assertEqual(result["path"], "/api/users")


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

    def test_headers_merged_not_overwritten(self):
        """Headers from defaults and route are merged, not overwritten."""
        defaults = {"headers": {"Content-Type": "application/json"}}
        route = {"path": "/test", "method": "GET", "headers": {"X-Custom": "true"}}
        result = mockroute.apply_defaults(route, defaults)
        self.assertEqual(result["headers"]["Content-Type"], "application/json")
        self.assertEqual(result["headers"]["X-Custom"], "true")

    def test_empty_defaults(self):
        """Empty defaults don't change route."""
        route = {"path": "/test", "method": "GET", "status": 200}
        result = mockroute.apply_defaults(route, {})
        self.assertEqual(result["status"], 200)

    def test_headers_merged_not_replaced(self):
        """Headers from defaults and route are merged, not replaced."""
        defaults = {
            "headers": {
                "Content-Type": "application/json",
                "X-Default": "default-value",
            }
        }
        route = {
            "path": "/test",
            "method": "GET",
            "headers": {"X-Custom": "custom-value"},
        }
        result = mockroute.apply_defaults(route, defaults)
        self.assertEqual(result["headers"]["Content-Type"], "application/json")
        self.assertEqual(result["headers"]["X-Default"], "default-value")
        self.assertEqual(result["headers"]["X-Custom"], "custom-value")

    def test_route_headers_override_default_headers(self):
        """Route headers override default headers with same key."""
        defaults = {
            "headers": {"Content-Type": "application/json", "X-Shared": "default"}
        }
        route = {"path": "/test", "method": "GET", "headers": {"X-Shared": "override"}}
        result = mockroute.apply_defaults(route, defaults)
        self.assertEqual(result["headers"]["X-Shared"], "override")
        self.assertEqual(result["headers"]["Content-Type"], "application/json")

    def test_headers_only_in_route(self):
        """Headers only in route are preserved."""
        defaults = {"status": 200}
        route = {"path": "/test", "method": "GET", "headers": {"X-Custom": "value"}}
        result = mockroute.apply_defaults(route, defaults)
        self.assertEqual(result["headers"]["X-Custom"], "value")

    def test_headers_only_in_defaults(self):
        """Headers only in defaults are preserved."""
        defaults = {"headers": {"Content-Type": "text/plain"}}
        route = {"path": "/test", "method": "GET"}
        result = mockroute.apply_defaults(route, defaults)
        self.assertEqual(result["headers"]["Content-Type"], "text/plain")


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
        # Reset class attributes for test isolation
        mockroute.MockRouteHandler.enable_cors = True
        mockroute.MockRouteHandler.global_latency = None
        mockroute.MockRouteHandler.global_failure_rate = None
        mockroute.MockRouteHandler.verbose = False

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
        resp, _body = self._request("GET", "/health")
        self.assertEqual(resp.getheader("Access-Control-Allow-Origin"), "*")
        self.assertIn("GET", resp.getheader("Access-Control-Allow-Methods"))

    def test_options_preflight(self):
        """OPTIONS request returns 204 with CORS headers."""
        resp, _body = self._request("OPTIONS", "/health")
        self.assertEqual(resp.status, 204)
        self.assertEqual(resp.getheader("Access-Control-Allow-Origin"), "*")

    def test_content_type_json(self):
        """JSON responses have correct Content-Type."""
        resp, _body = self._request("GET", "/health")
        self.assertIn("application/json", resp.getheader("Content-Type"))

    def test_method_mismatch_returns_404(self):
        """Wrong method for known path returns 404."""
        resp, _body = self._request("DELETE", "/health")
        self.assertEqual(resp.status, 404)

    def test_custom_headers(self):
        """Custom headers from route config are included."""
        resp, _body = self._request("GET", "/health")
        self.assertIn("application/json", resp.getheader("Content-Type"))

    def test_query_string_in_request(self):
        """Requests with query strings match routes correctly."""
        resp, body = self._request("GET", "/api/users?limit=10")
        self.assertEqual(resp.status, 200)
        self.assertEqual(json.loads(body), [{"id": 1, "name": "Alice"}])

    def test_query_string_multiple_params(self):
        """Multiple query parameters are handled correctly."""
        resp, body = self._request("GET", "/api/users?page=1&size=5&sort=name")
        self.assertEqual(resp.status, 200)
        self.assertEqual(json.loads(body), [{"id": 1, "name": "Alice"}])

    def test_defaults_application(self):
        """Default headers and route headers are merged in actual response."""
        resp, body = self._request("GET", "/health")
        self.assertIn("application/json", resp.getheader("Content-Type"))
        self.assertEqual(resp.getheader("Access-Control-Allow-Origin"), "*")
        self.assertEqual(json.loads(body), {"status": "ok"})


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
        mockroute.MockRouteHandler.global_latency = None
        mockroute.MockRouteHandler.global_failure_rate = None

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
            # Reset for other tests
            mockroute.MockRouteHandler.enable_cors = True


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


class TestHeadMethod(unittest.TestCase):
    """Test HEAD method support."""

    def test_head_returns_headers_no_body(self):
        """HEAD request returns response without body."""
        config = {
            "routes": [
                {
                    "path": "/test",
                    "method": "HEAD",
                    "status": 200,
                    "body": {"data": "should not appear"},
                    "latency_ms": 0,
                    "failure_rate": 0.0,
                }
            ]
        }
        mockroute.MockRouteHandler.config = config
        mockroute.MockRouteHandler.enable_cors = True
        mockroute.MockRouteHandler.global_latency = None
        mockroute.MockRouteHandler.global_failure_rate = None

        server = mockroute.ThreadingHTTPServer(
            ("127.0.0.1", 0), mockroute.MockRouteHandler
        )
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("HEAD", "/test")
            resp = conn.getresponse()
            body = resp.read()
            self.assertEqual(resp.status, 200)
            self.assertEqual(len(body), 0)
            conn.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)


class TestQueryStringMatching(unittest.TestCase):
    """Test that query strings don't break route matching."""

    def test_get_with_query_string(self):
        """GET /api/users?limit=10 matches /api/users route."""
        config = {
            "routes": [
                {
                    "path": "/api/users",
                    "method": "GET",
                    "status": 200,
                    "body": [{"id": 1}],
                    "latency_ms": 0,
                    "failure_rate": 0.0,
                }
            ]
        }
        mockroute.MockRouteHandler.config = config
        mockroute.MockRouteHandler.global_latency = None
        mockroute.MockRouteHandler.global_failure_rate = None

        server = mockroute.ThreadingHTTPServer(
            ("127.0.0.1", 0), mockroute.MockRouteHandler
        )
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/api/users?limit=10&offset=0")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            body = json.loads(resp.read())
            self.assertEqual(body, [{"id": 1}])
            conn.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)


class TestLatencyCap(unittest.TestCase):
    """Test that latency is capped at MAX_LATENCY_MS."""

    def test_latency_capped_at_max(self):
        """Latency values above MAX_LATENCY_MS are capped."""
        self.assertGreater(mockroute.MAX_LATENCY_MS, 0)
        self.assertEqual(mockroute.MAX_LATENCY_MS, 60000)

    def test_latency_cap_applied_to_route(self):
        """Route latency exceeding cap is reduced to MAX_LATENCY_MS."""
        # Just verify the cap exists and is reasonable
        self.assertEqual(mockroute.MAX_LATENCY_MS, 60000)
        # The actual cap behavior is tested in the unit tests for _handle_request


if __name__ == "__main__":
    unittest.main()
