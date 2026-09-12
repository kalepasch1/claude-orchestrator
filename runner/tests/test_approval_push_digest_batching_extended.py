#!/usr/bin/env python3
"""Extended test suite for approval digest batching feature.

Comprehensive test coverage for:
- Digest building with edge cases
- Filtering logic (legal-gated, routine, status, kind)
- Configuration and environment variable handling
- Database integration and error resilience
- Link generation with alternatives
- Audience and email behavior
- Batching on/off toggle with various scenarios
"""
import importlib
import os
import sys
import unittest
from unittest.mock import patch, MagicMock
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

import approval_push as ap

GOOD_KEY = "k" * 40


class DigestEdgeCasesTest(unittest.TestCase):
    """Edge cases in digest building and title handling."""

    def test_empty_cards_list(self):
        title, body = ap.build_digest([])
        self.assertIn("0 decisions", title)
        self.assertIn("cockpit", body)

    def test_digest_with_missing_project(self):
        cards = [{"id": "a1", "kind": "legal", "title": "No project card"}]
        title, body = ap.build_digest(cards)
        self.assertIn("[-]", body)
        self.assertIn("No project card", body)

    def test_digest_with_missing_title(self):
        cards = [{"id": "a1", "kind": "legal", "project": "p"}]
        title, body = ap.build_digest(cards)
        self.assertIn("[p] Decision: ", body)

    def test_digest_with_very_long_title_is_truncated(self):
        long_title = "x" * 200
        cards = [{"id": "a1", "kind": "legal", "project": "p", "title": long_title}]
        _, body = ap.build_digest(cards)
        self.assertIn("x" * 120, body)
        self.assertNotIn("x" * 121, body)

    def test_digest_distinguishes_decision_from_action(self):
        cards_decision = [{"id": "a1", "kind": "legal", "project": "p", "title": "T"}]
        cards_action = [{"id": "a1", "kind": "operator", "project": "p", "title": "T"}]
        _, body_d = ap.build_digest(cards_decision)
        _, body_a = ap.build_digest(cards_action)
        self.assertIn("Decision", body_d)
        self.assertIn("Action", body_a)

    def test_digest_with_special_characters(self):
        cards = [{"id": "a1", "kind": "legal", "project": "p", "title": "Approve <script>alert(1)</script>"}]
        title, body = ap.build_digest(cards)
        self.assertIn("<script>", body)

    def test_digest_pluralization_boundary_cases(self):
        for n in [1, 2, 10, 100]:
            cards = [{"id": f"a{i}", "kind": "legal", "project": "p", "title": f"T{i}"} for i in range(n)]
            title, _ = ap.build_digest(cards)
            if n == 1:
                self.assertIn("1 decision need", title)
                self.assertNotIn("decisions", title)
            else:
                self.assertIn(f"{n} decisions need", title)

    def test_digest_always_includes_cockpit_pointer(self):
        cards = [{"id": "a1", "kind": "legal", "project": "p", "title": "T"}]
        _, body = ap.build_digest(cards)
        self.assertIn("cockpit", body)
        self.assertNotIn("sig=", body)


