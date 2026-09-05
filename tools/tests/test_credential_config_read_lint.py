#!/usr/bin/env python3
"""The CREDENTIAL_CONFIG_READ rule in tools/lint_conventions.py.

The runtime guard (runner/fleet_config_guard.assert_readable) catches this when
the line executes. This rule catches it at review time, which matters because
the executing form of the bug ran once per host per run: sixteen executors each
burned a full session on an empty token before anyone saw a stack trace.

A lint rule that fires on innocent code gets disabled, so the negative cases
below are as load-bearing as the positive ones -- in particular `d.get("key")`
on an ordinary dict, which is everywhere in this tree.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lint_conventions as lc  # noqa: E402


def _rules_for(source: str, filename: str = "sample.py"):
    """Run the linter over `source` and return the rule names it reported."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, filename)
        with open(path, "w") as fh:
            fh.write(source)
        return [v.rule for v in lc.check_file(path)]


class TestCredentialConfigReadIsFlagged(unittest.TestCase):
    def test_get_config_with_a_credential_key(self):
        src = 'def f(store):\n    return store.get_config("GITHUB_PAT")\n'
        self.assertIn("CREDENTIAL_CONFIG_READ", _rules_for(src))

    def test_bare_get_config_function_call(self):
        src = 'from x import get_config\n\n\ndef f():\n    return get_config("VERCEL_TOKEN")\n'
        self.assertIn("CREDENTIAL_CONFIG_READ", _rules_for(src))

    def test_fleet_config_dao_dot_get(self):
        src = 'import fleet_config_dao\n\n\ndef f():\n    return fleet_config_dao.get("OPENAI_API_KEY")\n'
        self.assertIn("CREDENTIAL_CONFIG_READ", _rules_for(src))

    def test_a_credential_hidden_in_a_get_many_batch(self):
        src = (
            'def f(dao):\n'
            '    return dao.get_many(["ORCH_MAX_WORKERS", "GEMINI_API_KEY"])\n'
        )
        self.assertIn("CREDENTIAL_CONFIG_READ", _rules_for(src))

    def test_service_key_shape_is_caught(self):
        # SUPABASE_SERVICE_KEY slipped past an earlier API_?KEY-only pattern.
        src = 'def f(store):\n    return store.get_config("SUPABASE_SERVICE_KEY")\n'
        self.assertIn("CREDENTIAL_CONFIG_READ", _rules_for(src))

    def test_the_message_points_at_the_environment(self):
        src = 'def f(store):\n    return store.get_config("GITHUB_PAT")\n'
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sample.py")
            with open(path, "w") as fh:
                fh.write(src)
            hits = [v for v in lc.check_file(path)
                    if v.rule == "CREDENTIAL_CONFIG_READ"]
        self.assertEqual(len(hits), 1)
        self.assertIn('os.environ.get("GITHUB_PAT")', hits[0].message)


class TestInnocentCodeIsNotFlagged(unittest.TestCase):
    def test_ordinary_config_keys_pass(self):
        src = 'def f(store):\n    return store.get_config("ORCH_MAX_WORKERS")\n'
        self.assertNotIn("CREDENTIAL_CONFIG_READ", _rules_for(src))

    def test_a_plain_dict_get_is_not_a_config_read(self):
        src = 'def f(d):\n    return d.get("api_key")\n'
        self.assertNotIn("CREDENTIAL_CONFIG_READ", _rules_for(src))

    def test_reading_the_credential_from_the_environment_is_the_fix_not_the_bug(self):
        src = 'import os\n\n\ndef f():\n    return os.environ.get("GITHUB_PAT")\n'
        self.assertNotIn("CREDENTIAL_CONFIG_READ", _rules_for(src))

    def test_a_non_literal_key_is_not_guessed_at(self):
        src = 'def f(store, name):\n    return store.get_config(name)\n'
        self.assertNotIn("CREDENTIAL_CONFIG_READ", _rules_for(src))

    def test_the_guard_module_may_name_the_keys_it_forbids(self):
        src = 'def f(store):\n    return store.get_config("GITHUB_PAT")\n'
        self.assertNotIn(
            "CREDENTIAL_CONFIG_READ",
            _rules_for(src, filename="fleet_config_guard.py"),
        )

    def test_tests_may_construct_the_violation_they_assert_on(self):
        src = 'def f(store):\n    return store.get_config("GITHUB_PAT")\n'
        self.assertNotIn(
            "CREDENTIAL_CONFIG_READ",
            _rules_for(src, filename="test_something.py"),
        )


class TestRuleAgreesWithTheRuntimeGuard(unittest.TestCase):
    """Two detectors that disagree are worse than one."""

    def test_same_verdict_on_every_key(self):
        sys.path.insert(
            0,
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "runner",
            ),
        )
        import fleet_config_guard as g

        keys = [
            "GITHUB_PAT", "VERCEL_TOKEN", "OPENAI_API_KEY", "SUPABASE_SERVICE_KEY",
            "DATABASE_URL", "SENTRY_DSN", "SESSION_COOKIE",
            "ORCH_MAX_WORKERS", "LOG_LEVEL", "MAX_PARALLEL",
        ]
        for key in keys:
            lint_says_credential = bool(lc._CREDENTIAL_KEY_RE.search(key))
            guard_says_credential = not g.is_readable(key)
            self.assertEqual(lint_says_credential, guard_says_credential, msg=key)


if __name__ == "__main__":
    unittest.main(verbosity=2)
