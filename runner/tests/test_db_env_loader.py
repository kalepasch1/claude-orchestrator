"""db.py's .env loader must defer to subscription_guard, not re-derive the billing rule.

test_db_env_interlock.py covers the 2026-07-08 outage itself (a stray ANTHROPIC_API_KEY being
setdefault()'d back into every subprocess). This file covers the follow-on hazard: the loader
carried its own copy of the policy — `subscription off AND billing opted in` — which is strictly
looser than subscription_guard.is_api_allowed(), the module that actually owns the decision.
is_api_allowed() additionally requires purchased-credit intent and can be revoked live through
control_flags. The looser copy is the one that spends money, so the loader now asks the
authority and fails closed when it cannot.

Deliberately dependency-free: a throwaway copy of db.py is imported against a temp .env, exactly
as the interlock test does, so nothing here mocks db's internals.
"""
import os
import shutil
import sys
import tempfile
import unittest

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_MANAGED_ENV = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY_2",
    "ORCH_USE_SUBSCRIPTION", "ORCH_ALLOW_API_BILLING",
    "ORCH_USE_PURCHASED_CREDITS", "ORCH_USE_PAID_AGENTIC_CREDITS",
    "ORCH_STARTUP_DB_CONTROL_FLAGS",
)


def _load_env_into(env_lines, extra_environ=None, copy_guard=True):
    """Import a throwaway db.py against a temp .env; return the resulting os.environ subset.

    When ``copy_guard`` is False the throwaway directory has no subscription_guard.py, which is
    how the fail-soft path is exercised: the authority cannot be imported at all.
    """
    d = tempfile.mkdtemp()
    try:
        with open(os.path.join(d, ".env"), "w") as f:
            f.write("\n".join(env_lines))
        shutil.copy(os.path.join(RUNNER_DIR, "db.py"), os.path.join(d, "db.py"))
        if copy_guard:
            shutil.copy(os.path.join(RUNNER_DIR, "subscription_guard.py"),
                        os.path.join(d, "subscription_guard.py"))

        saved = {k: os.environ.pop(k, None) for k in _MANAGED_ENV}
        if extra_environ:
            os.environ.update(extra_environ)
        saved_path = list(sys.path)
        saved_modules = {m: sys.modules.pop(m, None) for m in ("db", "subscription_guard")}
        # Isolate from the real runner/ package so `copy_guard=False` genuinely has no guard.
        sys.path = [d] + [p for p in sys.path if os.path.abspath(p) != RUNNER_DIR]
        try:
            import db  # noqa: F401  (the throwaway copy in `d`, not runner/db.py)
            return {k: os.environ.get(k) for k in _MANAGED_ENV}
        finally:
            sys.path = saved_path
            for m, mod in saved_modules.items():
                sys.modules.pop(m, None)
                if mod is not None:
                    sys.modules[m] = mod
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    finally:
        shutil.rmtree(d, ignore_errors=True)


_BASE_ENV = [
    "SUPABASE_URL=https://x.supabase.co",
    "SUPABASE_SERVICE_KEY=abc",
]

_FULLY_OPTED_IN = [
    "ORCH_USE_SUBSCRIPTION=false",
    "ORCH_ALLOW_API_BILLING=true",
    "ORCH_USE_PURCHASED_CREDITS=true",
]


