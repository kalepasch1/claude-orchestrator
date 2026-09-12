#!/usr/bin/env python3
"""Tests for the relocated-file detection in reconcile_rescue_refs.classify().

Acceptance criteria from the task spec:
  1. A fixture repo where a file moved into a subdirectory unchanged →
     item classifies ALREADY_PRESENT and disposition names the new path.
  2. A fixture where the content also changed → does NOT classify as present.
"""

import os
import subprocess
import sys
import tempfile
import unittest

# Allow importing the module under test from the tools/ directory.
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

import reconcile_rescue_refs as rrr  # noqa: E402


def _git(cwd, *args):
    r = subprocess.run(
        ["git"] + list(args), cwd=cwd,
        capture_output=True, text=True, errors="replace",
    )
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr}")
    return r.stdout.strip()


def _make_fixture_repo(tmp):
    """Build a fixture repo where the rescue commit's file was moved in base.

    Rescue commit modifies contract.ts → content B.
    Base branch moves contract.ts to layers/contract.ts with the SAME content B.
    So the rescue commit's blob exists in base at a different path → relocated.
    """
    repo = os.path.join(tmp, "repo")
    os.makedirs(repo)
    _git(repo, "init")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "user.email", "test@test")

    # Initial commit: file at top level
    fpath = os.path.join(repo, "contract.ts")
    with open(fpath, "w") as f:
        f.write("export const filings = { version: 1 };\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")

    # Branch off: modify contract.ts on rescue branch
    _git(repo, "checkout", "-b", "rescue-branch")
    with open(fpath, "w") as f:
        f.write("export const filings = { version: 2 };\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "update contract on rescue branch")
    rescue_sha = _git(repo, "rev-parse", "HEAD")

    # Create rescue ref
    _git(repo, "update-ref", "refs/orch-rescue/test-relocated", rescue_sha)

    # Back to main: move contract.ts into a subdirectory WITH the same v2 content
    # (simulates someone independently making the same change and also reorganising)
    _git(repo, "checkout", "main")
    os.makedirs(os.path.join(repo, "layers"), exist_ok=True)
    _git(repo, "mv", "contract.ts", "layers/contract.ts")
    with open(os.path.join(repo, "layers", "contract.ts"), "w") as f:
        f.write("export const filings = { version: 2 };\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "move contract into layers/ with v2 content")

    base_sha = _git(repo, "rev-parse", "HEAD")
    return repo, rescue_sha, base_sha


def _make_modified_fixture_repo(tmp):
    """Build a fixture where file moved AND content diverged — should NOT match.

    Rescue commit modifies engine.py → content B.
    Base branch moves engine.py to core/engine.py with DIFFERENT content C.
    Blob mismatch → should not classify as relocated.
    """
    repo = os.path.join(tmp, "repo2")
    os.makedirs(repo)
    _git(repo, "init")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "user.email", "test@test")

    # Initial commit
    fpath = os.path.join(repo, "engine.py")
    with open(fpath, "w") as f:
        f.write("def run(): pass\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")

    # Rescue branch: modify engine.py to content B
    _git(repo, "checkout", "-b", "rescue-branch")
    with open(fpath, "w") as f:
        f.write("def run(): return 42\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "modify engine on rescue branch")
    rescue_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/orch-rescue/test-modified", rescue_sha)

    # Main: move engine.py into subdir with DIFFERENT content C
    _git(repo, "checkout", "main")
    os.makedirs(os.path.join(repo, "core"), exist_ok=True)
    _git(repo, "mv", "engine.py", "core/engine.py")
    with open(os.path.join(repo, "core", "engine.py"), "w") as f:
        f.write("def run(): return 99\n")  # different from rescue's version
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "move and modify engine")

    base_sha = _git(repo, "rev-parse", "HEAD")
    return repo, rescue_sha, base_sha


class TestRelocatedFileDetection(unittest.TestCase):

    def test_moved_file_classifies_already_present(self):
        """File moved to a subdirectory with identical content → ALREADY_PRESENT."""
        with tempfile.TemporaryDirectory() as tmp:
            repo, rescue_sha, base_sha = _make_fixture_repo(tmp)
            orig_dir = os.getcwd()
            os.chdir(repo)
            try:
                rrr._BASE_BLOB_INDEX.clear()

                item = rrr.Item(
                    ref="refs/orch-rescue/test-relocated",
                    sha=rescue_sha,
                    subject="update contract on rescue branch",
                    created_at=0,
                )
                rrr.classify(item, base_sha, set())

                self.assertEqual(item.classification, "ALREADY_PRESENT")
                self.assertIn("relocated", item.disposition)
                self.assertIn("layers/contract.ts", item.disposition)
                self.assertEqual(item.evidence, "blob-hash relocation match")
            finally:
                os.chdir(orig_dir)

    def test_modified_file_does_not_classify_as_present(self):
        """File moved AND content changed → should NOT be ALREADY_PRESENT."""
        with tempfile.TemporaryDirectory() as tmp:
            repo, rescue_sha, base_sha = _make_modified_fixture_repo(tmp)
            orig_dir = os.getcwd()
            os.chdir(repo)
            try:
                rrr._BASE_BLOB_INDEX.clear()

                item = rrr.Item(
                    ref="refs/orch-rescue/test-modified",
                    sha=rescue_sha,
                    subject="modify engine on rescue branch",
                    created_at=0,
                )
                rrr.classify(item, base_sha, set())

                self.assertNotEqual(item.classification, "ALREADY_PRESENT",
                                    "content-changed file must not be classified as relocated")
            finally:
                os.chdir(orig_dir)


if __name__ == "__main__":
    unittest.main()
