#!/usr/bin/env python3
"""
test_canary_metrics_server.py — tests for canary.start_metrics_server().

Covers: GET /metrics returns 200 text/plain, unknown paths and non-GET methods
return 404, startup is non-blocking (daemon thread, immediate return), repeated
calls are idempotent (no thread leaks), and bind failures are swallowed
gracefully (fail-soft, never wedges the canary loop).
"""
import os
import socket
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import canary


class MetricsServerTests(unittest.TestCase):
    def setUp(self):
        # Ephemeral port so parallel test runs never collide.
        os.environ["CANARY_METRICS_PORT"] = "0"
        canary._metrics_server = None

    def tearDown(self):
        server = canary._metrics_server
        if server is not None:
            server.shutdown()
            server.server_close()
        canary._metrics_server = None
        os.environ.pop("CANARY_METRICS_PORT", None)

    def _url(self, server, path):
        return f"http://127.0.0.1:{server.server_port}{path}"

    # --- Serving behavior ---

    def test_metrics_returns_200_text_plain(self):
        server = canary.start_metrics_server()
        self.assertIsNotNone(server)
        with urllib.request.urlopen(self._url(server, "/metrics"), timeout=5) as r:
            self.assertEqual(r.status, 200)
            self.assertIn("text/plain", r.headers.get("Content-Type", ""))
            self.assertTrue(r.read())

    def test_unknown_path_returns_404(self):
        server = canary.start_metrics_server()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self._url(server, "/nope"), timeout=5)
        self.assertEqual(ctx.exception.code, 404)

    def test_root_path_returns_404(self):
        server = canary.start_metrics_server()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self._url(server, "/"), timeout=5)
        self.assertEqual(ctx.exception.code, 404)

    def test_post_to_metrics_returns_404(self):
        server = canary.start_metrics_server()
        req = urllib.request.Request(self._url(server, "/metrics"),
                                     data=b"", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 404)

    def test_serves_multiple_sequential_requests(self):
        server = canary.start_metrics_server()
        for _ in range(3):
            with urllib.request.urlopen(self._url(server, "/metrics"), timeout=5) as r:
                self.assertEqual(r.status, 200)

    # --- Non-blocking startup ---

    def test_start_returns_immediately(self):
        t0 = time.monotonic()
        server = canary.start_metrics_server()
        elapsed = time.monotonic() - t0
        self.assertIsNotNone(server)
        self.assertLess(elapsed, 2.0, "start_metrics_server() must not block")

    def test_server_thread_is_daemon(self):
        canary.start_metrics_server()
        threads = [t for t in threading.enumerate() if t.name == "canary-metrics"]
        self.assertTrue(threads)
        self.assertTrue(all(t.daemon for t in threads))

    # --- Idempotency ---

    def test_repeated_calls_return_same_server(self):
        first = canary.start_metrics_server()
        second = canary.start_metrics_server()
        self.assertIs(first, second)

    def test_repeated_calls_do_not_leak_threads(self):
        canary.start_metrics_server()
        before = sum(1 for t in threading.enumerate() if t.name == "canary-metrics")
        for _ in range(5):
            canary.start_metrics_server()
        after = sum(1 for t in threading.enumerate() if t.name == "canary-metrics")
        self.assertEqual(before, after)

    # --- Fail-soft startup ---

    def test_bind_failure_is_swallowed(self):
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            blocker.bind(("0.0.0.0", 0))
            blocker.listen(1)
            os.environ["CANARY_METRICS_PORT"] = str(blocker.getsockname()[1])
            server = canary.start_metrics_server()  # must not raise
            self.assertIsNone(server)
        finally:
            blocker.close()

    def test_invalid_port_value_is_swallowed(self):
        os.environ["CANARY_METRICS_PORT"] = "not-a-port"
        server = canary.start_metrics_server()  # must not raise
        self.assertIsNone(server)

    def test_failed_start_can_retry_later(self):
        os.environ["CANARY_METRICS_PORT"] = "not-a-port"
        self.assertIsNone(canary.start_metrics_server())
        os.environ["CANARY_METRICS_PORT"] = "0"
        server = canary.start_metrics_server()
        self.assertIsNotNone(server)


if __name__ == "__main__":
    unittest.main()
