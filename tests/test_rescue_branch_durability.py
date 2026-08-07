#!/usr/bin/env python3
"""Lease-night recovery, group 1 — the provenance record must survive this disk.

The directive says the rescue branches must not be deleted. Verified 2026-08-05: 34 of them
exist locally and none on origin, so nobody has to delete them for them to be gone.
"""
import os
import sys
import unittest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
sys.path.insert(0, RUNNER)

import rescue_branch_durability as rbd  # noqa: E402

BRANCHES = [
    "hotfix/stash-rescue-lease-night-5f879035",
    "hotfix/stash-rescue-1785390775-21cf368b",
    "hotfix/sentinel-rescue-1785390775",
    "recovery/stashes-20260730-101500",
]


class NamespaceTests(unittest.TestCase):
    def test_every_rescue_namespace_is_recognised(self):
        for branch in BRANCHES:
            self.assertTrue(rbd.is_rescue_branch(branch), branch)

    def test_ordinary_branches_are_not_rescue_branches(self):
        for branch in ("master", "agent/some-task", "orchestrator/dev", "hotfix/unrelated"):
            self.assertFalse(rbd.is_rescue_branch(branch), branch)

    def test_the_current_branch_marker_is_tolerated(self):
        self.assertTrue(rbd.is_rescue_branch("* hotfix/stash-rescue-x"))

    def test_junk_is_fail_soft(self):
        for value in (None, "", 42, []):
            self.assertFalse(rbd.is_rescue_branch(value), repr(value))

    def test_listing_filters_to_rescue_branches_only(self):
        listing = "\n".join(BRANCHES + ["master", "agent/x", ""])
        self.assertEqual(rbd.list_rescue_branches(repo="/tmp", lister=lambda r: listing),
                         sorted(BRANCHES))

    def test_listing_is_fail_soft(self):
        def boom(repo):
            raise OSError("no git")
        self.assertEqual(rbd.list_rescue_branches(repo="/tmp", lister=boom), [])


class AuditTests(unittest.TestCase):
    def test_the_observed_state_is_reported_as_at_risk(self):
        """34 local, 0 on origin — the state actually measured on Mac 1."""
        report = rbd.audit(branches=BRANCHES, on_origin=lambda b: False)
        self.assertEqual(report["total"], 4)
        self.assertEqual(report["local_only"], 4)
        self.assertEqual(report["durable"], 0)
        self.assertEqual(report["at_risk"], BRANCHES)
        self.assertIn("already lost once", report["reason"])

    def test_a_fully_backed_set_reports_nothing_at_risk(self):
        report = rbd.audit(branches=BRANCHES, on_origin=lambda b: True)
        self.assertEqual(report["at_risk"], [])
        self.assertEqual(report["durable"], 4)
        self.assertEqual(report["reason"], "")

    def test_a_mixed_set_names_only_the_unbacked_ones(self):
        report = rbd.audit(branches=BRANCHES,
                           on_origin=lambda b: b.startswith("recovery/"))
        self.assertEqual(report["durable"], 1)
        self.assertEqual(len(report["at_risk"]), 3)
        self.assertNotIn("recovery/stashes-20260730-101500", report["at_risk"])

    def test_an_unprovable_branch_fails_CLOSED(self):
        """Unproven must mean at-risk. Assuming safety is how the first loss happened."""
        def boom(branch):
            raise RuntimeError("git unavailable")
        report = rbd.audit(branches=BRANCHES, on_origin=boom)
        self.assertEqual(report["at_risk"], BRANCHES)

    def test_an_empty_repo_reports_nothing_rather_than_failing(self):
        report = rbd.audit(branches=[], on_origin=lambda b: True)
        self.assertEqual(report["total"], 0)
        self.assertEqual(report["at_risk"], [])