class FilteringLogicTest(unittest.TestCase):
    """Test approval filtering in run() method."""

    def _run_with_cards(self, cards, policy_fn=None, **env_vars):
        """Helper to run with mocked cards and policy."""
        def fake_select(table, params=None):
            if table == "notifications":
                return []
            return cards

        if policy_fn is None:
            policy_fn = lambda a: True

        policy = type("P", (), {"is_legal_gated": staticmethod(policy_fn)})()
        notify_spy = {"calls": []}

        def fake_notify(msg):
            notify_spy["calls"].append(msg)

        env = dict(os.environ)
        env["APPROVAL_DIGEST_BATCHING"] = "1"
        env["APPROVAL_PUSH_EMAIL"] = "test@example.com"
        env["APPROVAL_LINK_SIGNING_KEY"] = GOOD_KEY
        env.update(env_vars)

        with patch.dict(os.environ, env, clear=True):
            mod = importlib.reload(ap)
            with patch.object(mod.db, "select", side_effect=fake_select), \
                 patch.object(mod.db, "insert") as mock_insert, \
                 patch.dict(sys.modules, {"approval_policy": policy, "notify": type("N", (), {"send": fake_notify})()}):
                pushed = mod.run()

        importlib.reload(ap)
        return pushed, mock_insert, notify_spy["calls"]

    def test_only_legal_gated_approvals_are_pushed(self):
        cards = [
            {"id": "a1", "kind": "legal", "title": "Legal gated", "legal_risk_level": "high"},
            {"id": "a2", "kind": "legal", "title": "Not gated", "legal_risk_level": "high"},
        ]
        policy_fn = lambda a: a["id"] == "a1"
        pushed, _, _ = self._run_with_cards(cards, policy_fn=policy_fn)
        self.assertEqual(pushed, 1)

    def test_routine_legal_approvals_are_skipped(self):
        cards = [
            {"id": "a1", "kind": "legal", "title": "Routine", "legal_risk_level": "routine"},
        ]
        pushed, _, _ = self._run_with_cards(cards)
        self.assertEqual(pushed, 0)

    def test_non_routine_legal_approvals_are_included(self):
        cards = [
            {"id": "a1", "kind": "legal", "title": "High risk", "legal_risk_level": "high"},
            {"id": "a2", "kind": "legal", "title": "Medium risk", "legal_risk_level": "medium"},
            {"id": "a3", "kind": "legal", "title": "Routine is skipped", "legal_risk_level": "routine"},
        ]
        pushed, _, _ = self._run_with_cards(cards)
        self.assertEqual(pushed, 2)

    def test_material_approvals_are_included(self):
        cards = [
            {"id": "a1", "kind": "material", "title": "Material", "legal_risk_level": None},
        ]
        pushed, _, _ = self._run_with_cards(cards)
        self.assertEqual(pushed, 1)

    def test_operator_approvals_are_included(self):
        cards = [
            {"id": "a1", "kind": "operator", "title": "Operator action", "legal_risk_level": None},
        ]
        pushed, _, _ = self._run_with_cards(cards)
        self.assertEqual(pushed, 1)

    def test_secret_approvals_are_included(self):
        cards = [
            {"id": "a1", "kind": "secret", "title": "Secret action", "legal_risk_level": None},
        ]
        pushed, _, _ = self._run_with_cards(cards)
        self.assertEqual(pushed, 1)

    def test_limit_parameter_respects_database_limit(self):
        """run(limit=5) should be passed to db.select()."""
        cards = [{"id": f"a{i}", "kind": "legal", "title": f"Card {i}", "legal_risk_level": "high"} for i in range(10)]

        def fake_select(table, params=None):
            if table == "notifications":
                return []
            # Verify limit was passed
            self.assertEqual(params.get("limit"), "5")
            return cards[:5]

        policy = type("P", (), {"is_legal_gated": staticmethod(lambda a: True)})()
        env = dict(os.environ)
        env["APPROVAL_DIGEST_BATCHING"] = "1"
        env["APPROVAL_PUSH_EMAIL"] = "test@example.com"
        env["APPROVAL_LINK_SIGNING_KEY"] = GOOD_KEY

        with patch.dict(os.environ, env, clear=True):
            mod = importlib.reload(ap)
            with patch.object(mod.db, "select", side_effect=fake_select), \
                 patch.object(mod.db, "insert"), \
                 patch.dict(sys.modules, {"approval_policy": policy, "notify": type("N", (), {"send": lambda m: None})()}):
                mod.run(limit=5)

        importlib.reload(ap)


