#!/usr/bin/env python3
"""Tests for config_approval.py — AI-based fleet_config change assessment."""
import os, sys, unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import config_approval as ca


class TestAssess(unittest.TestCase):
    """Unit tests for the _assess() risk classifier."""

    # ---- safe / auto-approve cases ----

    def test_routine_string_value(self):
        risk, _ = ca._assess("ORCH_AUTO_PULL_MIN", "5")
        self.assertEqual(risk, "low")

    def test_numeric_in_bounds(self):
        risk, _ = ca._assess("MAX_PARALLEL", "4")
        self.assertEqual(risk, "low")

    def test_orch_auto_pull_true(self):
        risk, _ = ca._assess("ORCH_AUTO_PULL", "true")
        self.assertEqual(risk, "low")

    def test_unknown_orch_key_safe(self):
        risk, _ = ca._assess("ORCH_SOME_NEW_FLAG", "enabled")
        self.assertEqual(risk, "low")

    def test_task_timeout_in_bounds(self):
        risk, _ = ca._assess("TASK_TIMEOUT", "1800")
        self.assertEqual(risk, "low")

    def test_boolean_false_non_critical_key(self):
        # disabling a non-critical flag is fine
        risk, _ = ca._assess("ENABLE_SPECULATIVE", "false")
        self.assertEqual(risk, "low")

    # ---- high-risk cases ----

    def test_max_parallel_zero(self):
        risk, reason = ca._assess("MAX_PARALLEL", "0")
        self.assertEqual(risk, "high")
        self.assertIn("safe range", reason)

    def test_max_parallel_too_high(self):
        risk, reason = ca._assess("MAX_PARALLEL", "50")
        self.assertEqual(risk, "high")
        self.assertIn("safe range", reason)

    def test_task_timeout_too_low(self):
        risk, reason = ca._assess("TASK_TIMEOUT", "10")
        self.assertEqual(risk, "high")
        self.assertIn("safe range", reason)

    def test_task_timeout_too_high(self):
        risk, reason = ca._assess("TASK_TIMEOUT", "99999")
        self.assertEqual(risk, "high")

    def test_non_numeric_for_numeric_key(self):
        risk, reason = ca._assess("MAX_PARALLEL", "lots")
        self.assertEqual(risk, "high")
        self.assertIn("expects a number", reason)

    def test_shell_semicolon_injection(self):
        risk, reason = ca._assess("ORCH_EXTRA_FLAG", "value;rm -rf /")
        self.assertEqual(risk, "high")
        self.assertIn("metacharacter", reason)

    def test_shell_pipe_injection(self):
        risk, reason = ca._assess("SOME_KEY", "foo|bar")
        self.assertEqual(risk, "high")

    def test_shell_subst_injection(self):
        risk, reason = ca._assess("SOME_KEY", "$(whoami)")
        self.assertEqual(risk, "high")

    def test_backtick_injection(self):
        risk, reason = ca._assess("SOME_KEY", "`id`")
        self.assertEqual(risk, "high")

    def test_absolute_path_value(self):
        risk, reason = ca._assess("SOME_KEY", "/etc/passwd")
        self.assertEqual(risk, "high")
        self.assertIn("path", reason)

    def test_tilde_path_value(self):
        risk, reason = ca._assess("SOME_KEY", "~/secret")
        self.assertEqual(risk, "high")

    def test_url_in_value(self):
        risk, reason = ca._assess("SOME_KEY", "https://attacker.com/payload")
        self.assertEqual(risk, "high")
        self.assertIn("URL", reason)

    def test_credential_keys_are_gated_not_routine(self):
        # The 2026-08-02 incident class: every one of these used to assess as
        # "routine change within safe operating envelope".
        for key, value in [
            ("GITHUB_PAT", "ghp_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"),
            ("VERCEL_TOKEN", "2f8Kq9WxLm3PzT7bR4nHvC1d"),
            ("ANTHROPIC_API_KEY", "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789"),
            ("SLACK_BOT_TOKEN", "xoxb-2334-4444-abcdefghijklmnop"),
            ("DB_PASSWORD", "hunter2correcthorsebattery"),
            ("SUPABASE_SERVICE_SECRET", "abcdefghijklmnopqrstuvwxyz"),
        ]:
            with self.subTest(key=key):
                risk, reason = ca._assess(key, value)
                self.assertEqual(risk, "high")
                self.assertIn("credential material", reason)

    def test_credential_shape_is_gated_under_an_innocent_key_name(self):
        for value in [
            "ghp_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8",
            "AKIAIOSFODNN7EXAMPLE",
            "-----BEGIN RSA PRIVATE KEY-----",
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r",
        ]:
            with self.subTest(value=value[:20]):
                risk, reason = ca._assess("ORCH_HARMLESS_LOOKING_FLAG", value)
                self.assertEqual(risk, "high")
                self.assertIn("credential material", reason)

    def test_secret_value_is_never_echoed_into_the_card_reason(self):
        token = "ghp_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
        _, reason = ca._assess("GITHUB_PAT", token)
        self.assertNotIn(token, reason)
        self.assertIn("redacted", reason)
        self.assertIn(str(len(token)), reason)

    def test_secret_reason_distinguishes_two_different_pushes(self):
        _, a = ca._assess("GITHUB_PAT", "ghp_" + "a" * 36)
        _, b = ca._assess("GITHUB_PAT", "ghp_" + "b" * 36)
        self.assertNotEqual(a, b)

    def test_secret_reference_is_not_gated(self):
        # Pointing at a secret is the correct pattern and must stay frictionless.
        for value in ["env:GITHUB_PAT", "${GITHUB_PAT}", "op://fleet/github/pat", ""]:
            with self.subTest(value=value):
                risk, _ = ca._assess("GITHUB_PAT", value)
                self.assertEqual(risk, "low")

    def test_ordinary_keys_are_not_swept_up_by_the_secret_rule(self):
        for key, value in [
            ("MAX_PARALLEL", "4"),
            ("ORCH_SOME_NEW_FLAG", "enabled"),
            ("ORCH_PASSTHROUGH_MODE", "on"),
            ("SOME_KEY", "plainvalue"),
        ]:
            with self.subTest(key=key):
                risk, _ = ca._assess(key, value)
                self.assertEqual(risk, "low")

    def test_orch_auto_pull_disabled(self):
        risk, reason = ca._assess("ORCH_AUTO_PULL", "false")
        self.assertEqual(risk, "high")
        self.assertIn("ORCH_AUTO_PULL", reason)

    def test_orch_auto_pull_zero_disabled(self):
        risk, reason = ca._assess("ORCH_AUTO_PULL", "0")
        self.assertEqual(risk, "high")

    def test_fleet_tick_too_low(self):
        risk, _ = ca._assess("ORCH_FLEET_TICK_S", "1")
        self.assertEqual(risk, "high")

    def test_fleet_tick_too_high(self):
        risk, _ = ca._assess("ORCH_FLEET_TICK_S", "999")
        self.assertEqual(risk, "high")


