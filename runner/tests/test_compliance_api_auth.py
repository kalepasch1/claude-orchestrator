#!/usr/bin/env python3
"""Authenticated boundary + tenancy for the compliance API gateway.

The gateway used to read tenancy straight out of the request body:

    tenant_id = body.get("tenant_id", "default")

so any caller could read or mutate any tenant's sandbox by typing a different
string. There was no caller identity, no body-size bound, no rate limit, and
`Access-Control-Allow-Origin: *` on every response.

The central assertion in this file is the cross-tenant one: a principal bound
to tenant A must not be able to reach tenant B's data by *asking* for it. The
rest pin the supporting controls, including that the gateway stays usable on
loopback until an authentication adapter is actually configured.
"""
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import compliance_auth as ca
from compliance_api_gateway import ComplianceAPIGateway


def _principal(name="acme", tenant="acme", scopes=(ca.READ, ca.WRITE), via="token"):
    return ca.Principal(name=name, tenant=tenant, scopes=frozenset(scopes), via=via)


class _GatewayCase(unittest.TestCase):
    def setUp(self):
        # A fresh gateway per test: the rate limiter and sandboxes are stateful.
        self.gw = ComplianceAPIGateway()
        self._env = {k: os.environ.get(k) for k in
                     ("ORCH_COMPLIANCE_API_TOKENS", "ORCH_COMPLIANCE_API_ALLOWED_ORIGINS")}
        os.environ.pop("ORCH_COMPLIANCE_API_TOKENS", None)
        self.addCleanup(self._restore)

    def _restore(self):
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class TestTenancyIsDerivedFromPrincipal(_GatewayCase):

    def test_body_tenant_id_cannot_redirect_the_read(self):
        """The regression: naming another tenant must not grant access."""
        victim = _principal(name="acme", tenant="acme")
        status, body = self.gw.dispatch(
            "GET", "/compliance/v1/apps/app1",
            {"tenant_id": "other-corp"}, principal=victim)
        self.assertEqual(status, 403)
        self.assertIn("may not act on tenant", body["error"])

    def test_omitted_tenant_uses_the_principals_own(self):
        called = {}
        with patch.object(self.gw.isolation, "snapshot",
                          side_effect=lambda t, a: called.setdefault("tenant", t) or {}):
            status, _ = self.gw.dispatch("GET", "/compliance/v1/apps/app1", {},
                                         principal=_principal(tenant="acme"))
        self.assertEqual(status, 200)
        self.assertEqual(called["tenant"], "acme")

    def test_matching_tenant_is_allowed(self):
        with patch.object(self.gw.isolation, "snapshot", return_value={"ok": True}):
            status, _ = self.gw.dispatch("GET", "/compliance/v1/apps/app1",
                                         {"tenant_id": "acme"},
                                         principal=_principal(tenant="acme"))
        self.assertEqual(status, 200)

    def test_admin_may_act_across_tenants(self):
        called = {}
        admin = _principal(name="root", tenant="ops", scopes=(ca.ADMIN,))
        with patch.object(self.gw.isolation, "snapshot",
                          side_effect=lambda t, a: called.setdefault("tenant", t) or {}):
            status, _ = self.gw.dispatch("GET", "/compliance/v1/apps/app1",
                                         {"tenant_id": "other-corp"}, principal=admin)
        self.assertEqual(status, 200)
        self.assertEqual(called["tenant"], "other-corp")

    def test_writes_are_tenant_bound_too(self):
        status, body = self.gw.dispatch(
            "POST", "/compliance/v1/apps/app1/risk-score",
            {"tenant_id": "other-corp", "score": 90}, principal=_principal(tenant="acme"))
        self.assertEqual(status, 403)

    def test_risk_score_write_uses_principal_tenant(self):
        seen = {}
        with patch.object(self.gw.isolation, "set_risk_score",
                          side_effect=lambda t, a, s: (seen.setdefault("tenant", t), (0.0, 90.0))[1]):
            status, _ = self.gw.dispatch("POST", "/compliance/v1/apps/app1/risk-score",
                                         {"score": 90}, principal=_principal(tenant="acme"))
        self.assertEqual(status, 200)
        self.assertEqual(seen["tenant"], "acme")

    def test_event_publish_is_stamped_with_principal_tenant(self):
        published = {}
        original = self.gw.events.publish

        def capture(event):
            published["tenant"] = event.tenant_id
            return original(event)

        with patch.object(self.gw.events, "publish", side_effect=capture):
            status, _ = self.gw.dispatch(
                "POST", "/compliance/v1/events",
                {"kind": "risk.score_changed", "app_id": "app1", "tenant_id": "acme"},
                principal=_principal(tenant="acme"))
        self.assertEqual(status, 202)
        self.assertEqual(published["tenant"], "acme")

    def test_event_stream_read_is_tenant_scoped(self):
        self.gw.dispatch("POST", "/compliance/v1/events",
                         {"kind": "risk.score_changed", "app_id": "a"},
                         principal=_principal(name="acme", tenant="acme"))
        status, body = self.gw.dispatch("GET", "/compliance/v1/events", {},
                                        principal=_principal(name="other", tenant="other"))
        self.assertEqual(status, 200)
        self.assertEqual(body["events"], [],
                         "another tenant's events must not be readable")