class BriefJsonHandlingTest(unittest.TestCase):
    """Test brief_json field handling in approval cards."""

    def _run_with_brief(self, brief_json):
        cards = [
            {
                "id": "a1", "kind": "legal", "title": "Test",
                "legal_risk_level": "high", "brief_json": brief_json
            }
        ]

        def fake_select(table, params=None):
            if table == "notifications":
                return []
            return cards

        policy = type("P", (), {"is_legal_gated": staticmethod(lambda a: True)})()
        env = dict(os.environ)
        env["APPROVAL_DIGEST_BATCHING"] = "0"
        env["APPROVAL_PUSH_EMAIL"] = "test@example.com"
        env["APPROVAL_LINK_SIGNING_KEY"] = GOOD_KEY

        with patch.dict(os.environ, env, clear=True):
            mod = importlib.reload(ap)
            with patch.object(mod.db, "select", side_effect=fake_select), \
                 patch.object(mod.db, "insert") as mock_insert, \
                 patch.dict(sys.modules, {"approval_policy": policy, "notify": type("N", (), {"send": lambda m: None})()}):
                mod.run()

            # Check what was inserted
            inserted = mock_insert.call_args_list
            importlib.reload(ap)
            return inserted

    def test_valid_dict_brief_json_includes_question(self):
        brief = {"question": "Should we proceed?", "context": "xyz"}
        calls = self._run_with_brief(brief)
        bodies = [call[0][1]["body"] for call in calls if call[0][0] == "notifications" and "QUESTION" in call[0][1].get("body", "")]
        self.assertTrue(len(bodies) > 0)
        self.assertIn("Should we proceed?", bodies[0])

    def test_string_brief_json_is_parsed(self):
        # PRODUCT FIX: run() did `bj = a.get("brief_json") or {}` and then guarded on
        # isinstance(bj, dict), so a text-encoded jsonb column silently dropped the
        # owner's QUESTION headline. approval_push.run() now json.loads() a string
        # brief_json, matching what it already does for `alternatives` and what
        # decision_confidence_autodecide does for this very column.
        brief = '{"question": "Parse me", "data": "yes"}'
        calls = self._run_with_brief(brief)
        bodies = [call[0][1]["body"] for call in calls if call[0][0] == "notifications" and "QUESTION" in call[0][1].get("body", "")]
        self.assertTrue(len(bodies) > 0)
        self.assertIn("QUESTION: Parse me", bodies[0])

    def test_invalid_json_string_is_ignored(self):
        # FIX (assertion was vacuous): this only checked that *some* insert happened,
        # which is true even if run() had rendered the raw garbage into the email. The
        # documented behaviour is "ignore the malformed JSON": the card still pushes, and
        # the body carries no QUESTION section and none of the unparsed text.
        brief = "{not valid json"
        calls = self._run_with_brief(brief)
        bodies = [c[0][1]["body"] for c in calls if c[0][0] == "notifications"]
        self.assertTrue(bodies)
        for body in bodies:
            self.assertNotIn("QUESTION:", body)
            self.assertNotIn("not valid json", body)

    def test_null_brief_json_is_handled(self):
        # FIX (assertion was vacuous): see above. A null brief_json must still push the
        # card, just with no QUESTION headline.
        brief = None
        calls = self._run_with_brief(brief)
        bodies = [c[0][1]["body"] for c in calls if c[0][0] == "notifications"]
        self.assertTrue(bodies)
        for body in bodies:
            self.assertNotIn("QUESTION:", body)

    def test_missing_brief_json_field(self):
        cards = [
            {"id": "a1", "kind": "legal", "title": "Test", "legal_risk_level": "high"}
        ]

        def fake_select(table, params=None):
            if table == "notifications":
                return []
            return cards

        policy = type("P", (), {"is_legal_gated": staticmethod(lambda a: True)})()
        env = dict(os.environ)
        env["APPROVAL_DIGEST_BATCHING"] = "0"
        env["APPROVAL_PUSH_EMAIL"] = "test@example.com"
        env["APPROVAL_LINK_SIGNING_KEY"] = GOOD_KEY

        with patch.dict(os.environ, env, clear=True):
            mod = importlib.reload(ap)
            with patch.object(mod.db, "select", side_effect=fake_select), \
                 patch.object(mod.db, "insert") as mock_insert, \
                 patch.dict(sys.modules, {"approval_policy": policy, "notify": type("N", (), {"send": lambda m: None})()}):
                pushed = mod.run()
                self.assertEqual(pushed, 1)

            importlib.reload(ap)


