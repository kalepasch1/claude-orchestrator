"""
test_config_errors.py - simulate configuration management errors.

Scenarios:
  A) Incorrect property settings — safe-key filtering, bad value types
  B) Missing dependencies — DB unavailable, missing env vars, fallback defaults
  C) Version conflicts — env overrides DB, conflicting config states, error classification
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fleet_control
import control_flags
import retry_policy


# ── A: Incorrect property settings ────────────────────────────────────────────

class TestIncorrectPropertySettings(unittest.TestCase):

    def test_credential_key_in_db_is_silently_skipped(self):
        """load_config must never apply credential-marker keys from fleet_config to env."""
        fake_db = MagicMock()
        fake_db.select.return_value = [
            {"key": "ANTHROPIC_API_KEY", "value": "secret-value"},
            {"key": "ORCH_PARALLEL", "value": "4"},
        ]
        with patch.object(fleet_control, "db", fake_db):
            saved = os.environ.pop("ORCH_PARALLEL", None)
            os.environ.pop("ANTHROPIC_API_KEY", None)
            try:
                applied = fleet_control.load_config()
                self.assertEqual(applied, 1, "only the safe key should be applied")
                self.assertNotIn("ANTHROPIC_API_KEY", os.environ,
                                 "credential key must never reach env")
                self.assertEqual(os.environ.get("ORCH_PARALLEL"), "4")
            finally:
                os.environ.pop("ORCH_PARALLEL", None)
                if saved is not None:
                    os.environ["ORCH_PARALLEL"] = saved

    def test_key_without_safe_prefix_silently_skipped(self):
        """load_config must skip keys that don't match any safe prefix."""
        fake_db = MagicMock()
        fake_db.select.return_value = [
            {"key": "SOME_RANDOM_VAR", "value": "should-not-appear"},
            {"key": "ORCH_EXTRA_CODERS", "value": "2"},
        ]
        with patch.object(fleet_control, "db", fake_db):
            os.environ.pop("SOME_RANDOM_VAR", None)
            saved = os.environ.pop("ORCH_EXTRA_CODERS", None)
            try:
                applied = fleet_control.load_config()
                self.assertEqual(applied, 1)
                self.assertNotIn("SOME_RANDOM_VAR", os.environ)
            finally:
                os.environ.pop("ORCH_EXTRA_CODERS", None)
                if saved is not None:
                    os.environ["ORCH_EXTRA_CODERS"] = saved

    def test_safe_key_rejects_all_deny_markers(self):
        """_safe_key must reject any key containing KEY, SECRET, TOKEN, PASSWORD, PWD, CREDENTIAL."""
        deny_cases = [
            "OPENAI_API_KEY",
            "ORCH_SECRET_WORD",
            "SOME_TOKEN",
            "DB_PASSWORD",
            "DB_PWD",
            "MY_CREDENTIAL",
            "orch_api_key",       # lowercase is also rejected
            "orch_secret_value",
        ]
        for k in deny_cases:
            with self.subTest(key=k):
                self.assertFalse(fleet_control._safe_key(k),
                                 f"credential-marker key '{k}' should be rejected")

    def test_safe_key_accepts_all_safe_prefixes(self):
        """_safe_key must accept all documented safe prefix families."""
        accept_cases = [
            "ORCH_AUTO_PULL",
            "MAX_PARALLEL",
            "RAM_FLOOR_GB",
            "PER_TASK_GB",
            "RELEASE_BRANCH",
            "QUEUE_MAX",
            "COST_CIRCUIT",
            "DEPLOY_WINDOW",
            "ENABLE_PROACTIVE_LOOPS",
            "TASK_TIMEOUT",
            "DEFAULT_TEST_CMD",
        ]
        for k in accept_cases:
            with self.subTest(key=k):
                self.assertTrue(fleet_control._safe_key(k),
                                f"safe key '{k}' should be accepted")

    def test_load_config_handles_none_value_gracefully(self):
        """load_config must skip rows where value is None without crashing."""
        fake_db = MagicMock()
        fake_db.select.return_value = [
            {"key": "ORCH_SOME_FLAG", "value": None},
            {"key": "ORCH_OTHER_FLAG", "value": "true"},
        ]
        with patch.object(fleet_control, "db", fake_db):
            saved = os.environ.pop("ORCH_SOME_FLAG", None)
            saved2 = os.environ.pop("ORCH_OTHER_FLAG", None)
            try:
                applied = fleet_control.load_config()
                self.assertEqual(applied, 1, "None-value row should be skipped")
                self.assertNotIn("ORCH_SOME_FLAG", os.environ)
            finally:
                os.environ.pop("ORCH_SOME_FLAG", None)
                os.environ.pop("ORCH_OTHER_FLAG", None)
                if saved is not None:
                    os.environ["ORCH_SOME_FLAG"] = saved
                if saved2 is not None:
                    os.environ["ORCH_OTHER_FLAG"] = saved2

    def test_load_config_handles_empty_key_gracefully(self):
        """load_config must skip rows with missing/empty key field."""
        fake_db = MagicMock()
        fake_db.select.return_value = [
            {"key": "", "value": "some-value"},
            {"key": None, "value": "other-value"},
            {"key": "ORCH_VALID_FLAG", "value": "1"},
        ]
        with patch.object(fleet_control, "db", fake_db):
            saved = os.environ.pop("ORCH_VALID_FLAG", None)
            try:
                applied = fleet_control.load_config()
                self.assertEqual(applied, 1, "empty/null key rows must be skipped")
            finally:
                os.environ.pop("ORCH_VALID_FLAG", None)
                if saved is not None:
                    os.environ["ORCH_VALID_FLAG"] = saved

    def test_mixed_safe_and_unsafe_keys_only_safe_applied(self):
        """load_config with a mix of key types must apply only the safe ones."""
        fake_db = MagicMock()
        fake_db.select.return_value = [
            {"key": "ORCH_BUILD_MANDATE", "value": "true"},
            {"key": "SUPABASE_SERVICE_KEY", "value": "do-not-set"},
            {"key": "MAX_PARALLEL", "value": "3"},
            {"key": "SOME_RANDOM", "value": "nope"},
            {"key": "DEPLOY_STRATEGY", "value": "blue-green"},
        ]
        with patch.object(fleet_control, "db", fake_db):
            to_clean = ["ORCH_BUILD_MANDATE", "MAX_PARALLEL", "DEPLOY_STRATEGY",
                        "SUPABASE_SERVICE_KEY", "SOME_RANDOM"]
            saved = {k: os.environ.pop(k, None) for k in to_clean}
            try:
                applied = fleet_control.load_config()
                self.assertEqual(applied, 3)
                self.assertNotIn("SUPABASE_SERVICE_KEY", os.environ)
                self.assertNotIn("SOME_RANDOM", os.environ)
                self.assertEqual(os.environ.get("ORCH_BUILD_MANDATE"), "true")
                self.assertEqual(os.environ.get("MAX_PARALLEL"), "3")
                self.assertEqual(os.environ.get("DEPLOY_STRATEGY"), "blue-green")
            finally:
                for k in to_clean:
                    os.environ.pop(k, None)
                    if saved[k] is not None:
                        os.environ[k] = saved[k]


