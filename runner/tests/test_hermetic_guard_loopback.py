"""The hermetic guard must block the network without blocking this machine.

Specification: `runner/tests/test-plan.md`. Each numbered edge case there has an
assertion here; the docstring below is the same contract in prose.

CORE SCENARIO. A test starts a server in its own process and scrapes it over
loopback. `runner/tests/test_canary_metrics_server.py` does exactly that — it binds the
canary `/metrics` endpoint on 127.0.0.1 and reads it back, which IS the behaviour under
test. Five of its cases failed with:

    urllib.error.URLError: <urlopen error [Errno 111] Connection refused by the test
    suite's hermetic guard: ('127.0.0.1', 9)>

Note the port: 9. The request never reached the server. It was sent to the discard-port
proxy the guard exports into `http_proxy`, because the guard also emptied `no_proxy`.
The guard's stated rule is "unit tests must not depend on a remote host"; a socket to
127.0.0.1 depends on no host but this one, so the rule never applied and the failure was
pure collateral.

EDGE CASES this pins down, because a widened guard is only safe if its edge is exact:
  * a real remote host is still refused (the guard must not have been defanged);
  * `localhost` and `::1` count as loopback, and so does all of 127.0.0.0/8;
  * a hostname that merely *contains* "localhost" (`notlocalhost.example.com`,
    `localhost.evil.com`) does NOT — substring matching here would be a hole;
  * unresolvable/garbage addresses are treated as remote, i.e. the check fails CLOSED;
  * `_is_loopback` performs no DNS resolution, since a lookup would itself be the
    remote dependency the guard exists to prevent.
"""
import os
import socket
import sys
import unittest
import urllib.error
import urllib.request

import importlib.util

# NOT `from conftest import ...`: there is a conftest.py at the repo root too, and a
# bare import resolves to whichever one sys.path finds first. Load this directory's by
# explicit path — the same duplicate-basename trap the two canary.py files fell into.
_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "runner_tests_conftest", os.path.join(_HERE, "conftest.py"))
_conftest = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("runner_tests_conftest", _conftest)
_spec.loader.exec_module(_conftest)

_is_loopback = _conftest._is_loopback

# The guard's exception is asserted on BEHAVIOURALLY (OSError + errno 111 + its
# message), not by class identity: pytest loads runner/tests/conftest.py as
# `runner.tests.conftest`, so the copy loaded above by path is a different class
# object and an isinstance check against it would never match the raised one.
_GUARD_MESSAGE = "hermetic guard"


class IsLoopbackTest(unittest.TestCase):
    def test_the_canonical_v4_address(self):
        self.assertTrue(_is_loopback(("127.0.0.1", 8000)))

    def test_the_whole_127_block(self):
        for host in ("127.0.0.2", "127.1.1.1", "127.255.255.254"):
            with self.subTest(host=host):
                self.assertTrue(_is_loopback((host, 80)))

    def test_the_name_localhost(self):
        self.assertTrue(_is_loopback(("localhost", 8000)))
        self.assertTrue(_is_loopback(("LOCALHOST", 8000)))

    def test_ipv6_loopback(self):
        for host in ("::1", "[::1]", "0:0:0:0:0:0:0:1", "::ffff:127.0.0.1"):
            with self.subTest(host=host):
                self.assertTrue(_is_loopback((host, 8000)))

    def test_a_real_remote_host_is_not_loopback(self):
        for host in ("github.com", "8.8.8.8", "api.anthropic.com", "192.168.1.10",
                     "10.0.0.1", "0.0.0.0"):
            with self.subTest(host=host):
                self.assertFalse(_is_loopback((host, 443)))

    def test_a_hostname_containing_localhost_is_not_loopback(self):
        # substring matching would be a hole an attacker-controlled name could walk through
        for host in ("notlocalhost.example.com", "localhost.evil.com",
                     "my-localhost-proxy.net", "127.0.0.1.evil.com"):
            with self.subTest(host=host):
                self.assertFalse(_is_loopback((host, 443)))

    def test_a_near_miss_octet_is_not_loopback(self):
        for host in ("128.0.0.1", "27.0.0.1", "1270.0.0.1", "127.0.0.256"):
            with self.subTest(host=host):
                self.assertFalse(_is_loopback((host, 80)))

    def test_it_fails_closed_on_garbage(self):
        for address in (None, 5, object(), (), ("",), (None, 80), b"\xff\xfe",
                        ({"host": "127.0.0.1"}, 80)):
            with self.subTest(address=address):
                self.assertFalse(_is_loopback(address))

    def test_it_never_raises(self):
        for address in (None, [], "", ("::",), (b"127.0.0.1", 80)):
            with self.subTest(address=address):
                self.assertIsInstance(_is_loopback(address), bool)

    def test_it_does_not_resolve_names(self):
        # a DNS lookup here would be the very remote dependency the guard prevents
        original = socket.getaddrinfo
        socket.getaddrinfo = lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("_is_loopback resolved a name"))
        try:
            self.assertFalse(_is_loopback(("example.com", 80)))
            self.assertTrue(_is_loopback(("127.0.0.1", 80)))
        finally:
            socket.getaddrinfo = original