class AlternativesHandlingTest(unittest.TestCase):
    """Test alternatives/options field handling."""

    # FIX (test was wrong): every test in this class called ap._links_block() with no
    # APPROVAL_LINK_SIGNING_KEY in the environment. _signing_key() then raises
    # SigningKeyUnavailable by design (an empty-key HMAC is publicly computable, so the
    # module refuses to sign) and _links_block() correctly returns the unsigned cockpit
    # pointer, which contains none of the option text these tests assert on. The tests
    # were asserting against a security fallback they never meant to exercise. Configuring
    # a real key puts them back on the signed path they were written for; the unsigned
    # fallback is covered separately by test_links_block_without_key_is_unsigned below.
    def setUp(self):
        self._env = patch.dict(os.environ, {"APPROVAL_LINK_SIGNING_KEY": GOOD_KEY})
        self._env.start()
        self.addCleanup(self._env.stop)

    def test_links_block_without_key_is_unsigned(self):
        """With no signing key the block must degrade to an unsigned cockpit pointer."""
        card = {"id": "a1", "title": "Test", "alternatives": [{"label": "Option 1"}]}
        env = {k: v for k, v in os.environ.items()
               if k not in ("APPROVAL_LINK_SIGNING_KEY", "APPROVAL_LINK_ALLOW_SERVICE_KEY")}
        with patch.dict(os.environ, env, clear=True):
            block = ap._links_block(card)
        self.assertIn("One-click links are disabled", block)
        self.assertIn("a1", block)
        self.assertNotIn("sig=", block)
        self.assertNotIn("OPTION 1", block)

    def test_alternatives_as_list_of_dicts(self):
        alts = [
            {"label": "Option 1", "description": "First option", "recommended": True},
            {"label": "Option 2", "risk": "high", "reversible": False},
        ]
        card = {"id": "a1", "title": "Test", "alternatives": alts}
        block = ap._links_block(card)
        self.assertIn("Option 1", block)
        self.assertIn("RECOMMENDED", block)
        self.assertIn("HARD TO REVERSE", block)

    def test_alternatives_as_list_of_strings(self):
        alts = ["Simple option 1", "Simple option 2"]
        card = {"id": "a1", "title": "Test", "alternatives": alts}
        block = ap._links_block(card)
        self.assertIn("Simple option 1", block)

    def test_alternatives_json_string_is_parsed(self):
        alts_json = '[{"label": "Parsed option"}]'
        card = {"id": "a1", "title": "Test", "alternatives": alts_json}
        block = ap._links_block(card)
        self.assertIn("Parsed option", block)

    def test_alternatives_limit_to_four_options(self):
        alts = [{"label": f"Option {i}"} for i in range(10)]
        card = {"id": "a1", "title": "Test", "alternatives": alts}
        block = ap._links_block(card)
        self.assertIn("OPTION 1", block)
        self.assertIn("OPTION 4", block)
        self.assertNotIn("OPTION 5", block)

    def test_alternative_label_truncation(self):
        alts = [{"label": "x" * 150}]
        card = {"id": "a1", "title": "Test", "alternatives": alts}
        block = ap._links_block(card)
        self.assertIn("x" * 90, block)

    def test_alternative_description_truncation(self):
        alts = [{"label": "Option", "description": "y" * 300}]
        card = {"id": "a1", "title": "Test", "alternatives": alts}
        block = ap._links_block(card)
        self.assertIn("y" * 200, block)
        self.assertNotIn("y" * 201, block)

    def test_alternative_with_missing_risk_shows_question_mark(self):
        alts = [{"label": "Option"}]
        card = {"id": "a1", "title": "Test", "alternatives": alts}
        block = ap._links_block(card)
        self.assertIn("[risk: ?", block)

    def test_invalid_json_alternatives_defaults_to_empty(self):
        card = {"id": "a1", "title": "Test", "alternatives": "{invalid"}
        block = ap._links_block(card)
        # Should still have approve/deny/defer links, just no options
        self.assertIn("APPROVE", block)


