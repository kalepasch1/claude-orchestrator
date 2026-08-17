#!/usr/bin/env python3
"""Unit tests for merged-diff merge-candidate selection.

Covers `is_merge_candidate` (message level), `is_merge_candidate_commit` (record level),
the `_is_ignored_path` helper, and the wiring of both into the extraction pipeline.
"""
import os
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import merged_diff_memory as mdm


def _record(**overrides) -> dict:
    """Build a valid merge-candidate record, with per-test overrides."""
    record = {
        "commit_hash": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
        "branch_name": "test-feature-123",
        "merge_message": "Merge branch 'agent/test-feature-123'",
        "diff": "diff --git a/feature.py b/feature.py\n+def hello():\n",
        "files": ["feature.py"],
        "author_date": "2026-08-01T12:00:00+00:00",
        "extracted_at": "2026-08-01T12:00:01",
    }
    record.update(overrides)
    return record


class TestIsMergeCandidate:
    """Message-level predicate: is_merge_candidate(commit_message) -> bool."""

    def test_normal_agent_merge_is_candidate(self):
        assert mdm.is_merge_candidate("Merge branch 'agent/test-feature-123'")

    def test_double_quoted_branch_is_candidate(self):
        assert mdm.is_merge_candidate('Merge branch "agent/fix-thing"')

    def test_trailing_text_after_branch_is_candidate(self):
        assert mdm.is_merge_candidate("Merge branch 'agent/foo' (auto-resolved)")

    def test_leading_and_trailing_whitespace_tolerated(self):
        assert mdm.is_merge_candidate("  Merge branch 'agent/foo'  ")

    def test_multiline_message_uses_first_line(self):
        assert mdm.is_merge_candidate("Merge branch 'agent/foo'\n\nsome body text")

    def test_non_agent_branch_is_not_candidate(self):
        assert not mdm.is_merge_candidate("Merge branch 'feature/other'")
        assert not mdm.is_merge_candidate("Merge branch 'orchestrator/dev'")

    def test_plain_commit_is_not_candidate(self):
        assert not mdm.is_merge_candidate("fix: correct the thing")

    def test_revert_of_agent_merge_is_not_candidate(self):
        assert not mdm.is_merge_candidate("Revert \"Merge branch 'agent/foo'\"")
        assert not mdm.is_merge_candidate("revert: Merge branch 'agent/foo'")

    def test_wip_and_fixup_noise_is_not_candidate(self):
        assert not mdm.is_merge_candidate("WIP Merge branch 'agent/foo'")
        assert not mdm.is_merge_candidate("fixup! Merge branch 'agent/foo'")
        assert not mdm.is_merge_candidate("squash! Merge branch 'agent/foo'")

    def test_empty_branch_name_is_not_candidate(self):
        assert not mdm.is_merge_candidate("Merge branch 'agent/'")

    def test_empty_and_blank_messages_are_not_candidates(self):
        assert not mdm.is_merge_candidate("")
        assert not mdm.is_merge_candidate("   \n  ")

    def test_non_string_input_fails_soft(self):
        assert not mdm.is_merge_candidate(None)
        assert not mdm.is_merge_candidate(12345)
        assert not mdm.is_merge_candidate(["Merge branch 'agent/foo'"])

    def test_message_must_start_with_merge(self):
        assert not mdm.is_merge_candidate("chore: Merge branch 'agent/foo'")

    def test_returns_actual_bool(self):
        assert mdm.is_merge_candidate("Merge branch 'agent/foo'") is True
        assert mdm.is_merge_candidate("nope") is False


class TestIsIgnoredPath:
    """Ignored-path helper used by the record-level predicate."""

    def test_source_files_are_not_ignored(self):
        assert not mdm._is_ignored_path("tools/merged_diff_memory.py")
        assert not mdm._is_ignored_path("src/app/main.ts")

    def test_lockfiles_are_ignored(self):
        assert mdm._is_ignored_path("package-lock.json")
        assert mdm._is_ignored_path("requirements.lock")
        assert mdm._is_ignored_path("pnpm-lock.yaml")

    def test_vendored_and_build_dirs_are_ignored(self):
        assert mdm._is_ignored_path("node_modules/left-pad/index.js")
        assert mdm._is_ignored_path("tools/__pycache__/x.cpython-311.pyc")
        assert mdm._is_ignored_path("web/dist/bundle.js")
        assert mdm._is_ignored_path("coverage/lcov.info")

    def test_binaries_and_minified_assets_are_ignored(self):
        assert mdm._is_ignored_path("docs/logo.png")
        assert mdm._is_ignored_path("web/app.min.js")

    def test_leading_dot_slash_is_normalized(self):
        assert mdm._is_ignored_path("./node_modules/foo/index.js")
        assert not mdm._is_ignored_path("./tools/thing.py")

    def test_bad_input_counts_as_ignored(self):
        assert mdm._is_ignored_path("")
        assert mdm._is_ignored_path("   ")
        assert mdm._is_ignored_path(None)

    def test_env_var_extends_ignore_list(self):
        with mock.patch.dict(os.environ, {"MERGED_DIFF_IGNORED_GLOBS": "*.generated.ts, CHANGELOG.md"}):
            assert mdm._is_ignored_path("shared/types.generated.ts")
            assert mdm._is_ignored_path("CHANGELOG.md")
            assert not mdm._is_ignored_path("shared/types.ts")