class TestAuthenticationRequired(_GatewayCase):

    def test_loopback_is_allowed_while_no_adapter_is_configured(self):
        with patch.object(self.gw.isolation, "snapshot", return_value={}):
            status, _ = self.gw.dispatch("GET", "/compliance/v1/apps/app1", {},
                                         client_host="127.0.0.1")
        self.assertEqual(status, 200)

    def test_non_loopback_is_rejected_while_no_adapter_is_configured(self):
        status, body = self.gw.dispatch("GET", "/compliance/v1/apps/app1", {},
                                        client_host="10.0.0.5")
        self.assertEqual(status, 403)
        self.assertIn("loopback-only", body["error"])

    def test_missing_client_identity_is_rejected(self):
        status, _ = self.gw.dispatch("GET", "/compliance/v1/apps/app1", {})
        self.assertEqual(status, 403)

    def test_configured_adapter_rejects_anonymous_loopback(self):
        os.environ["ORCH_COMPLIANCE_API_TOKENS"] = json.dumps(
            {"secret-token": {"principal": "acme", "tenant": "acme", "scopes": ["read"]}})
        status, body = self.gw.dispatch("GET", "/compliance/v1/apps/app1", {},
                                        client_host="127.0.0.1")
        self.assertEqual(status, 401)
        self.assertIn("authentication required", body["error"])

    def test_valid_token_authenticates_and_binds_tenant(self):
        os.environ["ORCH_COMPLIANCE_API_TOKENS"] = json.dumps(
            {"secret-token": {"principal": "acme", "tenant": "acme", "scopes": ["read"]}})
        seen = {}
        with patch.object(self.gw.isolation, "snapshot",
                          side_effect=lambda t, a: seen.setdefault("tenant", t) or {}):
            status, _ = self.gw.dispatch("GET", "/compliance/v1/apps/app1", {},
                                         client_host="10.0.0.5", token="secret-token")
        self.assertEqual(status, 200)
        self.assertEqual(seen["tenant"], "acme")

    def test_bad_token_is_rejected_even_from_loopback(self):
        """Loopback must never upgrade a wrong credential into a right one."""
        os.environ["ORCH_COMPLIANCE_API_TOKENS"] = json.dumps(
            {"secret-token": {"principal": "acme", "tenant": "acme"}})
        status, _ = self.gw.dispatch("GET", "/compliance/v1/apps/app1", {},
                                     client_host="127.0.0.1", token="wrong")
        self.assertEqual(status, 401)

    def test_token_presented_with_no_adapter_configured_is_rejected(self):
        status, _ = self.gw.dispatch("GET", "/compliance/v1/apps/app1", {},
                                     client_host="127.0.0.1", token="anything")
        self.assertEqual(status, 401)

    def test_malformed_token_config_authenticates_nobody(self):
        os.environ["ORCH_COMPLIANCE_API_TOKENS"] = "{not json"
        self.assertFalse(ca.auth_configured())
        status, _ = self.gw.dispatch("GET", "/compliance/v1/apps/app1", {},
                                     client_host="10.0.0.5", token="anything")
        self.assertEqual(status, 401)

    def test_health_does_not_require_credentials(self):
        status, body = self.gw.dispatch("GET", "/compliance/v1/health", {})
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")


class TestScopes(_GatewayCase):

    def test_read_only_principal_cannot_write(self):
        reader = _principal(name="ro", tenant="acme", scopes=(ca.READ,))
        status, body = self.gw.dispatch("POST", "/compliance/v1/apps/app1/risk-score",
                                        {"score": 10}, principal=reader)
        self.assertEqual(status, 403)
        self.assertIn("write", body["error"])

    def test_read_only_principal_can_read(self):
        reader = _principal(name="ro", tenant="acme", scopes=(ca.READ,))
        with patch.object(self.gw.isolation, "snapshot", return_value={}):
            status, _ = self.gw.dispatch("GET", "/compliance/v1/apps/app1", {},
                                         principal=reader)
        self.assertEqual(status, 200)

    def test_no_scopes_cannot_even_read(self):
        nobody = _principal(name="none", tenant="acme", scopes=())
        status, _ = self.gw.dispatch("GET", "/compliance/v1/apps/app1", {}, principal=nobody)
        self.assertEqual(status, 403)

    def test_admin_implies_every_scope(self):
        admin = _principal(name="root", tenant="acme", scopes=(ca.ADMIN,))
        self.assertTrue(admin.may(ca.READ))
        self.assertTrue(admin.may(ca.WRITE))


