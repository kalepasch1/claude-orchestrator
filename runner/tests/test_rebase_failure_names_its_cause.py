"""157 REDOs, 156 of them with no reason at all.

`_rebase_onto_base` reports a failed rebase as a list of conflicting files, captured
from `git diff --diff-filter=U` before it aborts. But a rebase can fail without a single
conflicting line: the branch is checked out in another worktree, the ref does not exist,
the tree is dirty, a hook refuses it. None of those produce unmerged paths, so the file
list comes back empty -- and the caller reports

    REDO (rebase conflict, rebuild on fresh orchestrator/dev (2/4))

naming nothing, then spends a FULL AGENT REBUILD on a task whose content may merge
cleanly.

MEASURED 2026-09-04, one merge-train log window: 157 REDOs, all beethoven, 156 of them
carrying no file list. Git had said why every time, on a stderr this function threw away.
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import merge_train


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=60)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-b", "main")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "T")
    (r / "a.txt").write_text("base\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-m", "seed")
    return str(r)


def test_a_real_content_conflict_still_names_its_files(repo, capsys):
    """The existing contract, unchanged: unmerged paths come back as the detail."""
    _git(repo, "checkout", "-b", "feature")
    (os.path.join(repo, "a.txt")) and open(os.path.join(repo, "a.txt"), "w").write("branch\n")
    _git(repo, "commit", "-am", "branch edit")
    _git(repo, "checkout", "main")
    open(os.path.join(repo, "a.txt"), "w").write("main\n")
    _git(repo, "commit", "-am", "main edit")

    ok, detail = merge_train._rebase_onto_base(repo, "feature", "main")
    assert ok is False
    assert "a.txt" in detail
    assert "not a content conflict" not in capsys.readouterr().out


def test_a_rebase_that_never_started_says_why(repo, capsys):
    """The 156. No unmerged paths, so no file list -- but git had a reason."""
    ok, detail = merge_train._rebase_onto_base(repo, "no-such-branch", "main")
    assert ok is False
    assert detail == ""
    out = capsys.readouterr().out
    assert "not a content conflict" in out, out
    assert "no-such-branch" in out, out
    # The point is the CAUSE, not just the fact of failure.
    assert any(w in out.lower() for w in ("no such", "invalid", "fatal", "does not")), out


def test_a_clean_rebase_says_nothing(repo, capsys):
    _git(repo, "checkout", "-b", "feature")
    open(os.path.join(repo, "b.txt"), "w").write("new\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "branch adds a file")
    _git(repo, "checkout", "main")
    open(os.path.join(repo, "c.txt"), "w").write("other\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "main adds a different file")

    ok, detail = merge_train._rebase_onto_base(repo, "feature", "main")
    assert ok is True and detail == ""
    assert capsys.readouterr().out.strip() == ""


def test_an_already_based_branch_is_untouched(repo, capsys):
    _git(repo, "checkout", "-b", "feature")
    ok, detail = merge_train._rebase_onto_base(repo, "feature", "main")
    assert ok is True and detail == ""
    assert capsys.readouterr().out.strip() == ""
