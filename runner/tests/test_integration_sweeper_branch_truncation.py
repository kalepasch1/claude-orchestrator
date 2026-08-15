"""Regression tests for the >80-char slug / branch-name truncation mismatch.

branch_materializer.derive_branch_name() clamps a task slug to 80 characters before
creating `agent/<slug>`. integration_sweeper used to look the branch up under the RAW
slug from the tasks row, so any task whose slug exceeded 80 characters could never be
found: it was reported missing_branch on every sweep and filed a fresh
recover-missing-branch-* row each time -- whose own slug is 22 characters longer and so
is itself unfindable. These tests pin the resolver to the materializer's derivation.
"""
import os, sys, unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import integration_sweeper
import branch_materializer


LONG_SLUG = ("recover-missing-branch-dropbox-wave-c-compounding-codegen-platform-spine-"
             "pipeline-structure-part-7-pipeline-structure-beyond-the-queued-rele")
SHORT_SLUG = "feat-x"


class TestBranchSlugDerivation(unittest.TestCase):

    def test_long_slug_is_actually_longer_than_the_clamp(self):
        """Guard the fixture itself: without this the other tests would pass vacuously."""
        self.assertGreater(len(LONG_SLUG), integration_sweeper._BRANCH_SLUG_MAX)

    def test_derivation_matches_branch_materializer(self):
        """The sweeper's local copy must not drift from the module that creates branches."""
        for slug in (LONG_SLUG, SHORT_SLUG, "Weird__Slug!!With@@Chars", "a" * 200, ""):
            self.assertEqual(
                branch_materializer.derive_branch_name(slug),
                f"agent/{integration_sweeper._derive_branch_slug(slug)}",
                f"derivation drifted for {slug!r}",
            )

    def test_clamped_name_is_a_candidate_for_a_long_slug(self):
        candidates = integration_sweeper._candidate_branches(LONG_SLUG)
        self.assertEqual(branch_materializer.derive_branch_name(LONG_SLUG), candidates[0])
        self.assertIn(f"agent/{LONG_SLUG}", candidates, "raw name must remain a fallback")

    def test_short_slug_yields_exactly_one_candidate(self):
        """No redundant duplicate probe (and therefore no extra git call) in the common case."""
        self.assertEqual([f"agent/{SHORT_SLUG}"], integration_sweeper._candidate_branches(SHORT_SLUG))


class TestBranchResolution(unittest.TestCase):

    def _resolver(self, existing):
        return lambda repo, branch: branch in existing

    def test_long_slug_resolves_to_the_materialized_branch(self):
        materialized = branch_materializer.derive_branch_name(LONG_SLUG)
        with patch.object(integration_sweeper, "_branch_exists_anywhere",
                          side_effect=self._resolver({materialized})):
            self.assertEqual(materialized,
                             integration_sweeper._resolve_agent_branch("/repo", LONG_SLUG))
            self.assertTrue(integration_sweeper._agent_branch_exists("/repo", LONG_SLUG))

    def test_legacy_untruncated_branch_still_resolves(self):
        """Branches pushed before the clamp existed must not become phantom-missing."""
        raw = f"agent/{LONG_SLUG}"
        with patch.object(integration_sweeper, "_branch_exists_anywhere",
                          side_effect=self._resolver({raw})):
            self.assertEqual(raw, integration_sweeper._resolve_agent_branch("/repo", LONG_SLUG))

    def test_genuinely_missing_branch_is_still_reported_missing(self):
        """The fix must not paper over real branch loss."""
        with patch.object(integration_sweeper, "_branch_exists_anywhere", return_value=False):
            self.assertIsNone(integration_sweeper._resolve_agent_branch("/repo", LONG_SLUG))
            self.assertFalse(integration_sweeper._agent_branch_exists("/repo", LONG_SLUG))


class TestQueueRecovery(unittest.TestCase):

    def test_no_recovery_queued_when_materialized_branch_exists(self):
        """The regression itself: a long-slug task with a live branch filed recovery churn."""
        materialized = branch_materializer.derive_branch_name(LONG_SLUG)
        task = {"id": "t1", "slug": LONG_SLUG, "state": "DONE", "kind": "build"}
        with patch.object(integration_sweeper, "_branch_exists_anywhere",
                          side_effect=self._exists({materialized})), \
             patch.object(integration_sweeper, "_handle_missing_branch") as handler:
            self.assertFalse(integration_sweeper._queue_recovery(task, {"repo_path": "/repo"}))
        handler.assert_not_called()

    def test_recovery_still_queued_when_no_candidate_exists(self):
        task = {"id": "t1", "slug": LONG_SLUG, "state": "DONE", "kind": "build"}
        with patch.object(integration_sweeper, "_branch_exists_anywhere", return_value=False), \
             patch.object(integration_sweeper, "_handle_missing_branch",
                          return_value=True) as handler:
            self.assertTrue(integration_sweeper._queue_recovery(task, {"repo_path": "/repo"}))
        handler.assert_called_once()

    @staticmethod
    def _exists(existing):
        return lambda repo, branch: branch in existing


if __name__ == "__main__":
    unittest.main()
