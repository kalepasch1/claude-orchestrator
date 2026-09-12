"""The read side of merged-diff memory.

Memos were written and indexed but never read back, so harvested rules and
frameworks were write-only. These tests pin the parse contract against the
exact format `merged_diff_memory._save_to_memory` emits, and pin the
fail-soft behaviour: a malformed memo, an unreadable file, or a missing
directory must degrade to fewer results, never to an exception.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))
import merged_diff_scan as mds


MEMO = """---
name: merged_diff_20260801
description: Patterns and conventions from master merges on 2026-08-01
metadata:
  type: project
  date: 2026-08-01
  commits: abc123, def456
---

## Learned Conventions & Do/Avoid Rules
- Use fail-soft error handling
- Prefer module-level singletons

## Frameworks in Use
pytest, asyncio

See also: [[project_orchestrator]]
"""


@pytest.fixture()
def projects(tmp_path, monkeypatch):
    """Point the scanner at a throwaway projects root."""
    monkeypatch.setattr(mds, "PROJECTS_ROOT", tmp_path)
    return tmp_path


def _write_memo(projects, project_id, filename, body=MEMO):
    d = projects / project_id / "memory"
    d.mkdir(parents=True, exist_ok=True)
    f = d / filename
    f.write_text(body, encoding="utf-8")
    return f


def test_parses_the_writer_format(projects):
    f = _write_memo(projects, "proj-a", "merged_diff_20260801.md")
    memo = mds.parse_memo(f)
    assert memo["name"] == "merged_diff_20260801"
    assert memo["date"] == "2026-08-01"
    assert memo["commits"] == ["abc123", "def456"]
    assert memo["rules"] == [
        "Use fail-soft error handling",
        "Prefer module-level singletons",
    ]
    assert memo["frameworks"] == ["pytest", "asyncio"]


def test_scan_project_finds_memos_and_tags_project_id(projects):
    _write_memo(projects, "proj-a", "merged_diff_20260801.md")
    memos = mds.scan_project("proj-a")
    assert len(memos) == 1
    assert memos[0]["project_id"] == "proj-a"


def test_scan_project_only_matches_the_memo_glob(projects):
    _write_memo(projects, "proj-a", "merged_diff_20260801.md")
    _write_memo(projects, "proj-a", "MEMORY.md")
    _write_memo(projects, "proj-a", "merged_learning_20260801.md")
    assert [m["path"].split("/")[-1] for m in mds.scan_project("proj-a")] == [
        "merged_diff_20260801.md"
    ]


def test_scan_project_returns_newest_filename_first(projects):
    _write_memo(projects, "proj-a", "merged_diff_20260801.md")
    _write_memo(projects, "proj-a", "merged_diff_20260803.md")
    _write_memo(projects, "proj-a", "merged_diff_20260802.md")
    names = [m["path"].split("/")[-1] for m in mds.scan_project("proj-a")]
    assert names == [
        "merged_diff_20260803.md",
        "merged_diff_20260802.md",
        "merged_diff_20260801.md",
    ]


# --- fail-soft ------------------------------------------------------------

def test_missing_project_returns_empty(projects):
    assert mds.scan_project("no-such-project") == []


def test_empty_project_id_returns_empty(projects):
    assert mds.scan_project("") == []
    assert mds.scan_project("   ") == []


def test_project_without_memory_dir_returns_empty(projects):
    (projects / "proj-a").mkdir(parents=True)
    assert mds.scan_project("proj-a") == []


def test_missing_projects_root_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(mds, "PROJECTS_ROOT", tmp_path / "gone")
    assert mds.list_project_ids() == []
    assert mds.scan_all() == []


def test_unreadable_memo_is_skipped_not_raised(projects, caplog):
    _write_memo(projects, "proj-a", "merged_diff_20260801.md")
    bad = projects / "proj-a" / "memory" / "merged_diff_broken.md"
    bad.mkdir()  # a directory where a file is expected
    memos = mds.scan_project("proj-a")
    assert len(memos) == 1


def test_memo_without_frontmatter_still_parses(projects):
    f = _write_memo(projects, "proj-a", "merged_diff_x.md", body="no frontmatter here\n")
    memo = mds.parse_memo(f)
    assert memo is not None
    assert memo["rules"] == []
    assert memo["commits"] == []


def test_placeholder_rule_line_is_not_a_rule(projects):
    body = MEMO.replace("- Use fail-soft error handling\n- Prefer module-level singletons",
                        "(no new rules extracted today)")
    f = _write_memo(projects, "proj-a", "merged_diff_x.md", body=body)
    assert mds.parse_memo(f)["rules"] == []


def test_frameworks_none_is_not_a_framework(projects):
    body = MEMO.replace("pytest, asyncio", "none")
    f = _write_memo(projects, "proj-a", "merged_diff_x.md", body=body)
    assert mds.parse_memo(f)["frameworks"] == []


# --- aggregation ----------------------------------------------------------

def test_scan_all_spans_projects(projects):
    _write_memo(projects, "proj-a", "merged_diff_20260801.md")
    _write_memo(projects, "proj-b", "merged_diff_20260801.md")
    assert {m["project_id"] for m in mds.scan_all()} == {"proj-a", "proj-b"}


def test_scan_all_accepts_an_explicit_project_list(projects):
    _write_memo(projects, "proj-a", "merged_diff_20260801.md")
    _write_memo(projects, "proj-b", "merged_diff_20260801.md")
    assert {m["project_id"] for m in mds.scan_all(["proj-a"])} == {"proj-a"}


def test_collect_rules_dedupes_across_memos(projects):
    _write_memo(projects, "proj-a", "merged_diff_20260801.md")
    _write_memo(projects, "proj-a", "merged_diff_20260802.md")
    assert mds.collect_rules("proj-a") == [
        "Prefer module-level singletons",
        "Use fail-soft error handling",
    ]


def test_collect_frameworks_dedupes_and_sorts(projects):
    _write_memo(projects, "proj-a", "merged_diff_20260801.md")
    _write_memo(projects, "proj-b", "merged_diff_20260801.md")
    assert mds.collect_frameworks() == ["asyncio", "pytest"]


def test_stats_counts_distinct_values(projects):
    _write_memo(projects, "proj-a", "merged_diff_20260801.md")
    _write_memo(projects, "proj-a", "merged_diff_20260802.md")
    assert mds.stats("proj-a") == {
        "memos": 2, "rules": 2, "frameworks": 2, "commits": 2,
    }


def test_stats_on_empty_root_is_all_zero(projects):
    assert mds.stats() == {"memos": 0, "rules": 0, "frameworks": 0, "commits": 0}


def test_memory_dir_layout_matches_the_spec(projects):
    assert mds.memory_dir("proj-a") == projects / "proj-a" / "memory"
