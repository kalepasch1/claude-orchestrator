"""Tests for the parse-diff-to-extract layer of merged_diff_memory.

`parse_merge_diff` and its four helpers shipped without a single test or a
single caller, so nothing held their behaviour in place. Each helper encodes a
deliberate, non-obvious decision that a well-meaning refactor would otherwise
silently undo:

  * `_parse_numstat` counts a binary file as changed but contributes no lines,
    because "0 lines" and "not a text file" are different facts.
  * `_count_conflict_resolutions` counts `<<<<<<<` only. `=======` is how
    markdown and rst underline headings, and this repo is full of both, so
    counting it would report conflicts in every documentation merge.
  * `_dedupe_and_cap` preserves git's tree order rather than sorting, and marks
    the overflow rather than dropping it silently.
  * `_to_iso_utc` falls back to now() rather than "", because these records are
    read back as JSON and sorted as text, and an undated record is
    indistinguishable from a corrupt one.

The end-to-end tests build a real git repository with a real merge, so the
`-m --first-parent` flags are exercised against git itself: a plain diff of a
merge commit prints nothing at all, which is the bug those flags exist to fix.
"""

import json
import subprocess
from datetime import datetime, timezone

import pytest

import merged_diff_memory as mdm


# --------------------------------------------------------------------------
# _parse_numstat
# --------------------------------------------------------------------------

def test_parse_numstat_sums_insertions_and_deletions():
    paths, ins, dels = mdm._parse_numstat("3\t1\ta.py\n10\t2\tb.py\n")
    assert paths == ["a.py", "b.py"]
    assert ins == 13
    assert dels == 3


def test_parse_numstat_counts_binary_file_but_adds_no_lines():
    """`-\\t-\\tpath` is git's binary marker: a changed file worth zero lines."""
    paths, ins, dels = mdm._parse_numstat("-\t-\tlogo.png\n5\t0\tnotes.md\n")
    assert paths == ["logo.png", "notes.md"]
    assert ins == 5
    assert dels == 0


def test_parse_numstat_ignores_malformed_and_empty_input():
    assert mdm._parse_numstat("") == ([], 0, 0)
    assert mdm._parse_numstat(None) == ([], 0, 0)
    # Fewer than three tab-separated fields is not a numstat line.
    assert mdm._parse_numstat("garbage\nalso\tgarbage\n") == ([], 0, 0)


def test_parse_numstat_keeps_last_field_as_path_for_renames():
    """Rename lines carry extra fields; the path is the final one."""
    paths, _, _ = mdm._parse_numstat("1\t1\told.py\tnew.py\n")
    assert paths == ["new.py"]


# --------------------------------------------------------------------------
# _dedupe_and_cap
# --------------------------------------------------------------------------

def test_dedupe_and_cap_preserves_first_seen_order():
    assert mdm._dedupe_and_cap(["b.py", "a.py", "b.py", "c.py"]) == ["b.py", "a.py", "c.py"]


def test_dedupe_and_cap_marks_the_overflow_instead_of_dropping_it():
    result = mdm._dedupe_and_cap([f"f{i}.py" for i in range(60)], limit=50)
    assert len(result) == 51
    assert result[-1] == "+10 more"
    assert result[0] == "f0.py"


def test_dedupe_and_cap_discards_blank_paths():
    assert mdm._dedupe_and_cap(["", "  ", "a.py", None]) == ["a.py"]


def test_dedupe_and_cap_at_exactly_the_limit_adds_no_marker():
    result = mdm._dedupe_and_cap([f"f{i}.py" for i in range(50)], limit=50)
    assert len(result) == 50
    assert "more" not in result[-1]


# --------------------------------------------------------------------------
# _count_conflict_resolutions
# --------------------------------------------------------------------------

def test_count_conflict_resolutions_counts_opening_markers():
    patch = (
        "+<<<<<<< HEAD\n"
        "+ours\n"
        "+=======\n"
        "+theirs\n"
        "+>>>>>>> branch\n"
        "+<<<<<<< HEAD\n"
        "+second\n"
        "+>>>>>>> branch\n"
    )
    assert mdm._count_conflict_resolutions(patch) == 2


def test_markdown_underline_is_not_a_conflict():
    """The regression this helper exists to prevent.

    `=======` underlines a setext heading in markdown and rst. Counting it
    would report a conflict in essentially every documentation merge in this
    repository.
    """
    patch = "+Release Notes\n+=============\n+\n+Some prose.\n+-------\n"
    assert mdm._count_conflict_resolutions(patch) == 0


