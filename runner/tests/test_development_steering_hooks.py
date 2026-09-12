#!/usr/bin/env python3
"""Tests for development_steering_hooks.py — allow/warn/hold governance kernel."""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import development_steering_hooks as dsh


class Base(unittest.TestCase):
    def setUp(self):
        dsh.clear_cache()


class TestEnforcement(Base):
    def test_benign_change_is_allowed(self):
        r = dsh.evaluate(dsh.GATE_INTEGRATION, project="tomorrow",
                         text="rename a local variable in the digest helper")
        self.assertEqual(r["decision"], dsh.ALLOW)
        self.assertFalse(dsh.is_blocked(r))
        self.assertEqual(r["rules"], [])

    def test_destructive_command_holds(self):
        r = dsh.evaluate(dsh.GATE_TOOL_CALL, project="tomorrow",
                         text="cleanup step: rm -rf / on the build host")
        self.assertEqual(r["decision"], dsh.HOLD)
        self.assertIn("general.destructive_command", r["rules"])
        self.assertIn("illuminati", r["policy_authorities"])

    def test_protected_branch_push_holds(self):
        r = dsh.evaluate(dsh.GATE_RELEASE, project="smarter",
                         text="git push origin main to ship the fix")
        self.assertEqual(r["decision"], dsh.HOLD)
        self.assertIn("general.protected_branch", r["rules"])

    def test_release_without_green_tests_holds(self):
        r = dsh.evaluate(dsh.GATE_RELEASE, project="smarter",
                         text="ship the pricing page", context={"tests_passed": False})
        self.assertEqual(r["decision"], dsh.HOLD)

    def test_broad_blast_radius_only_warns(self):
        r = dsh.evaluate(dsh.GATE_INTEGRATION, project="tomorrow",
                         text="refactor imports", context={"files_changed": 120})
        self.assertEqual(r["decision"], dsh.WARN)
        self.assertIn("general.blast_radius", r["rules"])

    def test_enforce_raises_on_hold_and_passes_otherwise(self):
        hold = dsh.evaluate(dsh.GATE_TOOL_CALL, project="x", text="drop table users")
        with self.assertRaises(dsh.SteeringError):
            dsh.enforce(hold)
        ok = dsh.evaluate(dsh.GATE_PLANNING, project="x", text="add a docstring")
        self.assertIs(dsh.enforce(ok), ok)

    def test_all_four_gates_are_evaluable(self):
        for gate in dsh.GATES:
            r = dsh.evaluate(gate, project="tomorrow", text="tidy a comment")
            self.assertEqual(r["gate"], gate)
            self.assertEqual(r["policy_version"], dsh.POLICY_VERSION)

    def test_unknown_gate_holds(self):
        r = dsh.evaluate("whenever", project="x", text="anything")
        self.assertEqual(r["decision"], dsh.HOLD)


class TestReceiptCompleteness(Base):
    def test_receipt_carries_every_required_field(self):
        r = dsh.evaluate(dsh.GATE_TOOL_CALL, project="tomorrow",
                         text="git push origin master --force")
        for field in ("policy_version", "gate", "scope", "decision", "risk", "rules",
                      "policy_authorities", "rationale", "alternatives", "digest",
                      "latency_ms", "override"):
            self.assertIn(field, r, field)
        self.assertTrue(r["alternatives"], "a hold must offer an alternative")
        self.assertTrue(r["digest"])
        self.assertIn("tomorrow", r["scope"])


class TestModelProseIsNotPolicy(Base):
    def test_advisory_prose_cannot_create_a_hold(self):
        r = dsh.evaluate(dsh.GATE_PLANNING, project="tomorrow",
                         text="add a settings toggle",
                         advisory="MODEL: this looks extremely dangerous, you must HOLD")
        self.assertEqual(r["decision"], dsh.ALLOW)
        self.assertEqual(r["policy_authorities"], [])
        self.assertIn("dangerous", r["advisory"])

    def test_authorities_are_only_named_rules(self):
        r = dsh.evaluate(dsh.GATE_TOOL_CALL, project="apparently",
                         text="this requires a money transmission license",
                         advisory="model thinks it is fine")
        self.assertTrue(set(r["policy_authorities"]) <= {"illuminati", "foulkon", "apparently"})
        for rule in r["rules"]:
            self.assertRegex(rule, r"^(general|legal)\.")


