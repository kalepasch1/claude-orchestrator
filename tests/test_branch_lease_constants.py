#!/usr/bin/env python3
"""Narrow regression tests for branch_lease's named bounds and logged fail-soft paths.

CLAUDE.md's lease-RPC postmortem states two rules this module used to break:

  * "DO name magic numbers ... lift these to module constants or ORCH_-prefixed env
    vars so they are fleet-pushable via fleet_control.py" — the TTL floor and the
    git-probe timeout were bare literals.
  * "AVOID *unlogged* broad excepts ... a silent `except Exception: pass` is the
    defect; a logged one is the convention" — ``_sha`` and ``release`` swallowed
    silently, so a lease taken with an empty base SHA was indistinguishable from a
    correct one.

These tests assert exactly those two properties and nothing else, so they stay true
if the surrounding lease protocol changes.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))


def _load():
    import importlib
    import branch_lease
    return importlib.reload(branch_lease)


class TestNamedBounds(unittest.TestCase):
    def test_min_ttl_is_a_named_module_constant(self):
        bl = _load()
        self.assertTrue(hasattr(bl, "MIN_TTL"))
        self.assertGreater(bl.MIN_TTL, 0)

    def test_git_probe_timeout_is_a_named_module_constant(self):
        bl = _load()
        self.assertTrue(hasattr(bl, "GIT_PROBE_TIMEOUT"))
        self.assertGreater(bl.GIT_PROBE_TIMEOUT, 0)

    def test_bounds_are_orch_prefixed_env_vars(self):
        """Fleet-pushable: fleet_control.py only propagates ORCH_-prefixed keys."""
        prev = dict(os.environ)
        try:
            os.environ["ORCH_BRANCH_LEASE_MIN_TTL_SECONDS"] = "45"
            os.environ["ORCH_BRANCH_LEASE_GIT_TIMEOUT_SECONDS"] = "7"
            bl = _load()
            self.assertEqual(bl.MIN_TTL, 45)
            self.assertEqual(bl.GIT_PROBE_TIMEOUT, 7)
        finally:
            os.environ.clear()
            os.environ.update(prev)
            _load()

    def test_no_bare_ttl_or_timeout_literals_remain(self):
        bl = _load()
        with open(bl.__file__, "r", encoding="utf-8") as fh:
            body = [line for line in fh if not line.lstrip().startswith(("#", '"', "'"))]
        source = "".join(body)
        self.assertNotIn("max(60,", source)
        self.assertNotIn("timeout=15", source)


class TestBroadCatchesAreLogged(unittest.TestCase):
    def test_sha_failure_writes_a_diagnostic_and_returns_none(self):
        import io
        import contextlib
        bl = _load()
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            # A repo path that cannot exist makes subprocess.run raise, exercising the
            # broad catch rather than the returncode branch.
            result = bl._sha("/nonexistent/repo/\0bad", "HEAD")
        self.assertIsNone(result)
        self.assertIn("branch_lease", buf.getvalue())

    def test_sha_never_raises_on_bad_input(self):
        bl = _load()
        for repo, ref in ((None, None), ("", ""), ("/nope", "HEAD")):
            self.assertIsNone(bl._sha(repo, ref) or None)


if __name__ == "__main__":
    unittest.main()
