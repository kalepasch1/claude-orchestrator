#!/usr/bin/env python3
"""Tests for decomposition_events — the missing-branch auto-creator's
decomposition-completion event handler (slice 3)."""
import threading
import unittest

from runner import decomposition_events


class RecordingProvisioner:
    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on or set()
        self.lock = threading.Lock()

    def __call__(self, slug, repo_path, base_branch):
        with self.lock:
            self.calls.append((slug, repo_path, base_branch))
        if slug in self.fail_on:
            raise RuntimeError(f"provision failed for {slug}")
        return True


class TestDecompositionEvents(unittest.TestCase):
    def setUp(self):
        decomposition_events.invalidate()

    def tearDown(self):
        decomposition_events.invalidate()

    def _handler_with(self, provisioner):
        h = decomposition_events._get_handler()
        h.provisioner = provisioner
        return h

    def test_provisions_branch_for_each_child(self):
        p = RecordingProvisioner()
        self._handler_with(p)
        result = decomposition_events.on_decomposition_completed(
            "parent", [{"slug": "parent-item-1"}, {"slug": "parent-item-2"}],
            repo_path="/tmp/repo", base_branch="master",
        )
        self.assertEqual(result["provisioned"],
                         ["parent-item-1", "parent-item-2"])
        self.assertEqual(len(p.calls), 2)
        self.assertEqual(p.calls[0], ("parent-item-1", "/tmp/repo", "master"))

    def test_child_base_branch_overrides_default(self):
        p = RecordingProvisioner()
        self._handler_with(p)
        decomposition_events.on_decomposition_completed(
            "parent", [{"slug": "c1", "base_branch": "dev"}],
            repo_path="/tmp/repo", base_branch="master",
        )
        self.assertEqual(p.calls[0][2], "dev")

    def test_failure_is_fail_soft_and_collected(self):
        p = RecordingProvisioner(fail_on={"c1"})
        self._handler_with(p)
        result = decomposition_events.on_decomposition_completed(
            "parent", [{"slug": "c1"}, {"slug": "c2"}], repo_path="/tmp/repo",
        )
        self.assertEqual(result["provisioned"], ["c2"])
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["slug"], "c1")

    def test_missing_repo_path_skips_without_error(self):
        p = RecordingProvisioner()
        self._handler_with(p)
        result = decomposition_events.on_decomposition_completed(
            "parent", [{"slug": "c1"}], repo_path=None,
        )
        self.assertEqual(result["provisioned"], [])
        self.assertEqual(result["skipped"], ["c1"])
        self.assertEqual(p.calls, [])

    def test_parent_slug_and_malformed_children_skipped(self):
        p = RecordingProvisioner()
        self._handler_with(p)
        result = decomposition_events.on_decomposition_completed(
            "parent", [{"slug": "parent"}, {}, None, {"slug": "ok"}],
            repo_path="/tmp/repo",
        )
        self.assertEqual(result["provisioned"], ["ok"])
        self.assertEqual(len(result["skipped"]), 3)

    def test_singleton_and_invalidate(self):
        first = decomposition_events._get_handler()
        self.assertIs(first, decomposition_events._get_handler())
        decomposition_events.invalidate()
        self.assertIsNot(first, decomposition_events._get_handler())

    def test_events_recorded_for_observability(self):
        p = RecordingProvisioner()
        self._handler_with(p)
        decomposition_events.on_decomposition_completed(
            "parent", [{"slug": "c1"}], repo_path="/tmp/repo",
        )
        events = decomposition_events.recent_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["parent_slug"], "parent")


if __name__ == "__main__":
    unittest.main()
