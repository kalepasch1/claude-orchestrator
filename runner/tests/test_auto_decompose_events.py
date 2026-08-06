#!/usr/bin/env python3
"""Wiring test: auto_decompose.decompose emits decomposition_completed so the
missing-branch auto-creator provisions branches for new slices."""
import unittest
from unittest.mock import patch

from runner import auto_decompose, decomposition_events


class RecordingProvisioner:
    def __init__(self):
        self.calls = []

    def __call__(self, slug, repo_path, base_branch):
        self.calls.append((slug, repo_path, base_branch))
        return True


NUMBERED_PROMPT = (
    "Do the following:\n1. first thing\n2. second thing\n3. third thing\n"
)


class TestDecomposeEventWiring(unittest.TestCase):
    def setUp(self):
        decomposition_events.invalidate()

    def tearDown(self):
        decomposition_events.invalidate()

    def test_decompose_emits_event_and_provisions_children(self):
        p = RecordingProvisioner()
        decomposition_events._get_handler().provisioner = p
        with patch.object(auto_decompose, "_ENABLED", True):
            tasks = auto_decompose.decompose(
                "parent", NUMBERED_PROMPT, base_branch="master",
                repo_path="/tmp/repo",
            )
        self.assertGreater(len(tasks), 1)
        provisioned = [c[0] for c in p.calls]
        self.assertEqual(provisioned, [t["slug"] for t in tasks])

    def test_no_event_without_repo_path_provisioning(self):
        p = RecordingProvisioner()
        decomposition_events._get_handler().provisioner = p
        with patch.object(auto_decompose, "_ENABLED", True):
            auto_decompose.decompose("parent", NUMBERED_PROMPT)
        self.assertEqual(p.calls, [])  # skipped, left for the sweep

    def test_event_failure_never_breaks_decomposition(self):
        with patch.object(auto_decompose, "_ENABLED", True):
            with patch.object(
                decomposition_events, "on_decomposition_completed",
                side_effect=RuntimeError("boom"),
            ):
                tasks = auto_decompose.decompose(
                    "parent", NUMBERED_PROMPT, repo_path="/tmp/repo",
                )
        self.assertGreater(len(tasks), 1)

    def test_single_task_prompt_emits_nothing(self):
        p = RecordingProvisioner()
        decomposition_events._get_handler().provisioner = p
        with patch.object(auto_decompose, "_ENABLED", True):
            tasks = auto_decompose.decompose(
                "parent", "one small change", repo_path="/tmp/repo",
            )
        self.assertEqual(len(tasks), 1)
        self.assertEqual(p.calls, [])


if __name__ == "__main__":
    unittest.main()
