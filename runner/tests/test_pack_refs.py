"""Nothing in this fleet ever packed a repo's refs, and one repo had 7,463 loose ones.

Every git command that enumerates refs walks the loose ref tree file by file, and the
merge train runs several such commands per candidate. The count only ever grows: each
finished task leaves an `agent/<slug>` branch behind and nothing removes it.

Measured on ~/Documents/smarter, 2026-09-01:

    loose refs        7,463  ->  3
    git for-each-ref     15s ->  6s
    refs resolvable  20,614  ->  20,614   (nothing lost; they moved to .git/packed-refs)

`grep -rn pack-refs runner/*.py` found no call site anywhere in the repository, and
`git gc --auto` never runs because the fleet never invokes gc.

Packing is not pruning, which is the distinction the tests below are mostly about: no
ref is deleted, every one still resolves, and a repo below the threshold is left alone.
"""
import os
import subprocess

import pytest

import worktree_gc as wg


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                          timeout=60)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "proj"
    r.mkdir()
    _git(str(r), "init", "-q", "-b", "main")
    _git(str(r), "config", "user.email", "t@example.com")
    _git(str(r), "config", "user.name", "t")
    (r / "f.txt").write_text("x\n")
    _git(str(r), "add", "-A")
    _git(str(r), "commit", "-q", "-m", "base")
    return str(r)


def _make_branches(repo, n, prefix="agent/task-"):
    for i in range(n):
        _git(repo, "branch", f"{prefix}{i}")


def test_a_repo_with_many_loose_refs_is_packed(repo):
    _make_branches(repo, 40)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(wg, "PACK_REFS_MIN_LOOSE", 10)
        before, after = wg.pack_refs(repo)
    assert before >= 40
    assert after < before, "refs were not packed"


def test_packing_loses_nothing(repo):
    """The whole safety argument. Packed refs must resolve exactly as before."""
    _make_branches(repo, 40)
    listed_before = _git(repo, "for-each-ref", "--format=%(refname) %(objectname)").stdout
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(wg, "PACK_REFS_MIN_LOOSE", 10)
        wg.pack_refs(repo)
    listed_after = _git(repo, "for-each-ref", "--format=%(refname) %(objectname)").stdout
    assert listed_before == listed_after, "a ref changed or disappeared when packing"
    assert listed_after.count("\n") >= 41


def test_a_named_branch_is_still_checkoutable_after_packing(repo):
    """for-each-ref agreeing is not quite the same as git being able to use them."""
    _make_branches(repo, 40)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(wg, "PACK_REFS_MIN_LOOSE", 10)
        wg.pack_refs(repo)
    assert _git(repo, "rev-parse", "--verify", "agent/task-7").returncode == 0
    assert _git(repo, "checkout", "-q", "agent/task-7").returncode == 0


def test_a_repo_below_the_threshold_is_left_alone(repo):
    """Packing costs a subprocess; a handful of refs is not worth one."""
    _make_branches(repo, 3)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(wg, "PACK_REFS_MIN_LOOSE", 500)
        before, after = wg.pack_refs(repo)
    assert before == after


def test_the_threshold_of_zero_disables_it(repo):
    _make_branches(repo, 40)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(wg, "PACK_REFS_MIN_LOOSE", 0)
        assert wg.pack_refs(repo) == (0, 0)


def test_dry_run_does_not_pack(repo):
    _make_branches(repo, 40)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(wg, "PACK_REFS_MIN_LOOSE", 10)
        before, after = wg.pack_refs(repo, dry_run=True)
    assert before == after
    assert wg._loose_ref_count(repo) >= 40, "dry_run packed anyway"


@pytest.mark.parametrize("path", ["", None, "/nonexistent/nowhere"])
def test_a_missing_repo_is_not_an_error(path):
    """An optimisation must never be the reason a sweep stops."""
    assert wg.pack_refs(path) == (0, 0)


def test_a_directory_that_is_not_a_git_repo_is_ignored(tmp_path):
    assert wg.pack_refs(str(tmp_path)) == (0, 0)


def test_a_failing_git_leaves_the_count_unchanged(repo, monkeypatch):
    _make_branches(repo, 40)

    class _Fail:
        returncode = 128
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(wg, "PACK_REFS_MIN_LOOSE", 10)
    monkeypatch.setattr(wg, "_run_git", lambda *a, **k: _Fail())
    before, after = wg.pack_refs(repo)
    assert before == after


def test_the_loose_count_is_bounded(repo):
    """A repo with a pathological ref tree must not make the counter the slow part."""
    _make_branches(repo, 30)
    assert wg._loose_ref_count(repo, cap=5) >= 5


def test_the_sweep_calls_pack_refs():
    """Structural: a helper nothing schedules does nothing.

    This repo has had exactly that bug before — generator_feedback.should_generate()
    existed with zero callers for weeks, and pipeline_metrics.get_health() lost its only
    caller in a merge and kept collecting samples nobody read.
    """
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "worktree_gc.py")
    with open(src, encoding="utf-8") as fh:
        body = fh.read()
    run_body = body[body.index("def run(dry_run=False"):]
    assert "pack_refs(repo" in run_body, (
        "worktree_gc.run no longer packs refs; loose refs will accumulate unbounded "
        "again and every ref-enumerating git command pays for them"
    )
