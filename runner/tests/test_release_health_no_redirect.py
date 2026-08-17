#!/usr/bin/env python3
"""`http_ok` promised that only a 200 counts as delivery. It did not deliver on that.

WHAT WAS MEASURED
-----------------
`urlopen` follows redirects by default, so a 3xx never reached the caller — only whatever the
final hop returned. Releases record `vercel_url` as the per-deployment hostname, and that
hostname sits behind Vercel Deployment Protection:

    web-e9w9viunp-...vercel.app  ->  302  ->  https://vercel.com/login  ->  200

so `http_ok` returned (200, True). The release-health half of promotion was being satisfied by
Vercel's login page — a page whose existence proves the deployment is NOT reachable.

TEST-FIXTURE CORRECTION WORTH KEEPING
-------------------------------------
The first version of this file modelled the redirect as a relative `Location: /login`. That is
same-site, so it quietly tested the opposite of the real case and passed against both the old
and the new code. The real `Location` is absolute and off-site. Every redirect here is served
by a real local HTTP server so the chain is exercised through urllib rather than around it.

Hermetic: two loopback servers, no outbound network.
"""
import http.server
import os
import sys
import threading
import unittest
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import deployment_terminal as dt  # noqa: E402


class _Handler(http.server.BaseHTTPRequestHandler):
    routes = {}

    def do_GET(self):
        code, headers, body = self.routes.get(self.path, (404, {}, b"nope"))
        self.send_response(code)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class _Server:
    def __init__(self, routes):
        self.routes = routes

    def __enter__(self):
        handler = type("H", (_Handler,), {"routes": self.routes})
        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        return False


class _FollowingOpener:
    """The OLD behaviour: urllib's default, which follows every redirect anywhere."""

    @staticmethod
    def open(req, timeout=20):
        return urllib.request.urlopen(req, timeout=timeout)


class TestRegistrableDomain(unittest.TestCase):

    def test_apex_and_www_share_a_registrable_domain(self):
        self.assertEqual(dt.registrable_domain("www.madeus.cc"),
                         dt.registrable_domain("madeus.cc"))

    def test_a_vercel_deployment_host_is_not_vercel_com(self):
        self.assertNotEqual(dt.registrable_domain("web-e9w9viunp-team.vercel.app"),
                            dt.registrable_domain("vercel.com"))

    def test_two_vercel_preview_hosts_are_separate_sites(self):
        self.assertNotEqual(dt.registrable_domain("a.vercel.app"),
                            dt.registrable_domain("b.vercel.app"))

    def test_a_multi_label_public_suffix_is_handled(self):
        self.assertEqual(dt.registrable_domain("shop.example.co.uk"), "example.co.uk")

    def test_the_plural_and_singular_pmi_domains_are_different_sites(self):
        # www.predictionmarketsadvisors.com (plural) 302s to the singular host. Different
        # registrable domain, so the plural would pin PMI red forever. Canonical host only.
        self.assertNotEqual(dt.registrable_domain("www.predictionmarketsadvisors.com"),
                            dt.registrable_domain("www.predictionmarketadvisors.com"))

    def test_an_ip_literal_does_not_crash(self):
        self.assertEqual(dt.registrable_domain("127.0.0.1"), "127.0.0.1")

    def test_empty_input_is_empty_not_an_exception(self):
        self.assertEqual(dt.registrable_domain(None), "")


class TestOffSiteRedirectIsNotDelivery(unittest.TestCase):

    def test_the_vercel_login_wall_used_to_read_as_200(self):
        # The exact production shape: deployment host 302s to an ABSOLUTE off-site login URL
        # which itself answers 200.
        with _Server({"/login": (200, {"Content-Type": "text/html"}, b"<h1>Login</h1>")}) as login:
            # `localhost` and `127.0.0.1` are distinct registrable domains, which is how two
            # loopback servers can stand in for two different sites.
            off_site = f"http://localhost:{login.port}/login"
            with _Server({"/": (302, {"Location": off_site}, b"")}) as dep:
                old_status, old_ok = dt.http_ok(dep.url + "/", opener=_FollowingOpener)
                new_status, new_ok = dt.http_ok(dep.url + "/")
        self.assertEqual((old_status, old_ok), (200, True))    # what shipped
        self.assertEqual((new_status, new_ok), (302, False))   # what is true

    def test_a_same_site_redirect_is_still_followed(self):
        # apex -> www is a DNS convention. Refusing all redirects was the first attempt and
        # would have pinned healthy projects red.
        with _Server({"/": (301, {"Location": "/home"}, b""),
                      "/home": (200, {}, b"ok")}) as srv:
            status, ok = dt.http_ok(srv.url + "/")
        self.assertEqual((status, ok), (200, True))

    def test_a_plain_200_is_unaffected(self):
        with _Server({"/": (200, {}, b"ok")}) as srv:
            self.assertEqual(dt.http_ok(srv.url + "/"), (200, True))

    def test_a_500_is_not_delivery(self):
        with _Server({"/": (500, {}, b"boom")}) as srv:
            status, ok = dt.http_ok(srv.url + "/")
        self.assertEqual((status, ok), (500, False))

    def test_an_empty_url_is_not_delivery(self):
        self.assertEqual(dt.http_ok(""), (None, False))


class TestVerifyReleasePrefersTheProductionDomain(unittest.TestCase):
    """`vercel_url` is the per-deployment alias behind Deployment Protection. The production
    domain is what a user actually reaches, and is therefore the thing to verify."""

    def test_the_prod_url_wins_over_the_deployment_alias(self):
        from unittest import mock
        seen = []

        def spy(url, timeout=20, opener=None):
            seen.append(url)
            return 200, True

        with mock.patch.object(dt, "http_ok", spy), \
                mock.patch.object(dt, "_prod_url", lambda *a, **k: "https://www.madeus.cc"), \
                mock.patch.object(dt, "live_production_sha", lambda *a, **k: ("", "no vercel")):
            dt.verify_release({"project": "beethoven", "to_sha": "a" * 40,
                               "vercel_url": "web-e9w9viunp-team.vercel.app"})
        self.assertEqual(seen, ["https://www.madeus.cc"])

    def test_the_deployment_alias_is_still_the_fallback(self):
        from unittest import mock
        seen = []

        def spy(url, timeout=20, opener=None):
            seen.append(url)
            return 200, True

        with mock.patch.object(dt, "http_ok", spy), \
                mock.patch.object(dt, "_prod_url", lambda *a, **k: ""), \
                mock.patch.object(dt, "live_production_sha", lambda *a, **k: ("", "no vercel")):
            dt.verify_release({"project": "x", "to_sha": "a" * 40,
                               "vercel_url": "web-abc-team.vercel.app"})
        self.assertEqual(seen, ["https://web-abc-team.vercel.app"])


if __name__ == "__main__":
    unittest.main()