# ── B: Missing dependencies / misconfigured environment ───────────────────────

class TestMissingDependencies(unittest.TestCase):

    def test_get_bool_returns_default_when_db_is_unavailable(self):
        """get_bool must return the given default when both env and DB are unavailable."""
        import db as _db
        orig_select = _db.select
        _db.select = lambda *a, **kw: (_ for _ in ()).throw(Exception("connection refused"))
        os.environ.pop("ORCH_MY_FLAG", None)
        try:
            self.assertFalse(control_flags.get_bool("MY_FLAG", default=False))
            self.assertTrue(control_flags.get_bool("MY_FLAG", default=True))
        finally:
            _db.select = orig_select

    def test_get_bool_reads_env_var_before_db(self):
        """get_bool must honor ORCH_<KEY> env var without touching the DB."""
        import db as _db
        db_called = []
        orig_select = _db.select
        _db.select = lambda *a, **kw: db_called.append(1) or []
        os.environ["ORCH_MY_FEATURE"] = "true"
        try:
            result = control_flags.get_bool("MY_FEATURE", default=False)
            self.assertTrue(result, "env var ORCH_MY_FEATURE=true must return True")
            self.assertEqual(db_called, [], "DB must not be queried when env var is set")
        finally:
            os.environ.pop("ORCH_MY_FEATURE", None)
            _db.select = orig_select

    def test_get_bool_returns_default_when_db_returns_no_rows(self):
        """get_bool falls back to default when the controls table has no matching row."""
        import db as _db
        orig_select = _db.select
        _db.select = lambda *a, **kw: []
        os.environ.pop("ORCH_ABSENT_FLAG", None)
        try:
            self.assertFalse(control_flags.get_bool("ABSENT_FLAG", default=False))
            self.assertTrue(control_flags.get_bool("ABSENT_FLAG", default=True))
        finally:
            _db.select = orig_select

    def test_get_bool_handles_dict_value_with_enabled_key(self):
        """get_bool must parse {"enabled": true/false} JSON dict values from the DB."""
        import db as _db
        import json
        orig_select = _db.select

        def _select_enabled(table, q=None):
            if q and q.get("key", "").endswith("dict_flag"):
                return [{"key": "dict_flag", "value": json.dumps({"enabled": True})}]
            return []

        _db.select = _select_enabled
        os.environ.pop("ORCH_DICT_FLAG", None)
        try:
            self.assertTrue(control_flags.get_bool("dict_flag", default=False))
        finally:
            _db.select = orig_select

    def test_get_bool_handles_old_schema_paused_field(self):
        """get_bool must handle the old-style controls row (scope=config, paused field)."""
        import db as _db
        orig_select = _db.select
        call_count = [0]

        def _select_old_schema(table, q=None):
            call_count[0] += 1
            # first call (key-value schema) returns nothing
            if call_count[0] == 1:
                return []
            # second call (old scope=config schema) returns a paused=false row
            return [{"scope": "config", "project": "old_flag", "paused": False, "reason": ""}]

        _db.select = _select_old_schema
        os.environ.pop("ORCH_OLD_FLAG", None)
        try:
            # paused=False means the flag is ON (not paused = enabled)
            self.assertTrue(control_flags.get_bool("old_flag", default=False))
        finally:
            _db.select = orig_select

    def test_load_config_does_not_raise_when_db_unavailable(self):
        """load_config must return 0 and never raise when the DB throws."""
        fake_db = MagicMock()
        fake_db.select.side_effect = Exception("network unreachable")
        with patch.object(fleet_control, "db", fake_db):
            try:
                result = fleet_control.load_config()
            except Exception as e:
                self.fail(f"load_config raised unexpectedly: {e}")
            self.assertEqual(result, 0)

    def test_tick_never_raises_when_all_sub_calls_fail(self):
        """tick() must be fully fail-soft — never raise even if DB, git, and controls all fail."""
        fake_db = MagicMock()
        fake_db.select.side_effect = Exception("total failure")
        with patch.object(fleet_control, "db", fake_db), \
             patch.object(fleet_control, "kill_switch", MagicMock()):
            try:
                fleet_control.tick()
            except Exception as e:
                self.fail(f"tick() raised unexpectedly: {e}")

    def test_get_bool_env_var_false_string_values(self):
        """get_bool must correctly parse falsy string env values."""
        false_values = ["false", "0", "no", "off", "disabled"]
        for v in false_values:
            with self.subTest(value=v):
                os.environ["ORCH_TEST_FLAG_X"] = v
                try:
                    self.assertFalse(control_flags.get_bool("TEST_FLAG_X", default=True),
                                     f"env value '{v}' should parse as False")
                finally:
                    os.environ.pop("ORCH_TEST_FLAG_X", None)

    def test_get_bool_env_var_true_string_values(self):
        """get_bool must correctly parse all truthy string env values."""
        true_values = ["true", "1", "yes", "on", "enabled"]
        for v in true_values:
            with self.subTest(value=v):
                os.environ["ORCH_TEST_FLAG_Y"] = v
                try:
                    self.assertTrue(control_flags.get_bool("TEST_FLAG_Y", default=False),
                                    f"env value '{v}' should parse as True")
                finally:
                    os.environ.pop("ORCH_TEST_FLAG_Y", None)