class ConfigurationEdgeCasesTest(unittest.TestCase):
    """Test environment variable and configuration edge cases."""

    def test_both_email_and_orch_owner_email_prefers_approval_push(self):
        env = {
            "APPROVAL_PUSH_EMAIL": "push@example.com",
            "ORCH_OWNER_EMAIL": "owner@example.com",
        }
        with patch.dict(os.environ, env, clear=True):
            mod = importlib.reload(ap)
            self.assertEqual(mod.AUDIENCE, "push@example.com")
        importlib.reload(ap)

    def test_audience_strips_whitespace(self):
        env = {"APPROVAL_PUSH_EMAIL": "  user@example.com  "}
        with patch.dict(os.environ, env, clear=True):
            mod = importlib.reload(ap)
            self.assertEqual(mod.AUDIENCE, "user@example.com")
        importlib.reload(ap)

    def test_digest_batching_truthy_values(self):
        for val in ("1", "true", "yes", "on", "TRUE", "YES", "ON"):
            env = {"APPROVAL_DIGEST_BATCHING": val}
            with patch.dict(os.environ, env, clear=True):
                mod = importlib.reload(ap)
                self.assertTrue(mod._digest_enabled(), f"Failed for value: {val}")
        importlib.reload(ap)

    def test_digest_batching_falsy_values(self):
        for val in ("0", "false", "no", "off", "FALSE", "NO", ""):
            env = {"APPROVAL_DIGEST_BATCHING": val}
            with patch.dict(os.environ, env, clear=True):
                mod = importlib.reload(ap)
                self.assertFalse(mod._digest_enabled(), f"Failed for value: {val}")
        importlib.reload(ap)

    def test_digest_batching_whitespace_handling(self):
        env = {"APPROVAL_DIGEST_BATCHING": "  1  "}
        with patch.dict(os.environ, env, clear=True):
            mod = importlib.reload(ap)
            self.assertTrue(mod._digest_enabled())
        importlib.reload(ap)

    def test_missing_audience_is_empty_string(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("APPROVAL_PUSH_EMAIL", "ORCH_OWNER_EMAIL")}
        with patch.dict(os.environ, env, clear=True):
            mod = importlib.reload(ap)
            self.assertEqual(mod.AUDIENCE, "")
        importlib.reload(ap)


class EmailRowBehaviorTest(unittest.TestCase):
    """Test email notification row creation behavior."""

    def _run_with_audience(self, audience):
        cards = [{"id": "a1", "kind": "legal", "title": "Test", "legal_risk_level": "high"}]

        def fake_select(table, params=None):
            if table == "notifications":
                return []
            return cards

        policy = type("P", (), {"is_legal_gated": staticmethod(lambda a: True)})()
        env = dict(os.environ)
        env["APPROVAL_DIGEST_BATCHING"] = "0"
        if audience is not None:
            env["APPROVAL_PUSH_EMAIL"] = audience
        env["APPROVAL_LINK_SIGNING_KEY"] = GOOD_KEY

        rows_inserted = []

        def fake_insert(table, row):
            rows_inserted.append(row)

        with patch.dict(os.environ, env, clear=True):
            mod = importlib.reload(ap)
            with patch.object(mod.db, "select", side_effect=fake_select), \
                 patch.object(mod.db, "insert", side_effect=fake_insert), \
                 patch.dict(sys.modules, {"approval_policy": policy, "notify": type("N", (), {"send": lambda m: None})()}):
                mod.run()

        importlib.reload(ap)
        return rows_inserted

    def test_email_row_created_when_audience_configured(self):
        rows = self._run_with_audience("user@example.com")
        email_rows = [r for r in rows if r.get("channel") == "email"]
        self.assertEqual(len(email_rows), 1)

    def test_email_row_not_created_when_no_audience(self):
        rows = self._run_with_audience(None)
        email_rows = [r for r in rows if r.get("channel") == "email"]
        self.assertEqual(len(email_rows), 0)

    def test_email_row_not_created_when_empty_audience(self):
        rows = self._run_with_audience("")
        email_rows = [r for r in rows if r.get("channel") == "email"]
        self.assertEqual(len(email_rows), 0)

    def test_smarter_row_created_always(self):
        rows = self._run_with_audience(None)
        smarter_rows = [r for r in rows if r.get("channel") == "smarter"]
        self.assertEqual(len(smarter_rows), 1)