class BlockedKeyNeverInjectedTest(unittest.TestCase):
    def test_default_subscription_mode_blocks_the_key(self):
        loaded = _load_env_into(_BASE_ENV + ["ANTHROPIC_API_KEY=should-not-load"])
        self.assertIsNone(loaded["ANTHROPIC_API_KEY"])

    def test_suffixed_variants_are_blocked_too(self):
        """ANTHROPIC_API_KEY_2 is the same hazard wearing a different name."""
        loaded = _load_env_into(_BASE_ENV + [
            "ANTHROPIC_API_KEY=should-not-load",
            "ANTHROPIC_API_KEY_2=should-not-load-either",
        ])
        self.assertIsNone(loaded["ANTHROPIC_API_KEY"])
        self.assertIsNone(loaded["ANTHROPIC_API_KEY_2"])

    def test_opt_in_without_purchased_credits_is_not_enough(self):
        """The old inline rule would have injected here; is_api_allowed() says no."""
        loaded = _load_env_into(_BASE_ENV + [
            "ORCH_USE_SUBSCRIPTION=false",
            "ORCH_ALLOW_API_BILLING=true",
            "ANTHROPIC_API_KEY=should-not-load",
        ])
        self.assertIsNone(
            loaded["ANTHROPIC_API_KEY"],
            "db.py must defer to subscription_guard.is_api_allowed(), not its own looser copy",
        )

    def test_missing_subscription_guard_fails_closed(self):
        """If the authority cannot be imported, the answer is no — never 'assume allowed'."""
        loaded = _load_env_into(
            _BASE_ENV + _FULLY_OPTED_IN + ["ANTHROPIC_API_KEY=should-not-load"],
            copy_guard=False,
        )
        self.assertIsNone(loaded["ANTHROPIC_API_KEY"])

    def test_subscription_on_beats_every_other_opt_in(self):
        loaded = _load_env_into(_BASE_ENV + [
            "ORCH_USE_SUBSCRIPTION=true",
            "ORCH_ALLOW_API_BILLING=true",
            "ORCH_USE_PURCHASED_CREDITS=true",
            "ANTHROPIC_API_KEY=should-not-load",
        ])
        self.assertIsNone(loaded["ANTHROPIC_API_KEY"])


class NonBlockedKeysStillLoadTest(unittest.TestCase):
    """The firewall is narrow on purpose: it must not turn into a general .env outage."""

    def test_ordinary_keys_load_while_billing_is_blocked(self):
        loaded = _load_env_into(_BASE_ENV + [
            "ORCH_USE_PURCHASED_CREDITS=false",
            "ANTHROPIC_API_KEY=should-not-load",
        ])
        self.assertIsNone(loaded["ANTHROPIC_API_KEY"])
        self.assertEqual(loaded["ORCH_USE_PURCHASED_CREDITS"], "false")

    def test_absent_key_stays_absent(self):
        loaded = _load_env_into(_BASE_ENV)
        self.assertIsNone(loaded["ANTHROPIC_API_KEY"])


class FullyOptedInStillWorksTest(unittest.TestCase):
    """A deliberate, fully-consented fallback must still be possible — this is a guard, not a wall."""

    def test_full_opt_in_injects_the_key(self):
        loaded = _load_env_into(
            _BASE_ENV + _FULLY_OPTED_IN + ["ANTHROPIC_API_KEY=should-load"])
        self.assertEqual(loaded["ANTHROPIC_API_KEY"], "should-load")


class ContractSurfaceTest(unittest.TestCase):
    """The blocked-prefix list is sourced from fleet_contracts when present, with a safe fallback."""

    def setUp(self):
        sys.path.insert(0, RUNNER_DIR)
        import db
        self.db = db

    def tearDown(self):
        if sys.path and sys.path[0] == RUNNER_DIR:
            sys.path.pop(0)

    def test_fallback_prefixes_block_the_outage_key(self):
        prefixes = self.db._blocked_api_env_prefixes()
        self.assertTrue(self.db._is_blocked_api_key("ANTHROPIC_API_KEY", prefixes))
        self.assertTrue(self.db._is_blocked_api_key("ANTHROPIC_API_KEY_2", prefixes))

    def test_unrelated_keys_are_not_blocked(self):
        prefixes = self.db._blocked_api_env_prefixes()
        for name in ("SUPABASE_URL", "OPENAI_API_KEY", "ANTHROPIC_MODEL",
                     "ANTHROPIC_API_KEYRING"):
            self.assertFalse(self.db._is_blocked_api_key(name, prefixes), name)


if __name__ == "__main__":
    unittest.main()
