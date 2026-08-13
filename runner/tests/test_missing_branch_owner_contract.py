"""Contract test for the missing-branch auto-recovery owner module (slice 3).

Slice 3 of improve-missing-branch-auto-recovery-fleet-wide determined that the owner
of fleet-wide missing-branch handling is `runner/branch_fleet_recovery.py`, and that
the correct insertion point for new recovery logic is `recover_branch` — the only
function on BOTH live code paths. See docs/missing-branch-recovery-owner-module.md.

These assertions exist so a rename or signature change fails loudly here instead of
letting a later slice insert logic into a module that never executes in production.
Import-only and signature-only: nothing here touches git, the network, or the DB.
"""
import inspect
import os
import sys
import unittest

_RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RUNNER not in sys.path:
    sys.path.insert(0, _RUNNER)

_REPO = os.path.dirname(_RUNNER)


class MissingBranchOwnerContractTest(unittest.TestCase):
    def test_owner_module_is_branch_fleet_recovery(self):
        self.assertTrue(
            os.path.isfile(os.path.join(_RUNNER, "branch_fleet_recovery.py")),
            "owner module runner/branch_fleet_recovery.py is missing",
        )

    def test_recover_branch_signature_is_the_insertion_point(self):
        import branch_fleet_recovery

        self.assertTrue(callable(branch_fleet_recovery.recover_branch))
        params = list(inspect.signature(branch_fleet_recovery.recover_branch).parameters)
        self.assertEqual(params, ["task", "repo_path", "base_branch"])

    def test_fleet_sweep_signature(self):
        import branch_fleet_recovery

        params = inspect.signature(branch_fleet_recovery.sweep).parameters
        self.assertEqual(list(params), ["project_id"])
        self.assertIsNone(params["project_id"].default)

    def test_scheduled_entry_point_exists(self):
        """branch_recovery_periodic is what the fleet scheduler actually runs."""
        import branch_recovery_periodic

        self.assertTrue(callable(branch_recovery_periodic.run))
        self.assertTrue(callable(branch_recovery_periodic.sweep))
        # Distinct signature from branch_fleet_recovery.sweep — the two are easy to
        # confuse, which is the whole reason this contract is pinned.
        self.assertEqual(list(inspect.signature(branch_recovery_periodic.sweep).parameters), [])

    def test_scheduled_path_calls_recover_branch_not_fleet_sweep(self):
        """The live path bypasses branch_fleet_recovery.sweep().

        If this ever stops being true the docs and the insertion-point guidance are
        stale, and a later slice would be inserting logic in the wrong function.
        """
        with open(os.path.join(_RUNNER, "branch_recovery_periodic.py"), encoding="utf-8",
                  errors="replace") as fh:
            src = fh.read()
        self.assertIn("branch_fleet_recovery.recover_branch", src)
        self.assertNotIn("branch_fleet_recovery.sweep", src)

    def test_detection_helper_signature(self):
        import branch_detection

        self.assertEqual(
            list(inspect.signature(branch_detection.detect_missing_branches).parameters),
            ["repo_path", "tasks"],
        )

    def test_detect_missing_branches_is_fail_soft_on_bad_repo(self):
        import branch_detection

        self.assertEqual(branch_detection.detect_missing_branches("", []), [])
        self.assertEqual(branch_detection.detect_missing_branches(None, None), [])
        self.assertEqual(
            branch_detection.detect_missing_branches("/nonexistent/repo/path", [{"slug": "x"}]),
            [],
        )

    def test_owner_module_doc_is_present(self):
        self.assertTrue(
            os.path.isfile(os.path.join(_REPO, "docs", "missing-branch-recovery-owner-module.md")),
            "slice-3 artifact docs/missing-branch-recovery-owner-module.md is missing",
        )


if __name__ == "__main__":
    unittest.main()