class TestIsMergeCandidateCommit:
    """Record-level predicate: is_merge_candidate_commit(commit) -> bool."""

    def test_normal_record_is_candidate(self):
        assert mdm.is_merge_candidate_commit(_record())

    def test_empty_diff_is_not_candidate(self):
        assert not mdm.is_merge_candidate_commit(_record(diff=""))
        assert not mdm.is_merge_candidate_commit(_record(diff="   \n  "))
        assert not mdm.is_merge_candidate_commit(_record(diff=None))

    def test_revert_message_is_not_candidate(self):
        assert not mdm.is_merge_candidate_commit(
            _record(merge_message="Revert \"Merge branch 'agent/foo'\"")
        )

    def test_non_agent_merge_is_not_candidate(self):
        assert not mdm.is_merge_candidate_commit(
            _record(merge_message="Merge branch 'orchestrator/dev'")
        )

    def test_only_ignored_paths_is_not_candidate(self):
        assert not mdm.is_merge_candidate_commit(
            _record(files=["package-lock.json", "node_modules/x/index.js"])
        )

    def test_mixed_paths_with_one_real_file_is_candidate(self):
        assert mdm.is_merge_candidate_commit(
            _record(files=["package-lock.json", "tools/real.py"])
        )

    def test_no_files_is_not_candidate(self):
        assert not mdm.is_merge_candidate_commit(_record(files=[]))

    def test_missing_commit_hash_is_not_candidate(self):
        assert not mdm.is_merge_candidate_commit(_record(commit_hash=""))
        assert not mdm.is_merge_candidate_commit(_record(commit_hash=None))

    def test_malformed_records_fail_soft(self):
        assert not mdm.is_merge_candidate_commit(None)
        assert not mdm.is_merge_candidate_commit("Merge branch 'agent/foo'")
        assert not mdm.is_merge_candidate_commit({})
        assert not mdm.is_merge_candidate_commit(_record(files="feature.py"))

    def test_returns_actual_bool(self):
        assert mdm.is_merge_candidate_commit(_record()) is True
        assert mdm.is_merge_candidate_commit({}) is False


def _setup_repo_with(tmp_dir: str, merge_message: str, filename: str = "feature.py") -> str:
    """Build a git repo whose single agent merge uses `merge_message` and touches `filename`."""
    repo = os.path.join(tmp_dir, "repo")
    os.makedirs(repo)
    run = lambda *a: subprocess.run(list(a), cwd=repo, check=True, capture_output=True)
    run("git", "init")
    run("git", "config", "user.email", "test@example.com")
    run("git", "config", "user.name", "Test User")
    Path(repo, "README.md").write_text("# repo\n")
    run("git", "add", "README.md")
    run("git", "commit", "-m", "initial commit")
    base = subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo, text=True
    ).strip()

    run("git", "checkout", "-b", "agent/test-feature-123")
    target = Path(repo, filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def hello():\n    return 'world'\n")
    run("git", "add", "-A", "-f")  # -f: bypass any global gitignore (node_modules cases)
    run("git", "commit", "-m", "agent: test-feature-123")

    run("git", "checkout", base)
    run("git", "merge", "--no-ff", "-m", merge_message, "agent/test-feature-123")
    return repo


class TestExtractionWiring:
    """The predicates must actually gate the extraction pipeline."""

    def test_candidate_merge_is_extracted(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _setup_repo_with(tmp_dir, "Merge branch 'agent/test-feature-123'")
            diffs = mdm.extract_merged_diffs(repo, limit=10)
            assert len(diffs) == 1
            assert diffs[0]["branch_name"] == "test-feature-123"

    def test_revert_merge_is_filtered_by_scanner(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _setup_repo_with(tmp_dir, "Revert \"Merge branch 'agent/test-feature-123'\"")
            assert mdm.get_recent_merged_agent_branches(repo, limit=10) == []
            assert mdm.extract_merged_diffs(repo, limit=10) == []

    def test_merge_touching_only_ignored_paths_is_filtered(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _setup_repo_with(
                tmp_dir,
                "Merge branch 'agent/test-feature-123'",
                filename="node_modules/left-pad/index.js",
            )
            # The scanner still sees the merge; the record-level predicate rejects it.
            assert len(mdm.get_recent_merged_agent_branches(repo, limit=10)) == 1
            assert mdm.extract_merged_diffs(repo, limit=10) == []

    def test_empty_diff_merge_is_filtered(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _setup_repo_with(tmp_dir, "Merge branch 'agent/test-feature-123'")
            with mock.patch.object(mdm, "get_merge_diff", return_value=""):
                assert mdm.extract_merged_diffs(repo, limit=10) == []

    def test_stats_reflects_candidate_filtering(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _setup_repo_with(tmp_dir, "Merge branch 'agent/test-feature-123'")
            assert mdm.stats(repo, limit=10)["total_merge_commits"] == 1
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _setup_repo_with(tmp_dir, "WIP Merge branch 'agent/test-feature-123'")
            assert mdm.stats(repo, limit=10)["total_merge_commits"] == 0


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