def test_count_conflict_resolutions_on_empty_input():
    assert mdm._count_conflict_resolutions("") == 0
    assert mdm._count_conflict_resolutions(None) == 0


# --------------------------------------------------------------------------
# _to_iso_utc
# --------------------------------------------------------------------------

def test_to_iso_utc_converts_offset_to_utc():
    assert mdm._to_iso_utc("2026-08-02T12:00:00-04:00") == "2026-08-02T16:00:00Z"


def test_to_iso_utc_normalises_trailing_z():
    assert mdm._to_iso_utc("2026-08-02T16:00:00Z") == "2026-08-02T16:00:00Z"


def test_to_iso_utc_falls_back_to_now_for_garbage():
    """An undated record is indistinguishable from a corrupt one, so never ''."""
    for bad in ("", None, "not-a-date"):
        out = mdm._to_iso_utc(bad)
        assert out.endswith("Z")
        # Parses, and is roughly now rather than an arbitrary epoch.
        parsed = datetime.fromisoformat(out.replace("Z", "+00:00"))
        assert abs((datetime.now(timezone.utc) - parsed).total_seconds()) < 120


def test_to_iso_utc_output_sorts_as_text_in_chronological_order():
    """These records are stored as JSON and ordered by string comparison."""
    earlier = mdm._to_iso_utc("2026-08-02T12:00:00-04:00")   # 16:00Z
    later = mdm._to_iso_utc("2026-08-02T13:00:00-04:00")     # 17:00Z
    assert earlier < later


# --------------------------------------------------------------------------
# parse_merge_diff — end to end against a real repository
# --------------------------------------------------------------------------

def _git(*args, cwd):
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


@pytest.fixture
def merged_repo(tmp_path):
    """A repo whose tip is a true merge commit of a two-file branch."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)
    _git("config", "user.email", "test@example.com", cwd=repo)
    _git("config", "user.name", "Test", cwd=repo)
    _git("config", "commit.gpgsign", "false", cwd=repo)

    (repo / "base.txt").write_text("line one\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "base", cwd=repo)

    _git("checkout", "-q", "-b", "feature", cwd=repo)
    (repo / "added.txt").write_text("alpha\nbeta\ngamma\n")
    (repo / "base.txt").write_text("line one\nline two\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "feature work", cwd=repo)

    _git("checkout", "-q", "main", cwd=repo)
    # --no-ff guarantees a real merge commit, which is the case that returns an
    # empty diff without `-m --first-parent`.
    _git("merge", "--no-ff", "-q", "-m", "Merge branch 'feature'", "feature", cwd=repo)

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo, check=True, stdout=subprocess.PIPE, text=True,
    ).stdout.strip()
    return repo, head


def test_parse_merge_diff_extracts_every_spec_field(merged_repo):
    repo, head = merged_repo
    record = mdm.parse_merge_diff(head, "feature", cwd=str(repo))

    assert set(record) == {
        "files_changed", "insertions", "deletions",
        "conflict_resolutions", "branch_name", "merge_date",
    }
    assert sorted(record["files_changed"]) == ["added.txt", "base.txt"]
    # 3 lines in added.txt + 1 appended to base.txt.
    assert record["insertions"] == 4
    assert record["deletions"] == 0
    assert record["conflict_resolutions"] == 0
    assert record["branch_name"] == "feature"
    assert record["merge_date"].endswith("Z")


def test_parse_merge_diff_sees_a_merge_commit_at_all(merged_repo):
    """Guards the `-m --first-parent` flags.

    Without them git prints nothing for a merge commit and every record came
    back with an empty file list — the defect these flags were added to fix.
    """
    repo, head = merged_repo
    assert mdm.parse_merge_diff(head, "feature", cwd=str(repo))["files_changed"]


def test_parse_merge_diff_is_fail_soft_on_an_unknown_commit(tmp_path):
    """A repo it cannot read must not wedge a caller writing memory."""
    record = mdm.parse_merge_diff("0" * 40, "ghost", cwd=str(tmp_path))
    assert record["files_changed"] == []
    assert record["insertions"] == 0
    assert record["deletions"] == 0
    assert record["conflict_resolutions"] == 0
    assert record["branch_name"] == "ghost"
    assert record["merge_date"].endswith("Z")


def test_parse_merge_diff_record_is_json_serialisable(merged_repo):
    """The record is persisted as JSON, so it must survive a round trip."""
    repo, head = merged_repo
    record = mdm.parse_merge_diff(head, "feature", cwd=str(repo))
    assert json.loads(json.dumps(record)) == record