# ── C: Version conflicts / conflicting config states ──────────────────────────

class TestVersionConflicts(unittest.TestCase):

    def test_env_var_overrides_conflicting_db_value(self):
        """When env ORCH_<KEY> and DB disagree, env wins without touching DB."""
        import db as _db
        orig_select = _db.select
        db_hit = []

        def _select_opposite(table, q=None):
            db_hit.append(1)
            return [{"key": "my_flag", "value": "false"}]  # DB says False

        _db.select = _select_opposite
        os.environ["ORCH_MY_FLAG"] = "true"  # env says True
        try:
            result = control_flags.get_bool("MY_FLAG", default=False)
            self.assertTrue(result, "env var must win over conflicting DB value")
            self.assertEqual(db_hit, [], "DB must not be consulted when env is set")
        finally:
            os.environ.pop("ORCH_MY_FLAG", None)
            _db.select = orig_select

    def test_later_load_config_overwrites_earlier_value(self):
        """A second load_config call with an updated DB value must update the env."""
        fake_db = MagicMock()
        fake_db.select.side_effect = [
            [{"key": "ORCH_PARALLEL_SETTING", "value": "2"}],
            [{"key": "ORCH_PARALLEL_SETTING", "value": "5"}],
        ]
        with patch.object(fleet_control, "db", fake_db):
            saved = os.environ.pop("ORCH_PARALLEL_SETTING", None)
            try:
                fleet_control.load_config()
                self.assertEqual(os.environ.get("ORCH_PARALLEL_SETTING"), "2")
                fleet_control.load_config()
                self.assertEqual(os.environ.get("ORCH_PARALLEL_SETTING"), "5",
                                 "second load must overwrite with updated value")
            finally:
                os.environ.pop("ORCH_PARALLEL_SETTING", None)
                if saved is not None:
                    os.environ["ORCH_PARALLEL_SETTING"] = saved

    def test_retry_policy_classifies_transient_errors(self):
        """classify must return 'transient' for network/rate-limit/provider errors."""
        transient_cases = [
            "Connection reset by peer",
            "urlopen error timed out",
            "HTTP 429 rate limit",
            "503 service unavailable",
            "budget cap reached",
            "cost circuit breaker",
            "high demand, try again",
            "econnreset during request",
            "SSL handshake failed",
            "postgrest error",
            "409: conflict",
            "http error 409",
        ]
        for note in transient_cases:
            with self.subTest(note=note):
                self.assertEqual(retry_policy.classify(note), "transient",
                                 f"'{note}' should be transient")

    def test_retry_policy_classifies_terminal_errors(self):
        """classify must return 'terminal' for genuine work failures and gated decisions."""
        terminal_cases = [
            "agent run failed: tests did not pass",
            "no committable changes",
            "changed nothing in the diff",
            "verify: output does not match spec",
            "quality gate: coverage dropped below 80%",
            "judge: introduces SQL injection",
            "legal review required: money transmission",
            "awaiting approval from two-key",
            "exhausted retries",
            "two-key authorization required",
        ]
        for note in terminal_cases:
            with self.subTest(note=note):
                self.assertEqual(retry_policy.classify(note), "terminal",
                                 f"'{note}' should be terminal")

    def test_terminal_marker_wins_over_transient_in_same_note(self):
        """When both terminal and transient signals appear, terminal must win."""
        mixed_note = "judge: timeout occurred during evaluation"
        self.assertEqual(retry_policy.classify(mixed_note), "terminal",
                         "terminal signal must take precedence over transient")

    def test_unknown_error_defaults_to_terminal(self):
        """classify must default to 'terminal' for completely novel/unrecognized errors."""
        unknown_cases = [
            "some totally novel error nobody has seen",
            "",
            "xyz",
        ]
        for note in unknown_cases:
            with self.subTest(note=note):
                self.assertEqual(retry_policy.classify(note), "terminal",
                                 "unknown errors must be terminal (fail-safe, not fail-open)")

    def test_decide_requeues_transient_errors_below_retry_cap(self):
        """decide must return action='requeue' for transient errors below MAX_TRANSIENT_RETRIES."""
        result = retry_policy.decide("Connection reset by peer", transient_retries=0)
        self.assertEqual(result["action"], "requeue")
        self.assertGreater(result["backoff_s"], 0)
        self.assertEqual(result["transient_retries"], 1)

    def test_decide_blocks_terminal_errors(self):
        """decide must return action='block' for terminal/gated errors regardless of retry count."""
        result = retry_policy.decide("judge: introduces SQL injection", transient_retries=0)
        self.assertEqual(result["action"], "block")
        self.assertEqual(result["backoff_s"], 0)

    def test_decide_still_requeues_at_retry_cap(self):
        """decide must continue requeuing (with capped backoff) even after exceeding the retry cap."""
        over_cap = retry_policy.MAX_TRANSIENT_RETRIES + 5
        result = retry_policy.decide("budget cap reached", transient_retries=over_cap)
        self.assertEqual(result["action"], "requeue",
                         "transient errors never become permanently blocked — they cooldown/failover")
        self.assertGreaterEqual(result["backoff_s"], retry_policy.BACKOFF_CAP_S * 0.5)

    def test_backoff_seconds_increases_with_retry_count(self):
        """backoff_seconds must grow with each retry (exponential backoff)."""
        b0 = retry_policy.BACKOFF_BASE_S
        b3 = retry_policy.BACKOFF_CAP_S
        # retry 0: base * 2^0 = base; retry 10: should be near cap
        s0 = retry_policy.backoff_seconds(0)
        s10 = retry_policy.backoff_seconds(10)
        self.assertGreaterEqual(s0, b0 * 0.5, "retry 0 backoff should be near base")
        self.assertLessEqual(s10, b3 * 1.5, "high-retry backoff should be near cap")
        self.assertGreater(s10, s0, "later retries must have longer backoff than early ones")

    def test_process_controls_handles_unknown_action_without_crashing(self):
        """process_controls must not crash and must record the error for an unknown action."""
        fake_db = MagicMock()
        fake_db.select.return_value = [{
            "id": "ctrl-x",
            "target": "all",
            "action": "teleport",  # unknown action
            "handled_by": [],
            "params": {"expected_hosts": []},
        }]
        with patch.object(fleet_control, "db", fake_db), \
             patch.object(fleet_control, "HOST", "test-host"), \
             patch.object(fleet_control, "_host_aliases", return_value={"test-host"}):
            try:
                result = fleet_control.process_controls()
            except Exception as e:
                self.fail(f"process_controls raised on unknown action: {e}")
        # The error was recorded via db.update with last_error set
        update_calls = fake_db.update.call_args_list
        self.assertTrue(len(update_calls) > 0, "unknown action error must be recorded")
        last_error = update_calls[0].args[2].get("last_error", "")
        self.assertIn("teleport", last_error, "error message must name the bad action")

    def test_safe_key_is_case_insensitive_for_deny_markers(self):
        """_safe_key must reject deny-marker keys regardless of letter case."""
        mixed_case_deny = [
            "orch_api_Key",
            "Orch_Secret_Value",
            "some_Token_here",
            "DB_Password",
        ]
        for k in mixed_case_deny:
            with self.subTest(key=k):
                self.assertFalse(fleet_control._safe_key(k),
                                 f"mixed-case deny key '{k}' must be rejected")


if __name__ == "__main__":
    unittest.main(verbosity=2)