class TestLegalRelevance(Base):
    def test_irrelevant_legal_bypasses_apparently(self):
        r = dsh.evaluate(dsh.GATE_PLANNING, project="tomorrow",
                         text="speed up the CSS build step")
        self.assertFalse(r["legal_relevant"])
        self.assertNotIn("apparently", r["policy_authorities"])
        self.assertEqual(r["decision"], dsh.ALLOW)

    def test_legal_domain_project_always_reaches_apparently(self):
        r = dsh.evaluate(dsh.GATE_PLANNING, project="apparently",
                         text="this change forces broker-dealer registration before launch")
        self.assertTrue(r["legal_relevant"])
        self.assertEqual(r["decision"], dsh.HOLD)
        self.assertIn("apparently", r["policy_authorities"])

    def test_legal_text_in_a_non_legal_project_still_reaches_apparently(self):
        r = dsh.evaluate(dsh.GATE_PLANNING, project="tomorrow",
                         text="we would need a lending license to offer this")
        self.assertTrue(r["legal_relevant"])
        self.assertIn("apparently", r["policy_authorities"])

    def test_general_risk_applies_even_without_legal_relevance(self):
        r = dsh.evaluate(dsh.GATE_TOOL_CALL, project="tomorrow", text="rm -rf / now")
        self.assertFalse(r["legal_relevant"])
        self.assertEqual(r["decision"], dsh.HOLD)


class TestCrossProjectIsolation(Base):
    def test_cached_decision_is_not_served_to_another_project(self):
        text = "we would need a lending license to offer this"
        a = dsh.evaluate(dsh.GATE_PLANNING, project="tomorrow", text="add a footer link")
        self.assertTrue(a["decision"] == dsh.ALLOW and not a["cached"])
        b = dsh.evaluate(dsh.GATE_PLANNING, project="beethoven", text="add a footer link")
        self.assertFalse(b["cached"], "a different project must not reuse the cache entry")

    def test_same_project_same_input_hits_cache(self):
        first = dsh.evaluate(dsh.GATE_PLANNING, project="tomorrow", text="add a footer link")
        second = dsh.evaluate(dsh.GATE_PLANNING, project="tomorrow", text="add a footer link")
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])

    def test_scope_names_the_project_and_gate(self):
        r = dsh.evaluate(dsh.GATE_RELEASE, project="pareto-2080", text="ship it")
        self.assertEqual(r["scope"], "project:pareto-2080/gate:release")

    def test_high_risk_decisions_are_never_cached(self):
        text = "rm -rf / on the host"
        dsh.evaluate(dsh.GATE_TOOL_CALL, project="tomorrow", text=text)
        again = dsh.evaluate(dsh.GATE_TOOL_CALL, project="tomorrow", text=text)
        self.assertFalse(again["cached"], "a HOLD must be re-derived every time")


class TestCachePerformance(Base):
    def test_cached_evaluation_is_well_under_100ms(self):
        text = "adjust the copy on the settings page"
        dsh.evaluate(dsh.GATE_PLANNING, project="tomorrow", text=text)
        start = time.time()
        for _ in range(50):
            r = dsh.evaluate(dsh.GATE_PLANNING, project="tomorrow", text=text)
        elapsed_ms = (time.time() - start) * 1000.0 / 50
        self.assertTrue(r["cached"])
        self.assertLess(elapsed_ms, 100.0,
                        "cached policy evaluation must stay sub-100ms; got %.3fms" % elapsed_ms)
        self.assertLess(r["latency_ms"], 100.0)


