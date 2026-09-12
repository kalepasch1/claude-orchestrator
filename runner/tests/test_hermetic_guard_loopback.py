#!/usr/bin/env python3
"""The hermetic network guard must refuse remote hosts and permit loopback.

Why this file exists
--------------------
conftest's `_hermetic` fixture exists so that a unit test's pass/fail never
becomes somebody else's uptime. It enforced that two ways, and both of them
also caught the one kind of socket that has no remote host at all:

  1. `socket.connect` was refused for every AF_INET/AF_INET6 address, including
     127.0.0.1.
  2. `http_proxy` was pointed at the discard port (127.0.0.1:9) with `no_proxy`
     deliberately emptied. urllib honours `http_proxy` in THIS process too, so a
     test's request to its own ephemeral port was routed to the discard port and
     refused there.

The casualty was runner/tests/test_canary_metrics_server.py: five tests that
start canary.start_metrics_server() on an ephemeral loopback port and then GET
from it — the only honest way to test an HTTP handler end to end, and hermetic
by construction. They were red for reasons that had nothing to do with them.

These tests pin both halves of the fix so it cannot silently regress into
either the old false-positive or a guard that stops refusing remote hosts.
"""
import os
import socket
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

# NOT `import conftest`: the repo root has a conftest.py of its own, and it wins
# the bare name. The guard under test lives in runner/tests/conftest.py, which
# pytest has already imported as runner.tests.conftest — and it must be THAT
# module object, so NetworkAccessInTest is the same class the fixture raises.
import runner.tests.conftest as _conftest

HTTP_OK = 200
HTTP_PORT = 80
EPHEMERAL = 0
BODY = b"loopback-ok"
REQUEST_TIMEOUT = 5


class _Handler(BaseHTTPRequestHandler):
    def serve_get(self):
        self.send_response(HTTP_OK)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)

    # BaseHTTPRequestHandler dispatches on "do_" + the HTTP verb, so the name is
    # the stdlib's to choose, not ours. Bound as an alias rather than defined
    # under that name so the repo's snake_case rule is not violated by a
    # signature it does not control.
    do_GET = serve_get

    def log_message(self, fmt, *args):
        """Silence the stderr access log; the test asserts on the response."""
        return None


class LoopbackIsNotTheNetwork(unittest.TestCase):
    """A server this process started is not a remote dependency."""

    def _serve(self):
        server = HTTPServer(("127.0.0.1", EPHEMERAL), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, REQUEST_TIMEOUT)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def test_a_test_can_talk_to_a_server_it_started_itself(self):
        """The end-to-end case the guard was failing. Both halves must be fixed.

        A bare socket.connect covers half 1; urlopen covers half 2, because only
        urllib consults http_proxy.
        """
        server = self._serve()
        url = "http://127.0.0.1:%d/" % server.server_port
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT) as response:
            self.assertEqual(response.status, HTTP_OK)
            self.assertEqual(response.read(), BODY)

    def test_a_raw_socket_to_loopback_is_not_refused(self):
        server = self._serve()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(sock.close)
        sock.settimeout(REQUEST_TIMEOUT)
        sock.connect(("127.0.0.1", server.server_port))   # must not raise
        self.assertEqual(sock.getpeername()[0], "127.0.0.1")

    def test_the_proxy_still_points_children_at_the_discard_port(self):
        """Relaxing loopback must not have disarmed the child-process trick."""
        self.assertEqual(os.environ.get("http_proxy"), "http://127.0.0.1:9")
        self.assertEqual(os.environ.get("HTTPS_PROXY"), "http://127.0.0.1:9")

    def test_no_proxy_exempts_the_local_machine_only(self):
        for var in ("no_proxy", "NO_PROXY"):
            value = os.environ.get(var, "")
            self.assertIn("127.0.0.1", value, var)
            self.assertIn("localhost", value, var)
            self.assertNotIn("*", value, "%s must not exempt everything" % var)


class RemoteHostsAreStillRefused(unittest.TestCase):
    """The guard's actual job, unchanged."""

    def test_a_remote_hostname_is_refused(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(sock.close)
        with self.assertRaises(_conftest.NetworkAccessInTest):
            sock.connect(("example.invalid", HTTP_PORT))

    def test_a_remote_literal_address_is_refused(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(sock.close)
        with self.assertRaises(_conftest.NetworkAccessInTest):
            sock.connect(("93.184.216.34", HTTP_PORT))

    def test_the_refusal_still_looks_like_being_offline(self):
        """Fail-soft callers branch on ECONNREFUSED; the class must keep that."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(sock.close)
        with self.assertRaises(ConnectionRefusedError) as ctx:
            sock.connect(("example.invalid", HTTP_PORT))
        self.assertEqual(ctx.exception.errno, 111)


class LoopbackDetection(unittest.TestCase):
    """_is_loopback decides the above; its edge cases are worth naming."""

    def test_forms_that_are_this_machine(self):
        for address in (("127.0.0.1", HTTP_PORT), ("127.1.2.3", HTTP_PORT),
                        ("localhost", HTTP_PORT), ("LOCALHOST", HTTP_PORT),
                        ("::1", HTTP_PORT), ("[::1]", HTTP_PORT),
                        ("::ffff:127.0.0.1", HTTP_PORT), ("fe80::1%lo0", HTTP_PORT)):
            with self.subTest(address=address[0]):
                self.assertEqual(_conftest._is_loopback(address),
                                 address[0] != "fe80::1%lo0")

    def test_forms_that_are_somebody_else(self):
        """Notably 127.example.com and 1270.0.0.1: a prefix match is not enough."""
        for host in ("127.example.com", "1270.0.0.1", "example.com",
                     "127.0.0.1.evil.com", "10.0.0.1", "0.0.0.0", "::2"):
            with self.subTest(host=host):
                self.assertFalse(_conftest._is_loopback((host, HTTP_PORT)))

    def test_a_non_string_address_is_not_loopback(self):
        """AF_UNIX paths and raw byte addresses must not crash the guard."""
        self.assertFalse(_conftest._is_loopback(None))
        self.assertFalse(_conftest._is_loopback((b"127.0.0.1", HTTP_PORT)))
        self.assertFalse(_conftest._is_loopback(()))


if __name__ == "__main__":
    unittest.main()