class SweepTests(unittest.TestCase):
    def setUp(self):
        self.archived = []
        self.shared = []

    def _archiver(self, branch):
        self.archived.append(branch)
        return "abc123"

    def _sharer(self, branch):
        self.shared.append(branch)
        return True

    def test_sweep_is_read_only_by_default(self):
        result = rbd.sweep(branches=BRANCHES, on_origin=lambda b: False,
                           archiver=self._archiver, sharer=self._sharer)
        self.assertEqual(self.shared, [], "sweep must not push unless asked")
        self.assertEqual(result["shared"], [])

    def test_sweep_archives_every_at_risk_tip_even_when_not_sharing(self):
        """The archive ref is the cheap half and survives gc regardless of what follows."""
        result = rbd.sweep(branches=BRANCHES, on_origin=lambda b: False,
                           archiver=self._archiver, sharer=self._sharer)
        self.assertEqual(sorted(result["archived"]), sorted(BRANCHES))

    def test_sharing_pushes_only_the_at_risk_branches(self):
        result = rbd.sweep(branches=BRANCHES, share=True,
                           on_origin=lambda b: b.startswith("recovery/"),
                           archiver=self._archiver, sharer=self._sharer)
        self.assertEqual(len(result["shared"]), 3)
        self.assertNotIn("recovery/stashes-20260730-101500", result["shared"])

    def test_a_failed_push_is_reported_not_swallowed(self):
        result = rbd.sweep(branches=BRANCHES, share=True, on_origin=lambda b: False,
                           archiver=self._archiver, sharer=lambda b: False)
        self.assertEqual(sorted(result["failed"]), sorted(BRANCHES))
        self.assertEqual(result["shared"], [])

    def test_a_throwing_sharer_is_reported_not_fatal(self):
        def boom(branch):
            raise RuntimeError("push refused")
        result = rbd.sweep(branches=BRANCHES, share=True, on_origin=lambda b: False,
                           archiver=self._archiver, sharer=boom)
        self.assertEqual(len(result["failed"]), len(BRANCHES))

    def test_nothing_at_risk_means_nothing_done(self):
        result = rbd.sweep(branches=BRANCHES, share=True, on_origin=lambda b: True,
                           archiver=self._archiver, sharer=self._sharer)
        self.assertEqual(result["archived"], [])
        self.assertEqual(result["shared"], [])


class NeverDeletesTests(unittest.TestCase):
    def test_the_module_has_no_delete_capability_at_all(self):
        """For these branches deletion is never right, so the capability is absent, not guarded."""
        source = open(os.path.join(RUNNER, "rescue_branch_durability.py"), errors="replace").read()
        for forbidden in ("safe_delete", '"-D"', "branch -D", "push origin --delete", "--delete"):
            self.assertNotIn(forbidden, source, f"found {forbidden}")

    def test_it_reuses_branch_durability_rather_than_reimplementing_it(self):
        source = open(os.path.join(RUNNER, "rescue_branch_durability.py"), errors="replace").read()
        self.assertIn("import branch_durability", source)
        self.assertIn("is_on_origin", source)
        self.assertIn("archive_branch", source)

    def test_the_shared_primitives_still_exist(self):
        import branch_durability
        for name in ("is_on_origin", "archive_branch", "try_share"):
            self.assertTrue(callable(getattr(branch_durability, name, None)), name)


class RenderTests(unittest.TestCase):
    def test_at_risk_branches_are_named_for_the_operator(self):
        text = rbd.render(rbd.sweep(branches=BRANCHES, on_origin=lambda b: False,
                                    archiver=lambda b: None, sharer=lambda b: False))
        self.assertIn("LOCAL ONLY", text)
        self.assertIn("hotfix/stash-rescue-lease-night-5f879035", text)
        self.assertIn("--share", text)

    def test_a_healthy_report_does_not_cry_wolf(self):
        text = rbd.render(rbd.sweep(branches=BRANCHES, on_origin=lambda b: True))
        self.assertNotIn("LOCAL ONLY\n    at risk", text)
        self.assertNotIn("--share", text)

    def test_render_is_fail_soft(self):
        self.assertIsInstance(rbd.render(None), str)
        self.assertIsInstance(rbd.render({}), str)


if __name__ == "__main__":
    unittest.main()