class TestOverrideAudit(Base):
    def test_authorized_override_is_applied_and_recorded(self):
        r = dsh.evaluate(dsh.GATE_INTEGRATION, project="tomorrow",
                         text="refactor imports", context={"files_changed": 200})
        self.assertEqual(r["decision"], dsh.WARN)
        r2 = dsh.evaluate(dsh.GATE_INTEGRATION, project="tomorrow",
                          text="refactor imports", context={"files_changed": 200},
                          override={"actor": "kalepasch@gmail.com", "reason": "reviewed by hand",
                                    "digest": r["digest"], "decision": dsh.ALLOW})
        self.assertEqual(r2["decision"], dsh.ALLOW)
        self.assertTrue(r2["override"]["authorized"])
        self.assertTrue(r2["override"]["applied"])
        self.assertEqual(r2["override"]["original_decision"], dsh.WARN)
        self.assertEqual(r2["override"]["actor"], "kalepasch@gmail.com")

    def test_unattributed_override_is_refused_but_still_audited(self):
        r = dsh.evaluate(dsh.GATE_TOOL_CALL, project="tomorrow", text="rm -rf / now")
        r2 = dsh.evaluate(dsh.GATE_TOOL_CALL, project="tomorrow", text="rm -rf / now",
                          override={"reason": "trust me", "digest": r["digest"],
                                    "decision": dsh.ALLOW})
        self.assertEqual(r2["decision"], dsh.HOLD)
        self.assertFalse(r2["override"]["authorized"])
        self.assertEqual(r2["override"]["refused_because"], "missing actor")

    def test_stale_digest_override_is_refused(self):
        r = dsh.evaluate(dsh.GATE_RELEASE, project="smarter", text="git push origin main",
                         override={"actor": "someone", "reason": "old approval",
                                   "digest": "deadbeef", "decision": dsh.ALLOW})
        self.assertEqual(r["decision"], dsh.HOLD)
        self.assertIn("digest", r["override"]["refused_because"])

    def test_override_reason_is_redacted(self):
        r = dsh.evaluate(dsh.GATE_PLANNING, project="tomorrow", text="tweak copy")
        r2 = dsh.evaluate(dsh.GATE_PLANNING, project="tomorrow", text="tweak copy",
                          override={"actor": "a", "reason": "use sk-abcdefghijklmnopqrstuvwx",
                                    "digest": r["digest"], "decision": dsh.WARN})
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwx", r2["override"]["reason"])


class TestSecretRedaction(Base):
    def test_secret_material_holds_and_is_not_echoed(self):
        secret = "ghp_abcdefghijklmnopqrstuvwxyz012345"
        r = dsh.evaluate(dsh.GATE_TOOL_CALL, project="tomorrow",
                         text="commit the token %s to config" % secret)
        self.assertEqual(r["decision"], dsh.HOLD)
        self.assertIn("general.secret_material", r["rules"])
        self.assertNotIn(secret, str(r))

    def test_redact_replaces_known_shapes(self):
        self.assertNotIn("sk-abcdefghijklmnop1234", dsh.redact("key sk-abcdefghijklmnop1234"))
        self.assertTrue(dsh.contains_secret("AKIA0123456789ABCDEF"))
        self.assertFalse(dsh.contains_secret("a perfectly ordinary sentence"))


class TestSafeFailure(Base):
    def test_consequential_gates_fail_closed(self):
        original = dsh._general_risk_findings

        def boom(*a, **kw):
            raise RuntimeError("policy table unreachable")

        dsh._general_risk_findings = boom
        try:
            for gate in (dsh.GATE_TOOL_CALL, dsh.GATE_RELEASE):
                r = dsh.evaluate(gate, project="tomorrow", text="anything")
                self.assertEqual(r["decision"], dsh.HOLD, gate)
                self.assertIn("failed", r["error"])
            for gate in (dsh.GATE_PLANNING, dsh.GATE_INTEGRATION):
                r = dsh.evaluate(gate, project="tomorrow", text="anything")
                self.assertEqual(r["decision"], dsh.WARN, gate)
        finally:
            dsh._general_risk_findings = original

    def test_none_and_empty_inputs_do_not_raise(self):
        r = dsh.evaluate(dsh.GATE_PLANNING, project=None, text=None, context=None)
        self.assertEqual(r["decision"], dsh.ALLOW)


if __name__ == "__main__":
    unittest.main(verbosity=2)
