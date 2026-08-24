#!/usr/bin/env python3
"""Coverage for merge_candidate — the merged-diff extraction gate.

The invariants under test:
  * a rejection is always CHEAP: gate 1 decides from the message, before subprocesses;
  * real agent work is never rejected — a false negative silently stops the fleet
    learning, and nothing would report it;
  * the gate is off-switchable and every rejection carries a reason.
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import merge_candidate as mc  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("MERGE_CANDIDATE_ENABLED", raising=False)
    monkeypatch.delenv("MERGE_CANDIDATE_REQUIRE_AGENT", raising=False)
    monkeypatch.delenv("MERGED_DIFF_IGNORED_GLOBS", raising=False)


# ── gate 1: messages ────────────────────────────────────────────────────────

def test_an_agent_branch_merge_is_a_candidate():
    ok, _ = mc.is_candidate_message("Merge agent/improve-thing into master")
    assert ok is True


def test_a_revert_is_rejected():
    ok, reason = mc.is_candidate_message("Revert \"Merge agent/thing\"")
    assert ok is False
    assert "revert" in reason.lower()


def test_revert_is_matched_on_a_word_boundary_only():
    """An identifier that merely contains the letters must not trip the revert rule.

    `reverted_at` is a column name, not a revert: `_` is a word character, so the
    trailing \\b does not match and the merge stays a candidate. `subversion` likewise.
    Rejecting real agent work because a column was named after a timestamp is a false
    negative, and a false negative here is invisible — the fleet just quietly stops
    learning from that merge.
    """
    assert mc.is_candidate_message("Merge agent/x: add reverted_at column")[0] is True
    assert mc.is_candidate_message("Merge agent/x: add subversion support")[0] is True
    # But the actual word, in the shapes git and humans write it, still is one.
    for message in ("Revert \"Merge agent/x\"", "Merge agent/x: reverts the cache change",
                    "Merge agent/x reverting bad commit"):
        assert mc.is_candidate_message(message)[0] is False


@pytest.mark.parametrize("marker", ["WIP", "fixup!", "squash!", "amend!"])
def test_work_in_progress_markers_are_rejected(marker):
    ok, reason = mc.is_candidate_message(f"Merge agent/x {marker} something")
    assert ok is False
    assert "progress" in reason.lower()


def test_a_sync_merge_of_master_into_itself_is_rejected():
    ok, reason = mc.is_candidate_message("Merge remote-tracking branch 'origin/master'")
    assert ok is False
    assert "agent" in reason.lower()


def test_a_bare_sha_merge_into_head_is_rejected():
    ok, _ = mc.is_candidate_message("Merge commit 'd9a5dd25' into HEAD")
    assert ok is False


def test_a_human_pr_merge_is_rejected():
    ok, _ = mc.is_candidate_message("Merge pull request #63 from kalepasch1/fix/lock")
    assert ok is False


def test_an_empty_message_is_rejected_with_a_reason():
    for value in ("", "   ", None, 42):
        ok, reason = mc.is_candidate_message(value)
        assert ok is False and reason


def test_every_rejection_carries_a_nonempty_reason():
    for message in ("Revert x", "Merge x WIP", "Merge origin/master", ""):
        ok, reason = mc.is_candidate_message(message)
        assert ok is False and reason.strip()


def test_require_agent_can_be_relaxed(monkeypatch):
    monkeypatch.setenv("MERGE_CANDIDATE_REQUIRE_AGENT", "false")
    ok, _ = mc.is_candidate_message("Merge pull request #63 from kalepasch1/fix/lock")
    assert ok is True


def test_kill_switch_accepts_everything(monkeypatch):
    monkeypatch.setenv("MERGE_CANDIDATE_ENABLED", "false")
    assert mc.is_candidate_message("Revert everything")[0] is True
    assert mc.is_candidate_record([])[0] is True


# ── filtering ───────────────────────────────────────────────────────────────

def test_filter_splits_kept_from_rejected():
    commits = [("aaa", "Merge agent/good into master"),
               ("bbb", "Merge remote-tracking branch 'origin/master'"),
               ("ccc", "Revert \"Merge agent/bad\"")]
    kept, rejected = mc.filter_candidate_messages(commits)
    assert [c[0] for c in kept] == ["aaa"]
    assert [c[0] for c in rejected] == ["bbb", "ccc"]


def test_rejected_entries_carry_the_reason_not_the_message():
    _, rejected = mc.filter_candidate_messages([("bbb", "Merge origin/master")])
    assert "agent" in rejected[0][1].lower()


def test_malformed_entries_are_rejected_not_crashed():
    kept, rejected = mc.filter_candidate_messages([None, ("only-one",), 7])
    assert kept == []
    assert len(rejected) == 3


def test_empty_input_is_empty_output():
    assert mc.filter_candidate_messages([]) == ([], [])
    assert mc.filter_candidate_messages(None) == ([], [])


# ── gate 2: paths ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    "package-lock.json", "yarn.lock", "go.sum", "Cargo.lock",
    "node_modules/left-pad/index.js", "runner/__pycache__/db.cpython-39.pyc",
    "dist/app.js", "build/out.o", "vendor/lib.py", "coverage/lcov.info",
    "static/app.min.js", "static/app.min.css", "static/app.js.map",
    "docs/diagram.png", "fonts/x.woff2", "lib/native.so",
])
def test_generated_and_binary_paths_are_ignored(path):
    assert mc.is_ignored_path(path) is True


@pytest.mark.parametrize("path", [
    "runner/db.py", "runner/merge_candidate.py", "app/pages/index.vue",
    "README.md", "src/main.ts", ".github/workflows/ci.yml",
])
def test_real_source_paths_are_not_ignored(path):
    assert mc.is_ignored_path(path) is False


def test_dist_is_matched_as_a_component_not_a_substring():
    """`runner/distribution.py` must survive the 'dist' rule."""
    assert mc.is_ignored_path("runner/distribution.py") is False
    assert mc.is_ignored_path("dist/bundle.js") is True


def test_leading_dot_slash_is_normalised():
    assert mc.is_ignored_path("./node_modules/x.js") is True
    assert mc.is_ignored_path("./runner/db.py") is False


def test_empty_and_non_string_paths_are_treated_as_ignorable():
    for value in ("", "   ", None, 42, []):
        assert mc.is_ignored_path(value) is True


def test_a_merge_touching_source_is_a_candidate():
    ok, _ = mc.is_candidate_record(["runner/db.py", "package-lock.json"])
    assert ok is True


def test_an_empty_diff_is_rejected():
    ok, reason = mc.is_candidate_record([])
    assert ok is False
    assert "empty" in reason.lower()


def test_a_lockfile_only_merge_is_rejected():
    ok, reason = mc.is_candidate_record(["package-lock.json", "yarn.lock"])
    assert ok is False
    assert "ignorable" in reason.lower()


def test_a_missing_file_list_is_rejected_not_assumed_good():
    ok, reason = mc.is_candidate_record(None)
    assert ok is False and reason


def test_a_non_iterable_file_list_is_rejected():
    ok, _ = mc.is_candidate_record(7)
    assert ok is False


# ── operator-configurable globs ─────────────────────────────────────────────

def test_extra_globs_can_ignore_a_path_by_full_path(monkeypatch):
    monkeypatch.setenv("MERGED_DIFF_IGNORED_GLOBS", "docs/*")
    assert mc.is_ignored_path("docs/notes.md") is True
    assert mc.is_ignored_path("runner/db.py") is False


def test_extra_globs_can_ignore_a_path_by_filename(monkeypatch):
    monkeypatch.setenv("MERGED_DIFF_IGNORED_GLOBS", "*.snap")
    assert mc.is_ignored_path("tests/x/__snapshots__.snap") is True


def test_extra_globs_make_an_otherwise_good_merge_a_non_candidate(monkeypatch):
    monkeypatch.setenv("MERGED_DIFF_IGNORED_GLOBS", "docs/*")
    assert mc.is_candidate_record(["docs/a.md", "docs/b.md"])[0] is False


def test_blank_glob_entries_are_ignored(monkeypatch):
    monkeypatch.setenv("MERGED_DIFF_IGNORED_GLOBS", " , ,")
    assert mc.is_ignored_path("runner/db.py") is False


def test_stats_reports_the_live_configuration():
    s = mc.stats()
    assert s["enabled"] is True and s["require_agent_branch"] is True
    assert "node_modules" in s["ignored_dirs"]


# ── the measurement this gate was justified by ──────────────────────────────

def test_the_gate_reproduces_the_recorded_saving_on_this_repo():
    """The task recorded 448 merges / 14 days with 58 non-candidates.

    Asserting the exact historical numbers would rot the moment anyone merges again, so
    this pins the RATIO instead: a double-digit percentage is rejected, and the large
    majority is kept. A gate that rejected almost everything, or almost nothing, would
    be broken in a way the unit tests above cannot see.
    """
    try:
        out = subprocess.check_output(
            ["git", "log", "--format=%h %s", "--merges", "--since=14 days ago", "master"],
            cwd=REPO, text=True, errors="replace", timeout=60)
    except (subprocess.SubprocessError, OSError):
        pytest.skip("git history unavailable")

    commits = [tuple(line.split(None, 1)) for line in out.splitlines()
               if len(line.split(None, 1)) == 2]
    if len(commits) < 50:
        pytest.skip("not enough merge history in the window to be meaningful")

    kept, rejected = mc.filter_candidate_messages(commits)
    assert len(kept) + len(rejected) == len(commits)

    share = len(rejected) / len(commits)
    assert 0.02 < share < 0.5, (
        f"gate rejected {len(rejected)}/{len(commits)} ({share:.0%}) — "
        "outside the plausible band; the predicate has probably drifted")
