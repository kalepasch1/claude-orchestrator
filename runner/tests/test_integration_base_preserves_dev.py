"""_integration_base must never discard unpromoted merges on the integration branch.

Regression test for the 2026-09-01 finding: `_integration_base` used to run
`git branch -f <dev> <prod>` whenever dev was not strictly ahead of prod. Any merge
that had landed on dev but had not yet been promoted was silently destroyed, while the
task row stayed MERGED. That is the mechanism behind phantom_merge_audit's 10,598 rows
and the 22 / 9 forced resets visible in the `tomorrow` / `apparently-law` reflogs.

These tests drive real git repositories, because the bug lived entirely in which git
command was chosen.
"""
import os
import subprocess
import sys
import tempfile
import unittest

# `import runner` resolves to the PACKAGE under pytest, not runner/runner.py. Load the
# module by path so this test works both under pytest and when run directly.
import importlib.util
_RUNNER_PY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner.py")
sys.path.insert(0, os.path.dirname(_RUNNER_PY))
_spec = importlib.util.spec_from_file_location("_runner_under_test", _RUNNER_PY)
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)  # noqa: E402


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def _sha(repo, ref):
    return _git(repo, "rev-parse", ref).stdout.strip()


def _commit(repo, name):
    with open(os.path.join(repo, name), "w") as fh:
        fh.write(name)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", name, "--no-gpg-sign")


def _make_repo(prod="main", dev="orchestrator/dev"):
    """A repo on <prod> with one commit, plus a <dev> branch pointing at it."""
    d = tempfile.mkdtemp(prefix="intbase-")
    _git(d, "init", "-q", "-b", prod)
    _git(d, "config", "user.email", "t@t.t")
    _git(d, "config", "user.name", "t")
    _git(d, "config", "commit.gpgsign", "false")
    _commit(d, "base.txt")
    _git(d, "branch", dev)
    return d


class IntegrationBaseTests(unittest.TestCase):
    def setUp(self):
        self.env = {}
        for k in ("ORCH_CODE_MERGE_TARGET", "ORCH_STAGING_BRANCH", "ORCH_DEV_RESET_ON_DRIFT"):
            self.env[k] = os.environ.pop(k, None)
        os.environ["ORCH_CODE_MERGE_TARGET"] = "dev"
        os.environ["ORCH_STAGING_BRANCH"] = "orchestrator/dev"

    def tearDown(self):
        for k, v in self.env.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    # ── the actual regression ────────────────────────────────────────────────
    def test_diverged_dev_is_not_reset(self):
        """dev has an unpromoted merge, prod moved on: dev must keep its commit."""
        repo = _make_repo()
        proj = {"prod_branch": "main", "default_base": "main"}

        _git(repo, "checkout", "-q", "orchestrator/dev")
        _commit(repo, "unpromoted-improvement.txt")
        dev_before = _sha(repo, "orchestrator/dev")

        _git(repo, "checkout", "-q", "main")
        _commit(repo, "prod-hotfix.txt")

        out = runner._integration_base(repo, proj, "main")

        self.assertEqual(out, "orchestrator/dev")
        self.assertEqual(
            _sha(repo, "orchestrator/dev"), dev_before,
            "dev was rewritten; the unpromoted merge on it has been destroyed")
        self.assertTrue(
            os.path.exists(os.path.join(repo, "unpromoted-improvement.txt"))
            or _git(repo, "cat-file", "-e",
                    f"{dev_before}:unpromoted-improvement.txt").returncode == 0,
            "the unpromoted commit is no longer reachable from dev")

    def test_dev_behind_prod_fast_forwards(self):
        """The legitimate case still works: a stale dev catches up to prod."""
        repo = _make_repo()
        proj = {"prod_branch": "main", "default_base": "main"}

        _commit(repo, "prod-moved.txt")          # on main; dev untouched
        prod_sha = _sha(repo, "main")

        out = runner._integration_base(repo, proj, "main")

        self.assertEqual(out, "orchestrator/dev")
        self.assertEqual(_sha(repo, "orchestrator/dev"), prod_sha,
                         "a strictly-behind dev should fast-forward onto prod")

    def test_missing_dev_is_created_from_prod(self):
        repo = _make_repo()
        _git(repo, "branch", "-D", "orchestrator/dev")
        proj = {"prod_branch": "main", "default_base": "main"}

        out = runner._integration_base(repo, proj, "main")

        self.assertEqual(out, "orchestrator/dev")
        self.assertEqual(_sha(repo, "orchestrator/dev"), _sha(repo, "main"))

    def test_dev_ahead_of_prod_is_untouched(self):
        repo = _make_repo()
        proj = {"prod_branch": "main", "default_base": "main"}
        _git(repo, "checkout", "-q", "orchestrator/dev")
        _commit(repo, "ahead.txt")
        dev_before = _sha(repo, "orchestrator/dev")

        runner._integration_base(repo, proj, "main")

        self.assertEqual(_sha(repo, "orchestrator/dev"), dev_before)

    # ── the escape hatch still works ─────────────────────────────────────────
    def test_opt_in_flag_restores_destructive_reset(self):
        repo = _make_repo()
        proj = {"prod_branch": "main", "default_base": "main"}
        _git(repo, "checkout", "-q", "orchestrator/dev")
        _commit(repo, "unpromoted.txt")
        _git(repo, "checkout", "-q", "main")
        _commit(repo, "hotfix.txt")

        os.environ["ORCH_DEV_RESET_ON_DRIFT"] = "true"
        runner._integration_base(repo, proj, "main")

        self.assertEqual(_sha(repo, "orchestrator/dev"), _sha(repo, "main"),
                         "opt-in flag should reproduce the old force-reset")

    def test_flag_defaults_to_safe(self):
        self.assertFalse(runner._dev_reset_on_drift())


if __name__ == "__main__":
    unittest.main()
