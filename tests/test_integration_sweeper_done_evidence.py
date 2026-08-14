"""Regression: integration_sweeper's DONE closure must carry artifact evidence.

The crash loop (15 tracebacks, 94% of this job's failures) was a PATCH of
`{"state": "DONE"}` with no artifact_commit. The `enforce_evidence_on_closure`
trigger rejects that with HTTP 400 and the raw HTTPError escaped sweep(), so one
bad row aborted the entire sweep.
"""
import os
import subprocess
import sys
import types

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)


def _load_sweeper():
    # db/merge_train pull network config at import time in some environments; the
    # functions under test only touch db.update, which every test stubs.
    import integration_sweeper
    return integration_sweeper


def _git_repo(tmp_path, branch="agent/demo-slug"):
    repo = str(tmp_path / "repo")
    os.makedirs(repo)
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, env=env)
    open(os.path.join(repo, "f.txt"), "w").write("x")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "branch", branch], cwd=repo, check=True, env=env)
    return repo


def test_branch_tip_sha_resolves_and_fails_soft(tmp_path):
    s = _load_sweeper()
    repo = _git_repo(tmp_path)
    sha = s._branch_tip_sha(repo, "agent/demo-slug")
    assert len(sha) == 40

    # Unresolvable inputs return "" instead of raising.
    assert s._branch_tip_sha(repo, "agent/does-not-exist") == ""
    assert s._branch_tip_sha("/nonexistent/repo/path", "agent/demo-slug") == ""
    assert s._branch_tip_sha("", "agent/demo-slug") == ""


def test_done_closure_records_artifact_commit(tmp_path, monkeypatch):
    s = _load_sweeper()
    repo = _git_repo(tmp_path)
    calls = []
    monkeypatch.setattr(s.db, "update",
                        lambda table, where, patch: calls.append((table, where, patch)))

    assert s._close_done_with_evidence({"id": "t1"}, repo, "demo-slug") is True
    assert len(calls) == 1
    patch = calls[0][2]
    assert patch["state"] == "DONE"
    assert len(patch["artifact_commit"]) == 40


def test_done_closure_falls_back_to_justified_note_when_no_sha(tmp_path, monkeypatch):
    s = _load_sweeper()
    calls = []
    monkeypatch.setattr(s.db, "update",
                        lambda table, where, patch: calls.append((table, where, patch)))

    assert s._close_done_with_evidence({"id": "t1"}, "/nonexistent/repo", "demo-slug") is True
    patch = calls[-1][2]
    assert patch["state"] == "DONE"
    assert "artifact_commit" not in patch
    # The escape hatch the DB trigger documents, so the closure is honest, not silent.
    assert "NO-ARTIFACT-JUSTIFIED:" in patch["note"]


def test_rejected_artifact_commit_retries_then_never_raises(tmp_path, monkeypatch):
    s = _load_sweeper()
    repo = _git_repo(tmp_path)
    seen = []

    def flaky_update(table, where, patch):
        seen.append(patch)
        if "artifact_commit" in patch:
            raise RuntimeError("HTTP Error 400: Bad Request")

    monkeypatch.setattr(s.db, "update", flaky_update)
    assert s._close_done_with_evidence({"id": "t1"}, repo, "demo-slug") is True
    assert len(seen) == 2
    assert "NO-ARTIFACT-JUSTIFIED:" in seen[1]["note"]


def test_total_db_failure_is_swallowed_not_propagated(tmp_path, monkeypatch):
    s = _load_sweeper()

    def always_400(table, where, patch):
        raise RuntimeError("HTTP Error 400: Bad Request")

    monkeypatch.setattr(s.db, "update", always_400)
    # The whole point: one unwritable row must not abort the sweep.
    assert s._close_done_with_evidence({"id": "t1"}, "/nonexistent", "demo-slug") is False