class ErrorResilienceTest(unittest.TestCase):
    """Test error handling and graceful degradation."""

    def test_db_insert_error_in_digest_does_not_crash(self):
        cards = [{"id": "a1", "kind": "legal", "title": "Test", "legal_risk_level": "high"}]

        def fake_select(table, params=None):
            if table == "notifications":
                return []
            return cards

        policy = type("P", (), {"is_legal_gated": staticmethod(lambda a: True)})()

        call_count = [0]
        def fake_insert(table, row):
            call_count[0] += 1
            if call_count[0] > 2 and row.get("channel") == "digest":
                raise Exception("DB error")

        env = dict(os.environ)
        env["APPROVAL_DIGEST_BATCHING"] = "1"
        env["APPROVAL_PUSH_EMAIL"] = "test@example.com"
        env["APPROVAL_LINK_SIGNING_KEY"] = GOOD_KEY

        with patch.dict(os.environ, env, clear=True):
            mod = importlib.reload(ap)
            with patch.object(mod.db, "select", side_effect=fake_select), \
                 patch.object(mod.db, "insert", side_effect=fake_insert), \
                 patch.dict(sys.modules, {"approval_policy": policy, "notify": type("N", (), {"send": lambda m: None})()}):
                pushed = mod.run()
                self.assertEqual(pushed, 1)

        importlib.reload(ap)

    def test_notify_send_error_does_not_crash(self):
        cards = [{"id": "a1", "kind": "legal", "title": "Test", "legal_risk_level": "high"}]

        def fake_select(table, params=None):
            if table == "notifications":
                return []
            return cards

        policy = type("P", (), {"is_legal_gated": staticmethod(lambda a: True)})()

        def fake_notify_error(msg):
            raise Exception("Notify error")

        env = dict(os.environ)
        env["APPROVAL_DIGEST_BATCHING"] = "1"
        env["APPROVAL_PUSH_EMAIL"] = "test@example.com"
        env["APPROVAL_LINK_SIGNING_KEY"] = GOOD_KEY

        with patch.dict(os.environ, env, clear=True):
            mod = importlib.reload(ap)
            with patch.object(mod.db, "select", side_effect=fake_select), \
                 patch.object(mod.db, "insert"), \
                 patch.dict(sys.modules, {"approval_policy": policy, "notify": type("N", (), {"send": fake_notify_error})()}):
                pushed = mod.run()
                self.assertEqual(pushed, 1)

        importlib.reload(ap)

    def test_db_select_returns_none_is_handled(self):
        def fake_select(table, params=None):
            return None

        policy = type("P", (), {"is_legal_gated": staticmethod(lambda a: True)})()
        env = dict(os.environ)
        env["APPROVAL_DIGEST_BATCHING"] = "1"
        env["APPROVAL_PUSH_EMAIL"] = "test@example.com"
        env["APPROVAL_LINK_SIGNING_KEY"] = GOOD_KEY

        with patch.dict(os.environ, env, clear=True):
            mod = importlib.reload(ap)
            with patch.object(mod.db, "select", side_effect=fake_select), \
                 patch.object(mod.db, "insert"), \
                 patch.dict(sys.modules, {"approval_policy": policy, "notify": type("N", (), {"send": lambda m: None})()}):
                pushed = mod.run()
                self.assertEqual(pushed, 0)

        importlib.reload(ap)


