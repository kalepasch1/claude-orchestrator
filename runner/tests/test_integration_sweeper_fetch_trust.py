#!/usr/bin/env python3
"""A failed agent-ref fetch must never be read as "the branch is gone".

THE BURST THIS PREVENTS. 226 tasks were quarantined with
"integration_sweeper: branch lost and recovery exhausted" between 2026-08-23 20:00 and
2026-08-24 05:00 UTC, across nine unrelated projects at once (beethoven 37, smarter 34,
pareto-2080 30, darwn 28, racefeed 24, prediction-markets-institute 19, kalepasch-com 19,
santas-secret-workshop 17, sustainable-barks 17). Total rows carrying that note across all
history: 236 — 96% of it in one four-hour window. Nothing task-shaped is simultaneous
across nine repositories.

_fetch_agent_refs() swallowed every failure and returned nothing, so a network blip, an
expired credential or a timeout looked exactly like a clean fetch. With origin/agent/*
unpopulated (and `--prune` able to drop the refs that were the only local evidence), every
branch resolves as missing, and the once-per-process memo pins that verdict for the whole
run — every project in the sweep.
"""
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import integration_sweeper as isw  # noqa: E402

REPO = "/tmp/pretend-repo"


def _reset():
    isw._FETCHED_AGENT_REFS.clear()
    isw._AGENT_REFS_OK.clear()


class _Proc:
    def __init__(self, rc):
        self.returncode = rc
        self.stdout = b""
        self.stderr = b""


class FetchResultTests(unittest.TestCase):
    def setUp(self):
        _reset()
        self.addCleanup(_reset)

    def test_a_clean_fetch_is_trustworthy(self):
        with mock.patch.object(os.path, "isdir", return_value=True), \
             mock.patch.object(subprocess, "run", return_value=_Proc(0)):
            self.assertTrue(isw._fetch_agent_refs(REPO))
            self.assertTrue(isw.agent_refs_trustworthy(REPO))

    def test_a_nonzero_fetch_is_not_trustworthy(self):
        """The exact production condition: git fetch fails, everything looks missing."""
        with mock.patch.object(os.path, "isdir", return_value=True), \
             mock.patch.object(subprocess, "run", return_value=_Proc(128)):
            self.assertFalse(isw._fetch_agent_refs(REPO))
            self.assertFalse(isw.agent_refs_trustworthy(REPO))

    def test_a_raising_fetch_is_not_trustworthy(self):
        with mock.patch.object(os.path, "isdir", return_value=True), \
             mock.patch.object(subprocess, "run",
                               side_effect=subprocess.TimeoutExpired("git", 120)):
            self.assertFalse(isw._fetch_agent_refs(REPO))
            self.assertFalse(isw.agent_refs_trustworthy(REPO))

    def test_a_missing_repo_path_is_not_trustworthy(self):
        with mock.patch.object(os.path, "isdir", return_value=False):
            self.assertFalse(isw.agent_refs_trustworthy(REPO))
            self.assertFalse(isw.agent_refs_trustworthy(""))
            self.assertFalse(isw.agent_refs_trustworthy(None))

    def test_the_verdict_is_memoised_without_refetching(self):
        """One fetch per repo per process — but the RESULT must persist, not just the fact
        that a fetch was attempted. Losing the result is what made a single failure look
        like a clean run for the rest of the sweep."""
        with mock.patch.object(os.path, "isdir", return_value=True), \
             mock.patch.object(subprocess, "run", return_value=_Proc(128)) as run:
            isw._fetch_agent_refs(REPO)
            isw._fetch_agent_refs(REPO)
            self.assertFalse(isw.agent_refs_trustworthy(REPO))
            self.assertEqual(run.call_count, 1)

    def test_a_failure_is_announced_not_swallowed(self):
        with mock.patch.object(os.path, "isdir", return_value=True), \
             mock.patch.object(subprocess, "run", return_value=_Proc(128)), \
             mock.patch("builtins.print") as printed:
            isw._fetch_agent_refs(REPO)
        said = " ".join(str(c.args[0]) for c in printed.call_args_list if c.args)
        self.assertIn("FAILED", said)
        self.assertIn("not trustworthy", said)


class GuardIsWiredTests(unittest.TestCase):
    """The predicate is only worth anything if the destructive paths consult it."""

    def test_both_close_paths_are_gated(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "integration_sweeper.py")
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
        self.assertIn("elif not agent_refs_trustworthy(repo):", source,
                      "the branch-lost close path is not gated")
        self.assertIn("if _is_recovery and not agent_refs_trustworthy(repo):", source,
                      "the recovery-branch close path is not gated")
        # And the guard must sit BEFORE the quarantining write it protects.
        # rindex, not index: the phrase also appears in agent_refs_trustworthy's docstring
        # where the incident is explained. The one that matters is the WRITE.
        guard_at = source.index("elif not agent_refs_trustworthy(repo):")
        close_at = source.rindex("branch lost and recovery exhausted")
        self.assertLess(guard_at, close_at)


if __name__ == "__main__":
    unittest.main()