class TestFingerprint(unittest.TestCase):
    def test_same_input_same_fingerprint(self):
        self.assertEqual(ca._fingerprint("KEY", "val"), ca._fingerprint("KEY", "val"))

    def test_different_value_different_fingerprint(self):
        self.assertNotEqual(ca._fingerprint("KEY", "val1"), ca._fingerprint("KEY", "val2"))

    def test_different_key_different_fingerprint(self):
        self.assertNotEqual(ca._fingerprint("KEY1", "val"), ca._fingerprint("KEY2", "val"))

    def test_length(self):
        self.assertEqual(len(ca._fingerprint("K", "v")), 16)


class TestSweep(unittest.TestCase):

    def _make_db(self, config_rows, seen_fps=()):
        mock_db = MagicMock()
        # _seen_fingerprints() call: approvals select
        # sweep() call: fleet_config select
        def select_side(table, params=None):
            if table == "fleet_config":
                return config_rows
            if table == "approvals":
                return [{"detail": f"fp:{fp}"} for fp in seen_fps]
            return []
        mock_db.select.side_effect = select_side
        return mock_db

    def test_routine_change_auto_approved(self):
        rows = [{"key": "MAX_PARALLEL", "value": "4", "note": "", "updated_by": "op"}]
        mock_db = self._make_db(rows)
        with patch.object(ca, "db", mock_db):
            approved, gated = ca.sweep()
        self.assertEqual(approved, 1)
        self.assertEqual(gated, 0)
        inserted = mock_db.insert.call_args[0][1]
        self.assertEqual(inserted["status"], "approved")
        self.assertEqual(inserted["decided_by"], ca.POLICY_MARK)

    def test_risky_change_creates_pending_card(self):
        rows = [{"key": "MAX_PARALLEL", "value": "0", "note": "", "updated_by": "op"}]
        mock_db = self._make_db(rows)
        with patch.object(ca, "db", mock_db):
            approved, gated = ca.sweep()
        self.assertEqual(approved, 0)
        self.assertEqual(gated, 1)
        inserted = mock_db.insert.call_args[0][1]
        self.assertEqual(inserted["status"], "pending")
        self.assertIsNone(inserted.get("decided_by"))

    def test_already_seen_fingerprint_skipped(self):
        rows = [{"key": "MAX_PARALLEL", "value": "4", "note": "", "updated_by": "op"}]
        fp = ca._fingerprint("MAX_PARALLEL", "4")
        mock_db = self._make_db(rows, seen_fps=[fp])
        with patch.object(ca, "db", mock_db):
            approved, gated = ca.sweep()
        self.assertEqual(approved, 0)
        self.assertEqual(gated, 0)
        mock_db.insert.assert_not_called()

    def test_mixed_batch(self):
        rows = [
            {"key": "MAX_PARALLEL", "value": "4", "note": "", "updated_by": "op"},
            {"key": "ORCH_AUTO_PULL", "value": "false", "note": "", "updated_by": "op"},
            {"key": "TASK_TIMEOUT", "value": "1800", "note": "", "updated_by": "op"},
        ]
        mock_db = self._make_db(rows)
        with patch.object(ca, "db", mock_db):
            approved, gated = ca.sweep()
        self.assertEqual(approved, 2)  # MAX_PARALLEL=4 and TASK_TIMEOUT=1800 are safe
        self.assertEqual(gated, 1)    # ORCH_AUTO_PULL=false is risky

    def test_disabled_returns_zeros(self):
        with patch.object(ca, "ENABLED", False):
            self.assertEqual(ca.sweep(), (0, 0))

    def test_db_error_fails_soft(self):
        mock_db = MagicMock()
        mock_db.select.side_effect = RuntimeError("db down")
        with patch.object(ca, "db", mock_db):
            # should not raise
            result = ca.sweep()
        self.assertEqual(result, (0, 0))

    def test_card_contains_fingerprint_in_detail(self):
        rows = [{"key": "ORCH_FLEET_TICK_S", "value": "30", "note": "tick rate", "updated_by": "op"}]
        mock_db = self._make_db(rows)
        with patch.object(ca, "db", mock_db):
            ca.sweep()
        inserted = mock_db.insert.call_args[0][1]
        self.assertTrue(inserted["detail"].startswith("fp:"))

    def test_card_title_contains_key_and_value(self):
        rows = [{"key": "ORCH_EXTRA_CODERS", "value": "3", "note": "", "updated_by": "op"}]
        mock_db = self._make_db(rows)
        with patch.object(ca, "db", mock_db):
            ca.sweep()
        inserted = mock_db.insert.call_args[0][1]
        self.assertIn("ORCH_EXTRA_CODERS", inserted["title"])


