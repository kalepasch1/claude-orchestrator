"""Reproduce the repeated-remediation loop in fleet missing-branch recovery.

Slice 3 asked why the same file (packages/darwin-kernel/src/passport/passport.ts)
kept coming back with an identical conflict across remediations. The answer is in
`branch_fleet_recovery.recover_branch`: a lost branch is requeued as
`recover-<slug>`. Nothing excluded that *recovery* task from the next sweep, so
once it reached DONE with its own branch missing it was requeued in turn as
`recover-recover-<slug>`, and so on without bound. Each generation is a fresh
task re-applying the same patch to the same paths, so the conflict was not being
retried — it was being recreated.

`test_unbounded_recovery_chain_is_refused` is the deterministic reproduction: it
drives recover_branch over successive generations and asserts the chain stops.
Before the generation cap it grew forever.

Pure: no git, no network, no real DB — every boundary is stubbed.
"""
import logging
import os
import sys
import unittest
from unittest.mock import patch

_RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RUNNER not in sys.path:
    sys.path.insert(0, _RUNNER)

import branch_fleet_recovery as bfr  # noqa: E402


CONFLICTED_PATH = "packages/darwin-kernel/src/passport/passport.ts"


def _task(slug):
    return {"id": f"id-{slug}", "slug": slug, "project_id": "proj",
            "kind": "build", "base_branch": "master",
            "prompt": f"resolve the conflict in {CONFLICTED_PATH}"}


class RecoveryGenerationTest(unittest.TestCase):
    """Counting the prefixes is what makes the loop observable."""

    def test_original_slug_is_generation_zero(self):
        self.assertEqual(bfr.recovery_generation("fix-passport"), 0)

    def test_each_wrapper_increments(self):
        self.assertEqual(bfr.recovery_generation("recover-fix-passport"), 1)
        self.assertEqual(bfr.recovery_generation("recover-recover-fix-passport"), 2)
        self.assertEqual(bfr.recovery_generation("recover-recover-recover-x"), 3)

    def test_recover_inside_the_slug_does_not_count(self):
        """Only leading wrappers count — a task about recovery is not a retry."""
        self.assertEqual(bfr.recovery_generation("improve-recover-branch-logic"), 0)

    def test_fail_soft_on_bad_input(self):
        for bad in (None, 123, [], {}):
            self.assertEqual(bfr.recovery_generation(bad), 0)


class RecoveryLoopTest(unittest.TestCase):
    """recover_branch must not deepen the recover- chain without bound."""

    def setUp(self):
        # Every branch is missing locally and remotely, and a PAT is present:
        # this is exactly the state that reaches the requeue path.
        self._patches = [
            patch.object(bfr, "_branch_exists_local", return_value=False),
            patch.object(bfr, "_branch_exists_remote", return_value=False),
            patch.object(bfr.git_auth, "pat_available", return_value=True),
            patch.object(bfr, "DRY_RUN", False),
        ]
        for p in self._patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self._patches])

    def _run(self, slug, inserted):
        def fake_insert(table, row, **kwargs):
            inserted.append(row["slug"])
            return True

        with patch.object(bfr.db, "select", return_value=[]), \
             patch.object(bfr.db, "insert", side_effect=fake_insert), \
             patch.object(bfr.db, "update", return_value=True):
            return bfr.recover_branch(_task(slug), "/repo", "master")

    def test_first_loss_is_requeued_once(self):
        inserted = []
        result = self._run("fix-passport", inserted)
        self.assertEqual(result["strategy"], "requeued")
        self.assertEqual(inserted, ["recover-fix-passport"])

    def test_unbounded_recovery_chain_is_refused(self):
        """Drive the loop: each requeued slug is fed back in as the next task.

        Before the generation cap this never terminated — every pass produced a
        deeper `recover-` slug re-attempting the same patch on the same file.
        """
        slug = "fix-passport"
        chain = [slug]
        for _ in range(10):
            inserted = []
            result = self._run(slug, inserted)
            if result["strategy"] != "requeued":
                break
            slug = inserted[0]
            chain.append(slug)
        else:  # pragma: no cover - only reached if the cap is gone
            self.fail(f"recovery chain never terminated: {chain}")

        self.assertEqual(result["strategy"], "max_generation_exceeded")
        # Exactly one recovery attempt at the default cap of 1.
        self.assertEqual(chain, ["fix-passport", "recover-fix-passport"])

    def test_refusal_is_logged_with_the_generation(self):
        """The loop must be legible in the sweep output, not silent."""
        with self.assertLogs(bfr._log, level=logging.WARNING) as caught:
            result = self._run("recover-fix-passport", [])
        self.assertEqual(result["strategy"], "max_generation_exceeded")
        joined = "\n".join(caught.output)
        self.assertIn("recovery generation", joined)
        self.assertIn("recover-fix-passport", joined)

    def test_cap_is_configurable(self):
        with patch.object(bfr, "MAX_GENERATION", 2):
            inserted = []
            result = self._run("recover-fix-passport", inserted)
        self.assertEqual(result["strategy"], "requeued")
        self.assertEqual(inserted, ["recover-recover-fix-passport"])

    def test_generation_check_runs_before_any_db_write(self):
        """A refused generation must not touch the tasks table at all."""
        with patch.object(bfr.db, "select", side_effect=AssertionError("no db read")), \
             patch.object(bfr.db, "insert", side_effect=AssertionError("no db write")), \
             patch.object(bfr.db, "update", side_effect=AssertionError("no db write")):
            result = bfr.recover_branch(_task("recover-fix-passport"), "/repo", "master")
        self.assertEqual(result["strategy"], "max_generation_exceeded")


if __name__ == "__main__":
    unittest.main(verbosity=2)