class GuardStillBlocksRemoteTest(unittest.TestCase):
    """Widening must not defang. These run under the autouse hermetic fixture."""

    def test_a_remote_tcp_connection_is_refused(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        with self.assertRaises(OSError) as ctx:
            s.connect(("example.com", 80))
        s.close()
        self.assertIn(_GUARD_MESSAGE, str(ctx.exception))

    def test_a_remote_http_request_is_refused(self):
        with self.assertRaises(urllib.error.URLError):
            urllib.request.urlopen("http://example.com/", timeout=5)

    def test_connect_ex_to_a_remote_host_is_refused(self):
        # test-plan.md edge case 8. connect_ex is the same egress as connect, spelled
        # so it returns an errno instead of raising — and the guard only ever wrapped
        # connect, so this walked out to the real network and did so silently.
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        try:
            self.assertEqual(s.connect_ex(("example.com", 80)), 111)
        finally:
            s.close()

    def test_connect_ex_returns_rather_than_raises(self):
        # blocking it by raising would break callers in a way they would never break
        # on a genuinely offline machine, where connect_ex returns ECONNREFUSED.
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        try:
            result = s.connect_ex(("8.8.8.8", 53))
        except OSError:  # pragma: no cover
            self.fail("connect_ex raised; it must return an errno")
        finally:
            s.close()
        self.assertIsInstance(result, int)
        self.assertNotEqual(result, 0)

    def test_the_refusal_is_still_an_oserror_with_econnrefused(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        try:
            s.connect(("8.8.8.8", 53))
        except OSError as e:
            self.assertEqual(e.errno, 111)
        else:  # pragma: no cover
            self.fail("remote connection was not blocked")
        finally:
            s.close()


class LoopbackReachesItsOwnServerTest(unittest.TestCase):
    """The core scenario, end to end, under the guard."""

    def setUp(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import threading

        class _H(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b"ok\n"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), _H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_a_raw_socket_to_our_own_port_connects(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(("127.0.0.1", self.port))
        s.close()

    def test_urlopen_reaches_our_own_server(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/x", timeout=5) as r:
            self.assertEqual(r.status, 200)
            self.assertEqual(r.read(), b"ok\n")

    def test_it_is_not_silently_going_through_the_discard_proxy(self):
        # the original failure signature was ('127.0.0.1', 9) — the proxy, not us
        self.assertNotEqual(self.port, 9)
        self.assertIn("127.0.0.1", os.environ.get("no_proxy", ""))

    def test_connect_ex_to_our_own_port_succeeds(self):
        # test-plan.md edge case 9: closing the connect_ex hole must not close loopback.
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        try:
            self.assertEqual(s.connect_ex(("127.0.0.1", self.port)), 0)
        finally:
            s.close()

    def test_localhost_by_name_also_works(self):
        with urllib.request.urlopen(f"http://localhost:{self.port}/x", timeout=5) as r:
            self.assertEqual(r.status, 200)


if __name__ == "__main__":
    unittest.main()
