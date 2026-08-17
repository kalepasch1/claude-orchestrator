#!/usr/bin/env python3
"""Tests for the refs/orch-rescue/* classifier.

Builds real throwaway repositories rather than mocking git, because the whole
point of the module is what git actually reports about blob genealogy.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.reconcile_orch_rescue import (  # noqa: E402
    ALREADY_PRESENT,
    CONFLICTED,
    RECOVERABLE_VALUE,
    SUPERSEDED_BY_NEWER,
    build_base_blob_index,
    classify_file,
    is_noise,
    roll_up,
)


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


def write(repo, path, content):
    target = Path(repo) / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)


def commit(repo, message):
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", message)


class NoiseTest(unittest.TestCase):
    def test_dotfiles_and_caches_are_noise(self):
        for path in (
            ".canary-gemini-35",
            "runner/.preopt_cache/abc.json",
            ".recovery-intent-thing.txt",
            "docs/notes.md",
            "web/.orchestrator/state.json",
        ):
            self.assertTrue(is_noise(path), path)

    def test_product_code_is_not_noise(self):
        for path in (
            "runner/release_train.py",
            "web/components/FleetHealthBadge.vue",
            "supabase/migrations/2026_guard.sql",
        ):
            self.assertFalse(is_noise(path), path)

    def test_json_under_a_normal_directory_is_still_noise(self):
        # Sweeps are dominated by generated JSON; treating it as product code
        # made every ref look conflicted.
        self.assertTrue(is_noise("runner/cache/result.json"))


class RollUpTest(unittest.TestCase):
    def test_empty_rolls_up_to_already_present(self):
        self.assertEqual(roll_up([]), ALREADY_PRESENT)

    def test_worst_verdict_wins(self):
        self.assertEqual(
            roll_up([ALREADY_PRESENT, SUPERSEDED_BY_NEWER, CONFLICTED]), CONFLICTED
        )
        self.assertEqual(
            roll_up([ALREADY_PRESENT, RECOVERABLE_VALUE]), RECOVERABLE_VALUE
        )

    def test_recoverable_outranks_superseded(self):
        self.assertEqual(
            roll_up([SUPERSEDED_BY_NEWER, RECOVERABLE_VALUE]), RECOVERABLE_VALUE
        )


class ClassifyFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        git(self.repo, "init", "-q", "-b", "master")
        write(self.repo, "keep.py", "v1\n")
        commit(self.repo, "base")
        self.base = "master"

    def tearDown(self):
        self.tmp.cleanup()

    def _sha(self):
        return subprocess.run(
            ["git", "-C", self.repo, "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    def test_identical_content_is_already_present(self):
        self.assertEqual(
            classify_file(self.repo, self._sha(), "keep.py", self.base),
            ALREADY_PRESENT,
        )

    def test_path_absent_from_base_is_recoverable(self):
        write(self.repo, "new.py", "brand new\n")
        commit(self.repo, "add new")
        sha = self._sha()
        git(self.repo, "update-ref", "refs/heads/master", "HEAD~1")
        self.assertEqual(
            classify_file(self.repo, sha, "new.py", self.base), RECOVERABLE_VALUE
        )

    def test_older_state_of_a_tracked_file_is_superseded(self):
        old = self._sha()
        write(self.repo, "keep.py", "v2\n")
        commit(self.repo, "advance")
        # `old` holds v1, which is a historical state of master.
        self.assertEqual(
            classify_file(self.repo, old, "keep.py", self.base), SUPERSEDED_BY_NEWER
        )

    def test_prebuilt_index_matches_lazy_lookup(self):
        # The fast path must agree with the slow path, or the speedup is a bug.
        old = self._sha()
        write(self.repo, "keep.py", "v2\n")
        commit(self.repo, "advance")
        index = build_base_blob_index(self.repo, self.base)
        self.assertEqual(
            classify_file(self.repo, old, "keep.py", self.base, index),
            classify_file(self.repo, old, "keep.py", self.base),
        )

    def test_index_contains_historical_states_not_just_the_tip(self):
        write(self.repo, "keep.py", "v2\n")
        commit(self.repo, "advance")
        index = build_base_blob_index(self.repo, self.base)
        self.assertIn(
            f"{subprocess.run(['git', '-C', self.repo, 'rev-parse', 'HEAD~1:keep.py'], capture_output=True, text=True, check=True).stdout.strip()}:keep.py",
            index,
        )

    def test_content_never_on_base_is_conflicted(self):
        git(self.repo, "checkout", "-q", "-b", "sweep")
        write(self.repo, "keep.py", "divergent variant\n")
        commit(self.repo, "sweep wip")
        sweep = self._sha()
        git(self.repo, "checkout", "-q", "master")
        write(self.repo, "keep.py", "master went elsewhere\n")
        commit(self.repo, "master advance")
        self.assertEqual(
            classify_file(self.repo, sweep, "keep.py", self.base), CONFLICTED
        )


if __name__ == "__main__":
    unittest.main()