class TestBlockedKeys(unittest.TestCase):

    def test_blocked_keys_from_pending_cards(self):
        mock_db = MagicMock()
        mock_db.select.return_value = [
            {"title": "fleet_config: MAX_PARALLEL='0'"},
            {"title": "fleet_config: ORCH_AUTO_PULL='false'"},
        ]
        with patch.object(ca, "db", mock_db):
            keys = ca.blocked_keys()
        self.assertIn("MAX_PARALLEL", keys)
        self.assertIn("ORCH_AUTO_PULL", keys)

    def test_no_blocked_keys_when_no_pending(self):
        mock_db = MagicMock()
        mock_db.select.return_value = []
        with patch.object(ca, "db", mock_db):
            keys = ca.blocked_keys()
        self.assertEqual(keys, set())

    def test_db_error_returns_empty_set(self):
        mock_db = MagicMock()
        mock_db.select.side_effect = RuntimeError("timeout")
        with patch.object(ca, "db", mock_db):
            keys = ca.blocked_keys()
        self.assertEqual(keys, set())

    def test_non_config_titles_not_extracted(self):
        mock_db = MagicMock()
        mock_db.select.return_value = [
            {"title": "some unrelated approval title"},
        ]
        with patch.object(ca, "db", mock_db):
            keys = ca.blocked_keys()
        self.assertEqual(keys, set())


class TestLoadConfigIntegration(unittest.TestCase):
    """Verify fleet_control.load_config() honors blocked_keys()."""

    def test_blocked_key_not_applied(self):
        import fleet_control
        rows = [
            {"key": "MAX_PARALLEL", "value": "0"},
            {"key": "ORCH_AUTO_PULL_MIN", "value": "5"},
        ]
        mock_db = MagicMock()
        mock_db.select.return_value = rows
        with patch.object(fleet_control, "db", mock_db), \
             patch.object(fleet_control.config_approval, "blocked_keys", return_value={"MAX_PARALLEL"}), \
             patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MAX_PARALLEL", None)
            os.environ.pop("ORCH_AUTO_PULL_MIN", None)
            fleet_control.load_config()
            self.assertNotIn("MAX_PARALLEL", os.environ)
            self.assertEqual(os.environ.get("ORCH_AUTO_PULL_MIN"), "5")

    def test_approved_key_applied_normally(self):
        import fleet_control
        rows = [{"key": "MAX_PARALLEL", "value": "4"}]
        mock_db = MagicMock()
        mock_db.select.return_value = rows
        # ORCH_CONFIG_ENV_PINS must be stated, not inherited. This operator's
        # runner/.env pins MAX_PARALLEL (among 19 other keys) to the local value,
        # and load_config reads that list straight out of os.environ — so the
        # result of this test depended on whose machine it ran on: green on a
        # clean checkout, red here, with the reason ("PINNED to local .env value
        # '<unset>'") only visible in captured stderr. The pin behaviour has its
        # own coverage in test_fleet_config_consumption.py; what this test is
        # about is an APPROVED key taking effect, so it pins nothing.
        with patch.object(fleet_control, "db", mock_db), \
             patch.object(fleet_control.config_approval, "blocked_keys", return_value=set()), \
             patch.dict(os.environ, {"ORCH_CONFIG_ENV_PINS": ""}, clear=False):
            os.environ.pop("MAX_PARALLEL", None)
            fleet_control.load_config()
            self.assertEqual(os.environ.get("MAX_PARALLEL"), "4")


if __name__ == "__main__":
    unittest.main()