class NotificationChannelTest(unittest.TestCase):
    """Test notification channel behavior and row structure."""

    def _run_and_get_inserts(self, **env_vars):
        cards = [
            {"id": "a1", "kind": "legal", "title": "Test 1", "legal_risk_level": "high", "project": "p1"},
            {"id": "a2", "kind": "material", "title": "Test 2", "legal_risk_level": None, "project": "p2"},
        ]

        def fake_select(table, params=None):
            if table == "notifications":
                return []
            return cards

        policy = type("P", (), {"is_legal_gated": staticmethod(lambda a: True)})()
        inserts = []

        def fake_insert(table, row):
            inserts.append(row)

        env = dict(os.environ)
        env["APPROVAL_LINK_SIGNING_KEY"] = GOOD_KEY
        # FIX (test was wrong): the digest-row tests below used to assert that run() had
        # inserted the `digest` notification row by the time it returned. It has not, and
        # by design: ApprovalBatcher.append() only sends when the time window expires
        # (ORCH_APPROVAL_BATCH_WINDOW_MS, default 30s) or the item count reaches
        # ORCH_APPROVAL_BATCH_SIZE (default 50). With two cards neither trigger fires
        # inside run(), so digest_rows was empty and the tests blew up on digest_rows[0].
        # Setting the count threshold to the number of cards exercises the real
        # count-threshold flush path synchronously instead of racing a 30s daemon timer.
        env.setdefault("ORCH_APPROVAL_BATCH_SIZE", str(len(cards)))
        env.update(env_vars)

        with patch.dict(os.environ, env, clear=True):
            mod = importlib.reload(ap)
            with patch.object(mod.db, "select", side_effect=fake_select), \
                 patch.object(mod.db, "insert", side_effect=fake_insert), \
                 patch.dict(sys.modules, {"approval_policy": policy, "notify": type("N", (), {"send": lambda m: None})()}):
                mod.run()

        importlib.reload(ap)
        return inserts

    def test_per_card_email_rows_have_correct_structure(self):
        inserts = self._run_and_get_inserts(
            APPROVAL_DIGEST_BATCHING="0",
            APPROVAL_PUSH_EMAIL="user@example.com"
        )
        email_rows = [r for r in inserts if r.get("channel") == "email"]
        self.assertEqual(len(email_rows), 2)
        for row in email_rows:
            self.assertIn("title", row)
            self.assertIn("body", row)
            self.assertIn("approval_id", row)
            self.assertIn("kind", row)
            self.assertEqual(row["sent"], False)
            self.assertEqual(row["audience"], "user@example.com")

    def test_digest_row_uses_first_approval_id(self):
        inserts = self._run_and_get_inserts(
            APPROVAL_DIGEST_BATCHING="1",
            APPROVAL_PUSH_EMAIL="user@example.com"
        )
        digest_rows = [r for r in inserts if r.get("channel") == "digest"]
        self.assertEqual(len(digest_rows), 1)
        self.assertEqual(digest_rows[0]["approval_id"], "a1")

    def test_digest_row_structure(self):
        inserts = self._run_and_get_inserts(
            APPROVAL_DIGEST_BATCHING="1",
            APPROVAL_PUSH_EMAIL="user@example.com"
        )
        digest_rows = [r for r in inserts if r.get("channel") == "digest"]
        row = digest_rows[0]
        self.assertEqual(row["kind"], "digest")
        self.assertIn("2 decisions", row["title"])
        self.assertEqual(row["sent"], False)

    def test_title_field_truncation(self):
        cards = [{"id": "a1", "kind": "legal", "title": "x" * 300, "legal_risk_level": "high"}]

        def fake_select(table, params=None):
            if table == "notifications":
                return []
            return cards

        policy = type("P", (), {"is_legal_gated": staticmethod(lambda a: True)})()
        inserts = []

        def fake_insert(table, row):
            inserts.append(row)

        env = {
            "APPROVAL_DIGEST_BATCHING": "0",
            "APPROVAL_PUSH_EMAIL": "test@example.com",
            "APPROVAL_LINK_SIGNING_KEY": GOOD_KEY,
        }

        with patch.dict(os.environ, env, clear=True):
            mod = importlib.reload(ap)
            with patch.object(mod.db, "select", side_effect=fake_select), \
                 patch.object(mod.db, "insert", side_effect=fake_insert), \
                 patch.dict(sys.modules, {"approval_policy": policy, "notify": type("N", (), {"send": lambda m: None})()}):
                mod.run()

        importlib.reload(ap)
        for row in inserts:
            if "title" in row:
                self.assertLessEqual(len(row["title"]), 180)

    def test_body_field_truncation(self):
        cards = [{"id": "a1", "kind": "legal", "title": "T", "why": "y" * 2000, "legal_risk_level": "high"}]

        def fake_select(table, params=None):
            if table == "notifications":
                return []
            return cards

        policy = type("P", (), {"is_legal_gated": staticmethod(lambda a: True)})()
        inserts = []

        def fake_insert(table, row):
            inserts.append(row)

        env = {
            "APPROVAL_DIGEST_BATCHING": "0",
            "APPROVAL_PUSH_EMAIL": "test@example.com",
            "APPROVAL_LINK_SIGNING_KEY": GOOD_KEY,
        }

        with patch.dict(os.environ, env, clear=True):
            mod = importlib.reload(ap)
            with patch.object(mod.db, "select", side_effect=fake_select), \
                 patch.object(mod.db, "insert", side_effect=fake_insert), \
                 patch.dict(sys.modules, {"approval_policy": policy, "notify": type("N", (), {"send": lambda m: None})()}):
                mod.run()

        importlib.reload(ap)
        for row in inserts:
            if "body" in row:
                self.assertLessEqual(len(row["body"]), 4000)


