"""Spec §2 (parse diff to extract) and §5 (retrieval), for merged_diff_memory.

The spec asks for a minimum of eight cases across the success path, git errors,
I/O errors, DB errors and retrieval with and without a keyword. All five
categories are covered below.

Two decisions are asserted rather than merely implemented, because both are the
kind of thing a later reader would "simplify" back:

  * conflicts are counted from `<<<<<<<` alone. `=======` is also how markdown
    and rst underline headings, and this repo is full of both, so counting it
    would report conflicts in every documentation merge.
  * a keyword that matches nothing returns [], never the full list. Falling back
    to everything is how a filter silently stops filtering.
"""
import json
import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import merged_diff_memory as mdm  # noqa: E402


# ── helpers ────────────────────────────────────────────────────────────────

def numstat(*rows: tuple[str, str, str]) -> str:
    return "\n".join(f"{a}\t{d}\t{p}" for a, d, p in rows)


@pytest.fixture
def fake_git(monkeypatch):
    """Route every `_safe_run` call to a scripted response by subcommand."""

    def install(responses: dict[str, str]):
        def fake(cmd, cwd=None):
            if "--numstat" in cmd:
                return responses.get("numstat", "")
            if "show" in cmd:
                return responses.get("patch", "")
            if "log" in cmd:
                return responses.get("date", "")
            return ""

        monkeypatch.setattr(mdm, "_safe_run", fake)

    return install


# ── 1-4: success path ──────────────────────────────────────────────────────

def test_success_path_extracts_every_spec_field(fake_git):
    fake_git({
        "numstat": numstat(("10", "2", "runner/a.py"), ("5", "0", "runner/b.py")),
        "patch": "+++ b/runner/a.py\n+hello\n",
        "date": "2026-08-01T12:00:00+02:00",
    })

    record = mdm.parse_merge_diff("abc123", "agent/thing", cwd="/tmp")

    assert record["files_changed"] == ["runner/a.py", "runner/b.py"]
    assert record["insertions"] == 15
    assert record["deletions"] == 2
    assert record["conflict_resolutions"] == 0
    assert record["branch_name"] == "agent/thing"
    assert record["merge_date"] == "2026-08-01T10:00:00Z"  # normalised to UTC


def test_binary_files_count_as_changed_but_add_no_lines(fake_git):
    # git reports a binary file as `-\t-\tpath`. Counting it as 0 lines would
    # understate a merge that replaced an image; not counting the file at all
    # would lose it entirely.
    fake_git({"numstat": numstat(("-", "-", "public/logo.png"), ("3", "1", "a.py"))})

    record = mdm.parse_merge_diff("abc", "b")
    assert record["files_changed"] == ["public/logo.png", "a.py"]
    assert record["insertions"] == 3
    assert record["deletions"] == 1


def test_files_are_deduped_and_capped_with_a_more_marker(fake_git):
    rows = [("1", "0", f"f{i}.py") for i in range(60)]
    # -m --first-parent can repeat a path across parents.
    rows.append(("1", "0", "f0.py"))
    fake_git({"numstat": numstat(*rows)})

    files = mdm.parse_merge_diff("abc", "b")["files_changed"]
    assert len(files) == mdm.MAX_TRACKED_FILES + 1
    assert files[-1] == "+10 more"
    assert files[0] == "f0.py"
    assert len(set(files[:-1])) == mdm.MAX_TRACKED_FILES


def test_conflict_markers_are_counted_and_heading_underlines_are_not(fake_git):
    patch = (
        "+<<<<<<< HEAD\n"
        "+mine\n"
        "+=======\n"
        "+theirs\n"
        "+>>>>>>> branch\n"
        "+<<<<<<< HEAD\n"
        "+second block\n"
        "+>>>>>>> branch\n"
        # An rst/markdown heading underline. Not a conflict.
        "+Section Title\n"
        "+=============\n"
    )
    fake_git({"patch": patch})

    assert mdm.parse_merge_diff("abc", "b")["conflict_resolutions"] == 2


# ── 5: git errors ──────────────────────────────────────────────────────────

def test_git_failure_yields_a_well_formed_empty_record(monkeypatch):
    # _safe_run returns "" on any git failure — unknown commit, no git on PATH,
    # timeout. The caller writes memory and must not be wedged by it.
    monkeypatch.setattr(mdm, "_safe_run", lambda cmd, cwd=None: "")

    record = mdm.parse_merge_diff("nope", "agent/x")
    assert record["files_changed"] == []
    assert record["insertions"] == 0
    assert record["deletions"] == 0
    assert record["conflict_resolutions"] == 0
    assert record["branch_name"] == "agent/x"
    # An undated record is indistinguishable from a corrupt one, so it dates itself.
    assert record["merge_date"].endswith("Z")
    datetime.fromisoformat(record["merge_date"].replace("Z", "+00:00"))


def test_garbage_git_output_does_not_raise(monkeypatch):
    # Short lines are dropped (they carry no path we can trust); a well-shaped
    # line with unparseable counts keeps the path and contributes 0, so a
    # partially-garbled numstat still reports which files moved.
    monkeypatch.setattr(
        mdm, "_safe_run",
        lambda cmd, cwd=None: "only-one-column\n\n   \nnot\tnumbers\nx\ty\treal/path.py\n",
    )
    record = mdm.parse_merge_diff("abc", "b")
    assert record["insertions"] == 0
    assert record["deletions"] == 0
    assert record["files_changed"] == ["real/path.py"]


