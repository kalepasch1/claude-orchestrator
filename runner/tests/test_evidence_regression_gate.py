#!/usr/bin/env python3
"""The delivery-time regression gate for recovered evidence.

Classification and delivery safety are different questions and were being answered by
the same check. `git merge-tree` proves a three-way merge of an evidence ref onto the
base is conflict-free; it says nothing about checking that ref's tree out over the base,
which is what a recovery executor does when it copies files out of an evidence source.

When the ref is far behind, those two operations differ by the entire diff: the branch
lands looking like a feature and is in fact a partial revert. These tests pin the gate
that distinguishes them.
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import local_evidence_reconciler as ler  # noqa: E402


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          timeout=60)


def _write(root, rel, text):
    full = os.path.join(root, rel)
    os.makedirs(os.path.dirname(full) or root, exist_ok=True)
    with open(full, "w") as fh:
        fh.write(text)


def _commit(repo, msg):
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg)


def _padding(n):
    """Filler so the branch's hunk and the base's hunk are not adjacent.

    Without it git sees one overlapping edit and reports a conflict, which would test
    the conflict path instead of the one that matters: a ref that merges *cleanly* and
    is still unsafe to check out.
    """
    return "".join(f"# pad {i}\n" for i in range(n))


@pytest.fixture()
def stale_repo(tmp_path):
    """A repo whose `master` has grown well past a stale evidence branch.

    Shaped like the incident. `stale` edits the top of helpers.py and adds a file of its
    own; `master` later appends to the bottom of helpers.py and adds an unrelated module.
    The two edits merge cleanly, and `stale`'s tree is nonetheless missing everything
    master added.
    """
    repo = str(tmp_path / "repo")
    os.makedirs(repo)
    _git(repo, "init", "-q", "-b", "master")

    body = "def original():\n    return 1\n" + _padding(40)
    _write(repo, "helpers.py", body)
    _commit(repo, "base")

    _git(repo, "checkout", "-q", "-b", "stale")
    _write(repo, "helpers.py", "def from_evidence():\n    return 'value'\n\n\n" + body)
    # A second path master never touches, so the ref cannot be written off as superseded.
    _write(repo, "evidence_only.py", "RECOVERED = True\n")
    _commit(repo, "evidence work")

    _git(repo, "checkout", "-q", "master")
    _write(repo, "helpers.py", body + "\n"
           + "".join(f"def keep_me_{i}():\n    return {i}\n\n\n" for i in range(12)))
    _commit(repo, "master moves on")
    _write(repo, "unrelated.py", "VALUE = 1\n")
    _commit(repo, "more master")

    return repo


def test_stale_tree_that_deletes_base_code_is_not_safe(stale_repo):
    """The exact shape of the incident: behind + net deletions -> refuse."""
    report = ler.regression_report(stale_repo, "stale", "master")

    assert report["behind"] == 2
    assert report["removed_lines"] > 0
    assert "helpers.py" in report["removed_files"]
    assert report["safe"] is False
    assert "rebase" in report["detail"]


def test_merge_tree_still_says_the_same_ref_merges_cleanly(stale_repo):
    """Guards the premise: the gate is needed precisely because the merge check passes.

    If this ever starts failing, the two checks have converged and the gate is
    redundant — but until then, a clean merge is not evidence of a safe delivery.
    """
    clean, _detail = ler._applies_cleanly(stale_repo, "stale", "master")
    assert clean is True


def test_branch_rebased_onto_current_base_is_safe(stale_repo):
    """The remedy the gate names actually clears the gate."""
    _git(stale_repo, "checkout", "-q", "-b", "recovered", "stale")
    rebase = _git(stale_repo, "-c", "user.name=t", "-c", "user.email=t@t",
                  "rebase", "master")
    assert rebase.returncode == 0, rebase.stderr

    report = ler.regression_report(stale_repo, "recovered", "master")
    assert report["behind"] == 0
    assert report["removed_lines"] == 0
    assert report["safe"] is True


def test_unresolvable_ref_is_unsafe_not_silently_clean(stale_repo):
    """A missing branch must never read as 'nothing removed, ship it'."""
    report = ler.regression_report(stale_repo, "agent/never-pushed", "master")
    assert report["safe"] is False
    assert "not resolvable" in report["detail"]


def test_classify_marks_a_stale_recoverable_ref_rebase_only(stale_repo):
    """The warning has to reach the ledger, not just an ad-hoc caller.

    A RECOVERABLE_VALUE record that does not say *how* to apply it is how the tree got
    checked out verbatim in the first place.
    """
    ctx = ler.build_context(stale_repo, base="master")
    record = ler.classify(stale_repo, {"kind": "branch", "name": "stale",
                                       "ref": "stale"}, ctx)

    assert record["classification"] == "RECOVERABLE_VALUE"
    assert record["apply_mode"] == "rebase"
    assert record["behind"] == 2
    assert record["would_remove_lines"] > 0
    assert "WARNING" in record["disposition"]
    assert "rebase" in record["disposition"]


def test_classify_leaves_the_record_shape_intact_for_every_bucket(stale_repo):
    """New keys are additive: every record still carries the original fields."""
    ctx = ler.build_context(stale_repo, base="master")
    for item in ({"kind": "branch", "name": "stale", "ref": "stale"},
                 {"kind": "branch", "name": "gone", "ref": "refs/heads/gone"}):
        record = ler.classify(stale_repo, item, ctx)
        for key in ("source", "kind", "name", "slug", "classification", "disposition",
                    "unique_commits", "paths", "task", "branch", "commit", "detail",
                    "behind", "would_remove_lines", "would_remove_files", "apply_mode"):
            assert key in record, f"{key} missing for {item['name']}"


def test_regression_report_is_read_only(stale_repo):
    """Same invariant as the reconciler: auditing must not move anything."""
    before_head = _git(stale_repo, "rev-parse", "HEAD").stdout.strip()
    before_branch = _git(stale_repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    before_status = _git(stale_repo, "status", "--porcelain").stdout

    ler.regression_report(stale_repo, "stale", "master")

    assert _git(stale_repo, "rev-parse", "HEAD").stdout.strip() == before_head
    assert _git(stale_repo, "rev-parse", "--abbrev-ref",
                "HEAD").stdout.strip() == before_branch
    assert _git(stale_repo, "status", "--porcelain").stdout == before_status