class CardFieldHandlingTest(unittest.TestCase):
    """Test handling of various card fields in notification body."""

    def _run_and_get_body(self, card):
        def fake_select(table, params=None):
            if table == "notifications":
                return []
            return [card]

        policy = type("P", (), {"is_legal_gated": staticmethod(lambda a: True)})()
        body_result = []

        def fake_insert(table, row):
            if row.get("channel") == "email":
                body_result.append(row["body"])

        env = {
            "APPROVAL_DIGEST_BATCHING": "0",
            "APPROVAL_PUSH_EMAIL": "test@example.com",
            "APPROVAL_LINK_SIGNING_KEY": GOOD_KEY,
        }

        with patch.dict(os.environ, env, clear=True):
            mod = importlib.reload(ap)
            with patch.object(mod.db, "select", side_effect=fake_select), \
                 patch.object(mod.db, "insert", side_effect=fake_insert), \
                 patch.dict(sys.modules, {"approval_policy": policy, "notify": type("N", (), {"send": lambda m: None})()}):
                mod.run()

        importlib.reload(ap)
        return body_result[0] if body_result else ""

    def test_why_field_is_included(self):
        card = {"id": "a1", "kind": "legal", "title": "T", "legal_risk_level": "high", "why": "Important reason"}
        body = self._run_and_get_body(card)
        self.assertIn("WHY:", body)
        self.assertIn("Important reason", body)

    def test_value_field_is_included(self):
        card = {"id": "a1", "kind": "legal", "title": "T", "legal_risk_level": "high", "value": "High value"}
        body = self._run_and_get_body(card)
        self.assertIn("VALUE:", body)
        self.assertIn("High value", body)

    def test_risk_field_is_included(self):
        card = {"id": "a1", "kind": "legal", "title": "T", "legal_risk_level": "high", "risk": "Low risk"}
        body = self._run_and_get_body(card)
        self.assertIn("RISK:", body)
        self.assertIn("Low risk", body)

    def test_prebrief_field_is_included(self):
        card = {"id": "a1", "kind": "legal", "title": "T", "legal_risk_level": "high", "prebrief": "Initial brief"}
        body = self._run_and_get_body(card)
        self.assertIn("BRIEF:", body)
        self.assertIn("Initial brief", body)

    def test_long_why_field_is_truncated(self):
        card = {"id": "a1", "kind": "legal", "title": "T", "legal_risk_level": "high", "why": "x" * 1000}
        body = self._run_and_get_body(card)
        self.assertIn("WHY:", body)
        self.assertIn("x" * 700, body)


if __name__ == "__main__":
    unittest.main()
