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


# ── the dirty index that stopped a project merging ───────────────────────────

def _as_integration_worktree(tmp_path):
    """Same shape integration_runtime creates: <home>/.runtime/integration-worktrees/<k>."""
    d = tmp_path / ".runtime" / "integration-worktrees" / "abc123"
    d.mkdir(parents=True)
    return str(d)


def _seed(path):
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "T")
    open(os.path.join(path, "a.txt"), "w").write("base\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-m", "seed")


def test_a_staged_file_no_longer_blocks_the_rebase(tmp_path, capsys):
    """246 staged `.recovery-intent-*.txt` markers, 304 REDOs, zero merges."""
    wt = _as_integration_worktree(tmp_path)
    _seed(wt)
    _git(wt, "checkout", "-b", "feature")
    open(os.path.join(wt, "b.txt"), "w").write("work\n")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-m", "real work")
    _git(wt, "checkout", "main")
    open(os.path.join(wt, "c.txt"), "w").write("moved on\n")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-m", "base advances")

    # the poison: a marker staged and never committed
    open(os.path.join(wt, ".recovery-intent-some-slug.txt"), "w").write("recovery-intent\n")
    _git(wt, "add", "-f", ".recovery-intent-some-slug.txt")
    assert _git(wt, "diff", "--cached", "--name-only").stdout.strip()

    ok, detail = merge_train._rebase_onto_base(wt, "feature", "main")
    assert ok is True, f"rebase still blocked: {detail!r}"
    assert "cleared 1 staged path" in capsys.readouterr().out


def test_a_canonical_checkout_is_never_reset(tmp_path, capsys):
    """It may be someone's editor state. Not this train's business."""
    repo = str(tmp_path / "someones-checkout")
    os.makedirs(repo)
    _seed(repo)
    open(os.path.join(repo, "wip.txt"), "w").write("half-written\n")
    _git(repo, "add", "-A")

    assert merge_train._clear_integration_index(repo) is False
    assert _git(repo, "diff", "--cached", "--name-only").stdout.strip() == "wip.txt"


def test_a_clean_integration_worktree_is_left_alone(tmp_path, capsys):
    wt = _as_integration_worktree(tmp_path)
    _seed(wt)
    assert merge_train._clear_integration_index(wt) is False
    assert capsys.readouterr().out.strip() == ""


def test_untracked_files_survive(tmp_path):
    """node_modules and .nuxt are linked in on purpose; git rebase does not mind them."""
    wt = _as_integration_worktree(tmp_path)
    _seed(wt)
    open(os.path.join(wt, "staged.txt"), "w").write("x\n")
    _git(wt, "add", "-A")
    os.makedirs(os.path.join(wt, "node_modules"))
    open(os.path.join(wt, "node_modules", "keep.js"), "w").write("//\n")

    assert merge_train._clear_integration_index(wt) is True
    assert os.path.exists(os.path.join(wt, "node_modules", "keep.js"))


def test_a_rebase_left_in_progress_is_aborted(tmp_path, capsys):
    """A pass killed mid-rebase poisons its worktree for every later card.

    Observed live on beethoven's slot immediately after the index clearing above went
    in: 75 further refusals, this time
        fatal: It seems that there is already a rebase-merge directory ...
    Nothing recovers from that on its own, and `reset HEAD` cannot: HEAD is itself
    mid-rebase.
    """
    wt = _as_integration_worktree(tmp_path)
    _seed(wt)
    _git(wt, "checkout", "-b", "feature")
    open(os.path.join(wt, "a.txt"), "w").write("branch\n")
    _git(wt, "commit", "-am", "branch edit")
    _git(wt, "checkout", "main")
    open(os.path.join(wt, "a.txt"), "w").write("main\n")
    _git(wt, "commit", "-am", "main edit")

    # leave a rebase in progress, exactly as a killed pass does
    _git(wt, "rebase", "main", "feature")
    gitdir = _git(wt, "rev-parse", "--absolute-git-dir").stdout.strip()
    assert os.path.isdir(os.path.join(gitdir, "rebase-merge")), "fixture did not stick"

    merge_train._clear_integration_index(wt)
    assert not os.path.isdir(os.path.join(gitdir, "rebase-merge"))
    assert "cleared a rebase left in progress" in capsys.readouterr().out
