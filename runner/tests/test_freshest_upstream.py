"""The improvement lane tracks whichever of dev/prod is newer — by date, not by name.

Operator directive 2026-09-01: the lane must "autonomously replicate /dev and /prod,
whichever is more recent". Choosing by commit date rather than by branch name is what
makes that safe here: tomorrow's origin/dev is 4,336 commits behind origin/main and was
last touched on 6 February, so a name-based preference would drag the whole fleet onto
seven-month-old code. The freshness rule leaves it on main until someone commits to dev
again, then follows automatically.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import time
import unittest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)
_spec = importlib.util.spec_from_file_location("_runner_fresh", os.path.join(RUNNER, "runner.py"))
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


def _git(repo, *a, env=None):
    e = dict(os.environ, **(env or {}))
    return subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True, timeout=30, env=e)


def _commit(repo, name, when):
    with open(os.path.join(repo, name), "w") as fh:
        fh.write(name)
    _git(repo, "add", "-A")
    # "+0000" IS LOAD-BEARING. git reads a bare ISO string with no offset as LOCAL
    # time, so on any host that is not UTC the commit lands `when` shifted by the
    # machine's offset -- and test_ref_commit_time_reads_real_dates, which is the only
    # test here that checks an ABSOLUTE value rather than an ordering, failed by exactly
    # that offset (1700018000 != 1700000000, i.e. 18000s = UTC-5). The subject was fine
    # all along: _ref_commit_time asks git for `%ct`, which is a real epoch.
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime(when))
    _git(repo, "commit", "-m", name, "--no-gpg-sign",
         env={"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})


def _repo():
    d = tempfile.mkdtemp(prefix="fresh-")
    _git(d, "init", "-q", "-b", "main")
    _git(d, "config", "user.email", "t@t.t")
    _git(d, "config", "user.name", "t")
    _commit(d, "base.txt", 1_700_000_000)
    return d


PROJ = {"prod_branch": "main", "default_base": "orchestrator/dev"}


class FreshestUpstreamTests(unittest.TestCase):
    def tearDown(self):
        for k in ("ORCH_DEV_TRACKS_FRESHEST", "ORCH_TRACK_DEV_BRANCH"):
            os.environ.pop(k, None)

    def test_newer_dev_wins(self):
        r = _repo()
        _git(r, "branch", "dev")
        _git(r, "checkout", "-q", "dev")
        _commit(r, "dev-newer.txt", 1_800_000_000)
        _git(r, "checkout", "-q", "main")
        self.assertEqual(runner._freshest_upstream(r, PROJ), "dev")

    def test_newer_prod_wins(self):
        r = _repo()
        _git(r, "branch", "dev")           # dev pinned at the old base commit
        _commit(r, "prod-newer.txt", 1_800_000_000)
        self.assertEqual(runner._freshest_upstream(r, PROJ), "main")

    def test_the_tomorrow_shape_stays_on_main(self):
        """A dev branch seven months stale must never be tracked."""
        r = _repo()
        _git(r, "checkout", "-q", "-b", "dev")
        _commit(r, "ancient.txt", 1_770_000_000)      # Feb-ish
        _git(r, "checkout", "-q", "main")
        _commit(r, "recent.txt", 1_820_000_000)       # Sep-ish
        self.assertEqual(runner._freshest_upstream(r, PROJ), "main")

    def test_no_dev_branch_falls_back_to_prod(self):
        r = _repo()
        self.assertEqual(runner._freshest_upstream(r, PROJ), "main")

    def test_empty_repo_returns_empty(self):
        d = tempfile.mkdtemp(prefix="fresh-empty-")
        _git(d, "init", "-q", "-b", "main")
        self.assertEqual(runner._freshest_upstream(d, PROJ), "")

    def test_opt_out_pins_to_prod(self):
        r = _repo()
        _git(r, "checkout", "-q", "-b", "dev")
        _commit(r, "dev-newer.txt", 1_800_000_000)
        _git(r, "checkout", "-q", "main")
        os.environ["ORCH_DEV_TRACKS_FRESHEST"] = "false"
        self.assertEqual(runner._freshest_upstream(r, PROJ), "main")

    def test_dev_branch_name_is_configurable(self):
        r = _repo()
        _git(r, "checkout", "-q", "-b", "develop")
        _commit(r, "x.txt", 1_800_000_000)
        _git(r, "checkout", "-q", "main")
        os.environ["ORCH_TRACK_DEV_BRANCH"] = "develop"
        self.assertEqual(runner._freshest_upstream(r, PROJ), "develop")

    def test_ref_commit_time_reads_real_dates(self):
        r = _repo()
        self.assertEqual(runner._ref_commit_time(r, "main"), 1_700_000_000)
        self.assertIsNone(runner._ref_commit_time(r, "no-such-branch"))

    def test_integration_base_still_preserves_diverged_dev(self):
        """Freshness picks the upstream; it must not weaken the no-reset guarantee."""
        r = _repo()
        _git(r, "branch", "orchestrator/dev")
        _git(r, "checkout", "-q", "orchestrator/dev")
        _commit(r, "unpromoted.txt", 1_810_000_000)
        before = _git(r, "rev-parse", "orchestrator/dev").stdout.strip()
        _git(r, "checkout", "-q", "main")
        _commit(r, "prod-moved.txt", 1_820_000_000)

        os.environ["ORCH_CODE_MERGE_TARGET"] = "dev"
        os.environ["ORCH_STAGING_BRANCH"] = "orchestrator/dev"
        try:
            runner._integration_base(r, PROJ, "main")
        finally:
            os.environ.pop("ORCH_CODE_MERGE_TARGET", None)
            os.environ.pop("ORCH_STAGING_BRANCH", None)
        self.assertEqual(_git(r, "rev-parse", "orchestrator/dev").stdout.strip(), before,
                         "diverged lane was rewritten")


if __name__ == "__main__":
    unittest.main()
