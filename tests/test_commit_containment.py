"""PROPRIETARY -- Apparently Inc. Trade Secret. Protected under DTSA (18 U.S.C. 1836).

Offline proof for the per-task commit-containment evidence producer
(differential_gate.verify_commit_contains_task). Builds a throwaway git repo in
a tmp dir; no network, no live control plane. Deterministic.
"""
import os
import subprocess

from runner.differential_gate import verify_commit_contains_task, verify_and_record


def _git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True)


def _rev(repo, ref="HEAD"):
    return subprocess.run(
        ["git", "-C", repo, "rev-parse", ref], capture_output=True, text=True, check=True
    ).stdout.strip()


def _write(repo, rel, content):
    full = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as fh:
        fh.write(content)


def _commit(repo, msg):
    _git(repo, "add", "-A")
    _git(repo, "commit", "--no-verify", "-m", msg)
    return _rev(repo)


def _fixture(tmp_path):
    repo = str(tmp_path / "repo")
    os.makedirs(repo)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.test")
    _git(repo, "config", "user.name", "t")
    _git(repo, "checkout", "-q", "-b", "master")
    _write(repo, "README.md", "base\n")
    base = _commit(repo, "base")
    # artifact branch: one commit on the task's target file, one on an unrelated file
    _git(repo, "checkout", "-q", "-b", "orchestrator/dev")
    _write(repo, "server/task_target.ts", "export const x = 1\n")
    target_sha = _commit(repo, "feat: the task's real change")
    _write(repo, "unrelated/other.ts", "export const y = 2\n")
    unrelated_sha = _commit(repo, "chore: unrelated change")
    # a foreign commit that touches the SAME target path but is NOT on the branch
    _git(repo, "checkout", "-q", "-b", "foreign", base)
    _write(repo, "server/task_target.ts", "export const z = 3\n")
    foreign_sha = _commit(repo, "foreign edit to target path")
    _git(repo, "checkout", "-q", "orchestrator/dev")
    return repo, base, target_sha, unrelated_sha, foreign_sha


def test_a_commit_that_touches_the_task_path_contains(tmp_path):
    repo, _base, target_sha, _u, _f = _fixture(tmp_path)
    ev = verify_commit_contains_task(
        repo, "task-1", target_sha, "orchestrator/dev",
        declared_paths=["server/task_target.ts"],
    )
    assert ev.evaluable is True
    assert ev.contains_task_paths is True
    assert "server/task_target.ts" in ev.changed_paths


def test_b_borrowed_sha_touching_only_unrelated_files_is_false(tmp_path):
    repo, _base, _t, unrelated_sha, _f = _fixture(tmp_path)
    ev = verify_commit_contains_task(
        repo, "task-1", unrelated_sha, "orchestrator/dev",
        declared_paths=["server/task_target.ts"],
    )
    assert ev.evaluable is True
    assert ev.contains_task_paths is False


def test_c_sha_not_ancestor_of_artifact_branch_is_false(tmp_path):
    repo, _base, _t, _u, foreign_sha = _fixture(tmp_path)
    ev = verify_commit_contains_task(
        repo, "task-1", foreign_sha, "orchestrator/dev",
        declared_paths=["server/task_target.ts"],
    )
    assert ev.evaluable is True
    assert ev.contains_task_paths is False
    assert "ancestor" in ev.reason


def test_d_no_declared_paths_fails_closed_and_writes_nothing(tmp_path):
    repo, _base, target_sha, _u, _f = _fixture(tmp_path)
    ev = verify_commit_contains_task(
        repo, "task-1", target_sha, "orchestrator/dev",
        declared_paths=None,  # and no base -> cannot derive a path set
    )
    assert ev.evaluable is False
    assert ev.contains_task_paths is False
    store = {}
    def _write_row(e):
        store[(e.task_id, e.artifact_commit)] = e
        return e
    assert verify_and_record(ev, _write_row) is None
    assert len(store) == 0  # fail-closed: nothing written


def test_e_path_set_derived_from_branch_diff_when_paths_undeclared(tmp_path):
    repo, base, target_sha, _u, _f = _fixture(tmp_path)
    ev = verify_commit_contains_task(
        repo, "task-1", target_sha, "orchestrator/dev",
        base=base,  # derive task path-set from base...branch diff
    )
    assert ev.evaluable is True
    assert ev.contains_task_paths is True
    assert "server/task_target.ts" in ev.task_paths


def test_f_exactly_one_evidence_row_per_task_sha(tmp_path):
    repo, _base, target_sha, _u, _f = _fixture(tmp_path)
    ev = verify_commit_contains_task(
        repo, "task-1", target_sha, "orchestrator/dev",
        declared_paths=["server/task_target.ts"],
    )
    store = {}
    def _upsert(e):
        store[(e.task_id, e.artifact_commit)] = e  # unique(task_id, artifact_commit)
        return e
    verify_and_record(ev, _upsert)
    verify_and_record(ev, _upsert)  # second write of same (task,sha)
    assert len(store) == 1