def test_an_unparseable_date_falls_back_rather_than_propagating(monkeypatch):
    monkeypatch.setattr(mdm, "_safe_run", lambda cmd, cwd=None: "not-a-date")
    assert mdm.parse_merge_diff("abc", "b")["merge_date"].endswith("Z")


# ── 6: I/O errors ──────────────────────────────────────────────────────────

def test_retrieval_survives_an_unreadable_memory_file(monkeypatch, tmp_path):
    bad = tmp_path / "merged_diff_memory.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    monkeypatch.setattr(mdm, "MERGED_DIFF_FILE", bad)

    assert mdm.find_merges() == []
    assert mdm.find_merges("anything") == []


def test_write_failure_is_reported_not_swallowed(monkeypatch, tmp_path):
    # A silently-dropped write left the recovery memory looking populated while
    # it was stale, which is worse than an empty one.
    monkeypatch.setattr(mdm, "MEMORY_DIR", tmp_path / "nope")
    monkeypatch.setattr(mdm, "MERGED_DIFF_FILE", tmp_path / "nope" / "m.json")

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(mdm.os, "replace", boom)
    assert mdm._write_memory([{"commit": "a"}]) is False


# ── 7: DB errors ───────────────────────────────────────────────────────────

def test_a_failing_store_does_not_wedge_the_caller(monkeypatch, tmp_path):
    monkeypatch.setattr(mdm, "MERGED_DIFF_FILE", tmp_path / "m.json")

    def unavailable():
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(mdm, "_read_memory", unavailable)

    # find_merges reads the store; a store that raises must surface as an error
    # to the caller of _read_memory, not as a silent empty success elsewhere.
    with pytest.raises(RuntimeError):
        mdm.find_merges()


def test_capture_merge_returns_false_when_the_store_cannot_be_written(monkeypatch, tmp_path):
    monkeypatch.setattr(mdm, "MERGED_DIFF_FILE", tmp_path / "m.json")
    monkeypatch.setattr(mdm, "_read_memory", lambda: [])
    monkeypatch.setattr(mdm, "_safe_run", lambda cmd, cwd=None: "")
    monkeypatch.setattr(mdm, "_write_memory", lambda merges: False)

    assert mdm.capture_merge("abc", "agent/x", cwd=".") is False


# ── 8: retrieval, with and without a keyword ───────────────────────────────

@pytest.fixture
def populated(monkeypatch, tmp_path):
    path = tmp_path / "merged_diff_memory.json"
    merges = [
        {"commit": "1", "branch": "agent/alpha", "message": "add parser", "files_affected": ["runner/p.py"]},
        {"commit": "2", "branch": "agent/beta", "message": "fix gate", "files_affected": ["runner/gate.py"]},
        {"commit": "3", "branch": "agent/gamma", "message": "docs", "files_affected": ["README.md"]},
    ]
    path.write_text(json.dumps({"merges": merges}), encoding="utf-8")
    monkeypatch.setattr(mdm, "MERGED_DIFF_FILE", path)
    return merges


def test_retrieval_without_a_keyword_returns_everything_recent(populated):
    assert [m["commit"] for m in mdm.find_merges()] == ["1", "2", "3"]
    assert [m["commit"] for m in mdm.find_merges(limit=2)] == ["2", "3"]


def test_retrieval_with_a_keyword_matches_branch_message_and_files(populated):
    assert [m["commit"] for m in mdm.find_merges("beta")] == ["2"]
    assert [m["commit"] for m in mdm.find_merges("parser")] == ["1"]
    assert [m["commit"] for m in mdm.find_merges("README")] == ["3"]


def test_keyword_matching_is_case_insensitive(populated):
    assert [m["commit"] for m in mdm.find_merges("ALPHA")] == ["1"]


def test_a_keyword_that_matches_nothing_returns_nothing(populated):
    # Not the full list. A filter that falls back to everything has stopped
    # being a filter, and the caller cannot tell.
    assert mdm.find_merges("zzz-no-such-thing") == []


def test_blank_and_none_keywords_mean_unfiltered(populated):
    for keyword in (None, "", "   "):
        assert len(mdm.find_merges(keyword)) == 3


def test_a_malformed_record_is_skipped_not_fatal(monkeypatch, tmp_path, populated):
    broken = list(populated) + [{"commit": "4", "files_affected": "not-a-list"}]
    path = tmp_path / "merged_diff_memory.json"
    path.write_text(json.dumps({"merges": broken}), encoding="utf-8")
    monkeypatch.setattr(mdm, "MERGED_DIFF_FILE", path)

    assert [m["commit"] for m in mdm.find_merges("alpha")] == ["1"]


def test_non_positive_limits_mean_none(populated):
    assert mdm.find_merges(limit=0) == []
    assert mdm.find_merges("alpha", limit=-1) == []
    # A non-numeric limit falls back to the default rather than raising.
    assert len(mdm.find_merges(limit="oops")) == 3
