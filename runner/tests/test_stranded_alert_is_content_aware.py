"""A stranding alert that was wrong every six minutes for a fortnight.

`preserve-ec580138-fleet-work` (tip ec5801387c, committed 2026-08-18) fired

    STRANDED-COMMIT ALERT: branch preserve-ec580138-fleet-work (ec5801387c) holds 11
    runner/web files not in master — sample ['runner/done_to_merged.py',
    'runner/merge_train.py', ...]

every ~6 minutes for over two weeks. Checked line by line on 2026-09-04, ten of those
eleven files were ALREADY on master in full:

    runner/merge_train_report.py             162 added lines,  0 absent from master
    runner/tools/reconcile_orch_rescue.py    186 added,        0 absent
    runner/tests/test_reconcile_orch_rescue.py 115 added,      0 absent
    runner/done_to_merged.py                 172 added,        3 absent
    runner/stderr_digest.py                   67 added,        2 absent

The work landed by another route -- a rebuild, a redo, a different branch -- which is
the normal way this fleet lands anything. `stranded_commit_rescue` compared by PATH, so
a fully-merged branch looked exactly like one about to be forgotten.

That is worse than no alert at all. An alarm wrong every six minutes for a fortnight is
one a reader learns to skip, and the next REAL stranding scrolls past inside it.
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sentinel


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=60)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A base branch and a side branch, so the two cases can be built for real."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-b", "master")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "T")
    (r / "runner").mkdir()
    (r / "runner" / "seed.py").write_text("# seed\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-m", "seed")
    monkeypatch.setattr(sentinel, "git",
                        lambda *a, **k: _git(r, *a))
    return r


#: Long enough not to be filtered out as incidental punctuation.
LINES = [f"the_branch_added_this_substantive_line_number_{i} = {i}" for i in range(20)]


def test_work_that_already_reached_master_is_not_reported(repo):
    """The ec580138 case: same content, arrived by a different route."""
    _git(repo, "checkout", "-b", "side")
    (repo / "runner" / "landed.py").write_text("\n".join(LINES) + "\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "side work")
    side = _git(repo, "rev-parse", "HEAD").stdout.strip()

    # master gets the same content independently -- a redo, not a merge.
    _git(repo, "checkout", "master")
    (repo / "runner" / "landed.py").write_text(
        "# rebuilt by another agent\n" + "\n".join(LINES) + "\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "master rebuild")

    mb = _git(repo, "merge-base", "master", side).stdout.strip()
    assert not sentinel._is_really_absent_from("master", mb, side, "runner/landed.py")


def test_work_that_never_reached_master_is_still_reported(repo):
    """The alert must keep doing its job; this is the failure it exists for."""
    _git(repo, "checkout", "-b", "side2")
    (repo / "runner" / "lost.py").write_text("\n".join(LINES) + "\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "side work nobody merged")
    side = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "checkout", "master")

    mb = _git(repo, "merge-base", "master", side).stdout.strip()
    assert sentinel._is_really_absent_from("master", mb, side, "runner/lost.py")


def test_a_partial_landing_is_reported(repo):
    """Half the work arriving is not the work arriving."""
    _git(repo, "checkout", "-b", "side3")
    (repo / "runner" / "half.py").write_text("\n".join(LINES) + "\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "side work")
    side = _git(repo, "rev-parse", "HEAD").stdout.strip()

    _git(repo, "checkout", "master")
    (repo / "runner" / "half.py").write_text("\n".join(LINES[:5]) + "\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "only some of it")

    mb = _git(repo, "merge-base", "master", side).stdout.strip()
    assert sentinel._is_really_absent_from("master", mb, side, "runner/half.py")


def test_short_lines_alone_never_count_as_landed_work(repo):
    """Braces, imports and blank-ish lines match by accident in any file."""
    _git(repo, "checkout", "-b", "side4")
    (repo / "runner" / "tiny.py").write_text("x = 1\ny = 2\n)\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "trivial")
    side = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "checkout", "master")

    mb = _git(repo, "merge-base", "master", side).stdout.strip()
    # Nothing substantive was added, so there is nothing to call stranded.
    assert not sentinel._is_really_absent_from("master", mb, side, "runner/tiny.py")
