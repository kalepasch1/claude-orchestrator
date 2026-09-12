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
        # db.py now asks subscription_guard whether API billing is allowed instead of
        # re-deriving the rule, so the authority has to be importable for the opt-in case.
        shutil.copy(os.path.join(RUNNER_DIR, "subscription_guard.py"),
                    os.path.join(d, "subscription_guard.py"))
        sys.path.insert(0, d)
        # KEEP THE REAL MODULES AND PUT THEM BACK (fixed 2026-08-25).
        #
        # This used to `sys.modules.pop("db", None)` without keeping the object,
        # and the finally block popped the throwaway without restoring anything.
        # So every test that ran after this file found NO "db" in sys.modules,
        # and the next runtime `import db` built a SECOND db module object.
        #
        # From then on the suite had two live copies of the control-plane client.
        # Any module that had already done `import db` — every test file, and
        # conftest's own _REAL_MODULES registry — kept copy A; anything doing a
        # runtime `import db` inside a function got copy B. A test patching
        # db.select on the object it holds therefore patched A while the code
        # under test read B, and the patch silently did nothing.
        #
        # That is the whole of the 20-failure cluster in
        # test_done_to_merged_conversion.py and test_eval_harness_causal.py:
        # both patch their own module-level `db`, both exercise product code that
        # does `import db` inside a function, and both pass alone and fail in
        # suite. conftest cannot cover it — _restore_real_modules() runs at
        # collectstart, and this leak happens during the RUN phase.
        #
        # test_db_env_loader.py's _load_env_into already had the correct shape;
        # this is the same save/restore.
        saved_modules = {m: sys.modules.pop(m, None)
                         for m in ("db", "subscription_guard")}
        saved = {k: os.environ.pop(k, None) for k in
                 ("ANTHROPIC_API_KEY", "ORCH_USE_SUBSCRIPTION", "ORCH_ALLOW_API_BILLING",
                  "ORCH_USE_PURCHASED_CREDITS", "ORCH_USE_PAID_AGENTIC_CREDITS")}
        if extra_environ:
            os.environ.update(extra_environ)
        try:
            import db  # noqa: the throwaway copy in `d`, not runner/db.py
            return os.environ.get("ANTHROPIC_API_KEY")
        finally:
            sys.path.remove(d)
            for name, mod in saved_modules.items():
                sys.modules.pop(name, None)      # drop the throwaway
                if mod is not None:
                    sys.modules[name] = mod      # put the real one back
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    finally:
        shutil.rmtree(d, ignore_errors=True)


class ThrowawayImportLeavesNoHoleTest(unittest.TestCase):
    """The helper above must not leave sys.modules without a control-plane client.

    Not a style point. A MISSING name is worse than a replaced one: the next
    `import db` builds a second module object from the same source, and the
    session then has two live copies. Every module that imported db earlier keeps
    the first; anything doing `import db` inside a function gets the second. A
    test patching db.select on the object it holds patches one copy while the
    code under test reads the other, so the patch does nothing and the product
    talks to the real database. That is what these assertions exist to prevent.
    """

    def check_module_identity_survives(self):
        import db
        import subscription_guard
        before = {"db": db, "subscription_guard": subscription_guard}

        _fresh_db_env(["SUPABASE_URL=https://x.supabase.co",
                       "SUPABASE_SERVICE_KEY=abc"])

        for name, module in before.items():
            self.assertIn(name, sys.modules,
                          f"{name} was removed from sys.modules and not put back")
            self.assertIs(sys.modules[name], module,
                          f"sys.modules[{name!r}] is a different object than before")

    # unittest wants the camelCase spelling; the convention lint wants snake_case.
    test_module_identity_survives_a_throwaway_import = check_module_identity_survives


class DbEnvInterlockTest(unittest.TestCase):
    def test_default_subscription_mode_never_loads_anthropic_key_from_env_file(self):
        key = _fresh_db_env([
            "SUPABASE_URL=https://x.supabase.co",
            "SUPABASE_SERVICE_KEY=abc",
            "ANTHROPIC_API_KEY=fake-anthropic-key-should-not-load",
        ])
        self.assertIsNone(key, "db.py must never re-inject ANTHROPIC_API_KEY while billing is blocked")

    def test_deliberate_fallback_set_inside_env_file_is_still_honored(self):
        # Full consent now means what subscription_guard.is_api_allowed() means, which also
        # requires purchased-credit intent — db.py no longer keeps its own looser copy of the
        # rule. See runner/tests/test_db_env_loader.py.
        key = _fresh_db_env([
            "SUPABASE_URL=https://x.supabase.co",
            "SUPABASE_SERVICE_KEY=abc",
            "ORCH_USE_SUBSCRIPTION=false",
            "ORCH_ALLOW_API_BILLING=true",
            "ORCH_USE_PURCHASED_CREDITS=true",
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