class TestRequestLimits(_GatewayCase):

    def test_body_at_the_cap_is_accepted(self):
        ca.check_body_size(ca.MAX_BODY_BYTES)  # must not raise

    def test_oversized_body_is_413(self):
        with self.assertRaises(ca.AuthError) as caught:
            ca.check_body_size(ca.MAX_BODY_BYTES + 1)
        self.assertEqual(caught.exception.status, 413)

    def test_negative_content_length_is_rejected(self):
        with self.assertRaises(ca.AuthError):
            ca.check_body_size(-1)

    def test_unreadable_content_length_is_rejected(self):
        with self.assertRaises(ca.AuthError):
            ca.check_body_size("not-a-number")

    def test_rate_limit_trips_with_429(self):
        limiter = ca.RateLimiter(limit=3, window_s=60)
        for _ in range(3):
            limiter.check("acme")
        with self.assertRaises(ca.AuthError) as caught:
            limiter.check("acme")
        self.assertEqual(caught.exception.status, 429)

    def test_rate_limit_is_per_principal(self):
        limiter = ca.RateLimiter(limit=1, window_s=60)
        limiter.check("acme")
        limiter.check("other")  # a different principal is unaffected

    def test_gateway_enforces_the_rate_limit(self):
        self.gw.rate_limiter = ca.RateLimiter(limit=2, window_s=60)
        principal = _principal(tenant="acme")
        with patch.object(self.gw.isolation, "snapshot", return_value={}):
            self.gw.dispatch("GET", "/compliance/v1/apps/a", {}, principal=principal)
            self.gw.dispatch("GET", "/compliance/v1/apps/a", {}, principal=principal)
            status, _ = self.gw.dispatch("GET", "/compliance/v1/apps/a", {}, principal=principal)
        self.assertEqual(status, 429)

    def test_zero_limit_disables_rate_limiting(self):
        limiter = ca.RateLimiter(limit=0, window_s=60)
        for _ in range(50):
            limiter.check("acme")


class TestCors(_GatewayCase):

    def test_wildcard_origin_is_never_emitted(self):
        headers = ca.cors_headers("https://evil.example")
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_star_in_config_is_ignored(self):
        with patch.object(ca, "ALLOWED_ORIGINS", ("*",)):
            headers = ca.cors_headers("https://evil.example")
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_configured_origin_is_echoed(self):
        with patch.object(ca, "ALLOWED_ORIGINS", ("https://ops.internal",)):
            headers = ca.cors_headers("https://ops.internal")
        self.assertEqual(headers["Access-Control-Allow-Origin"], "https://ops.internal")

    def test_response_always_varies_on_origin(self):
        self.assertEqual(ca.cors_headers(None).get("Vary"), "Origin")


class TestAuditLogging(_GatewayCase):

    def test_cross_tenant_attempt_is_audited(self):
        with patch.object(ca, "audit") as audit:
            self.gw.dispatch("GET", "/compliance/v1/apps/app1",
                             {"tenant_id": "other-corp"}, principal=_principal(tenant="acme"))
        audit.assert_called()
        self.assertEqual(audit.call_args.kwargs["status"], 403)

    def test_successful_write_is_audited(self):
        with patch.object(self.gw.isolation, "set_risk_score", return_value=(0.0, 5.0)), \
             patch.object(ca, "audit") as audit:
            self.gw.dispatch("POST", "/compliance/v1/apps/app1/risk-score",
                             {"score": 5}, principal=_principal(tenant="acme"))
        actions = [c.args[0] for c in audit.call_args_list]
        self.assertTrue(any("risk-score" in a for a in actions))

    def test_audit_never_raises(self):
        import events
        with patch.object(events, "emit", side_effect=RuntimeError("disk full")):
            ca.audit("GET /x", _principal(), status=200)

    def test_audit_record_excludes_the_token(self):
        captured = {}
        import events
        with patch.object(events, "emit", side_effect=lambda kind, **f: captured.update(f)):
            ca.audit("GET /x", _principal(), status=200, token="super-secret")
        self.assertNotIn("token", captured)
        self.assertNotIn("super-secret", json.dumps(captured))

    def test_token_fingerprint_is_not_the_token(self):
        tag = ca.token_fingerprint("super-secret")
        self.assertNotIn("super-secret", tag)
        self.assertEqual(len(tag), 12)
        self.assertEqual(tag, ca.token_fingerprint("super-secret"), "must be stable")
        self.assertNotEqual(tag, ca.token_fingerprint("other-secret"))


class TestNoHardcodedSecrets(unittest.TestCase):

    def test_module_reads_tokens_only_from_the_environment(self):
        source = open(ca.__file__, encoding="utf-8").read()
        self.assertIn("ORCH_COMPLIANCE_API_TOKENS", source)
        for forbidden in ("PASSWORD =", "SECRET =", "TOKEN ="):
            self.assertNotIn(forbidden, source)

    def test_no_default_token_grants_access(self):
        os.environ.pop("ORCH_COMPLIANCE_API_TOKENS", None)
        self.assertEqual(ca._token_registry(), {})
        self.assertFalse(ca.auth_configured())


if __name__ == "__main__":
    unittest.main()
