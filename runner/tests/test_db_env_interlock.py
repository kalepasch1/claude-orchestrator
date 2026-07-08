"""Interlock test for the 2026-07-08 outage: db.py's .env loader used to setdefault() a stray
ANTHROPIC_API_KEY back into the environment of every subprocess (every periodic job is one),
undoing subscription_guard.enforce() from the parent runner process. That silently re-armed
billing_guard's key-presence check every 5 minutes and paused the fleet for ~10 hours.

This is the "catchable by a 5-line test" the postmortem called for: import db fresh against a
.env containing a live key, in default (subscription-on, no opt-in) mode, and assert the key
never reaches os.environ. Keep this test cheap and dependency-free — no network, no mocks of
db's internals — so it can run on every commit.
"""
import os
import shutil
import sys
import tempfile
import unittest

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fresh_db_env(env_lines, extra_environ=None):
    """Import a throwaway copy of db.py against a temp .env, return os.environ['ANTHROPIC_API_KEY']."""
    d = tempfile.mkdtemp()
    try:
        with open(os.path.join(d, ".env"), "w") as f:
            f.write("\n".join(env_lines))
        shutil.copy(os.path.join(RUNNER_DIR, "db.py"), os.path.join(d, "db.py"))
        sys.path.insert(0, d)
        sys.modules.pop("db", None)
        saved = {k: os.environ.pop(k, None) for k in
                 ("ANTHROPIC_API_KEY", "ORCH_USE_SUBSCRIPTION", "ORCH_ALLOW_API_BILLING")}
        if extra_environ:
            os.environ.update(extra_environ)
        try:
            import db  # noqa: the throwaway copy in `d`, not runner/db.py
            return os.environ.get("ANTHROPIC_API_KEY")
        finally:
            sys.path.remove(d)
            sys.modules.pop("db", None)
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    finally:
        shutil.rmtree(d, ignore_errors=True)


class DbEnvInterlockTest(unittest.TestCase):
    def test_default_subscription_mode_never_loads_anthropic_key_from_env_file(self):
        key = _fresh_db_env([
            "SUPABASE_URL=https://x.supabase.co",
            "SUPABASE_SERVICE_KEY=abc",
            "ANTHROPIC_API_KEY=fake-anthropic-key-should-not-load",
        ])
        self.assertIsNone(key, "db.py must never re-inject ANTHROPIC_API_KEY while billing is blocked")

    def test_deliberate_fallback_set_inside_env_file_is_still_honored(self):
        key = _fresh_db_env([
            "SUPABASE_URL=https://x.supabase.co",
            "SUPABASE_SERVICE_KEY=abc",
            "ORCH_USE_SUBSCRIPTION=false",
            "ORCH_ALLOW_API_BILLING=true",
            "ANTHROPIC_API_KEY=fake-anthropic-key-should-load",
        ])
        self.assertEqual(key, "fake-anthropic-key-should-load")

    def test_no_key_in_env_file_stays_absent(self):
        key = _fresh_db_env([
            "SUPABASE_URL=https://x.supabase.co",
            "SUPABASE_SERVICE_KEY=abc",
        ])
        self.assertIsNone(key)


if __name__ == "__main__":
    unittest.main()
