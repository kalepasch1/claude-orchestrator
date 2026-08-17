"""Regression: work landed on the LOCAL staging branch must not read as "branch lost".

THE DEFECT (observed 2026-08-12, diagnosed 2026-08-17)
------------------------------------------------------
`_integration_targets()` probed only `origin/<target>`. The dev->prod freeze is
deliberate: auto-sync.yml fast-forwards master on any push to orchestrator/dev, so
orchestrator/dev is landed LOCALLY and not pushed until an operator promotes. That
makes `origin/orchestrator/dev` lag by every commit landed since the last promotion,
and the ancestry test therefore reported genuinely integrated work as not integrated.

The sweeper's response to "not integrated + recovery exhausted" is
    state=QUARANTINED, "branch lost and recovery exhausted"
and that is TERMINAL -- sweep_passed() re-selects only DONE/BLOCKED/RUNNING, so a
quarantined row is never looked at again even after the branch IS pushed. Three
verified landings (aab8797f, 34a0ad90, b3d04dcf) were destroyed this way.

This is the same failure class as the vacuous typecheck gate: a control that reports
a clean/negative result while having verified nothing.
"""
import os
import subprocess
import sys

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, env=ENV,
                          capture_output=True, text=True)


def _frozen_fleet(tmp_path):
    """A repo shaped exactly like apparently under the freeze.

    origin/orchestrator/dev is BEHIND local orchestrator/dev, and the agent branch has
    been merged into the local staging branch only -- never pushed.
    """
    origin = str(tmp_path / "origin.git")
    repo = str(tmp_path / "repo")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "master", origin], check=True, env=ENV)
    os.makedirs(repo)
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "remote", "add", "origin", origin)
    open(os.path.join(repo, "f.txt"), "w").write("base")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    _git(repo, "branch", "orchestrator/dev")
    # The last operator-triggered promotion: origin gets the staging branch as it was.
    _git(repo, "push", "-q", "origin", "master", "orchestrator/dev")

    # Now an agent lands work and it is merged into the LOCAL staging branch only.
    _git(repo, "checkout", "-q", "-b", "agent/shadow-demo")
    open(os.path.join(repo, "shadow.txt"), "w").write("landed")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "feat(shadow): landed but not promoted")
    _git(repo, "checkout", "-q", "orchestrator/dev")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge shadow", "agent/shadow-demo")
    _git(repo, "fetch", "-q", "origin")
    return repo


def _refs_containing(repo, sha):
    out = []
    for ref in ("origin/orchestrator/dev", "refs/heads/orchestrator/dev"):
        if subprocess.run(["git", "rev-parse", "--verify", "--quiet", ref],
                          cwd=repo, capture_output=True).returncode != 0:
            continue
        if subprocess.run(["git", "merge-base", "--is-ancestor", sha, ref],
                          cwd=repo, capture_output=True).returncode == 0:
            out.append(ref)
    return out


def test_the_gate_can_still_fail(tmp_path, monkeypatch):
    """Non-vacuity: origin genuinely does NOT contain the work, so the old
    origin-only implementation really would have reported 'not integrated'."""
    monkeypatch.setenv("ORCH_STAGING_BRANCH", "orchestrator/dev")
    repo = _frozen_fleet(tmp_path)
    tip = _git(repo, "rev-parse", "agent/shadow-demo").stdout.strip()

    containing = _refs_containing(repo, tip)
    assert "origin/orchestrator/dev" not in containing, (
        "fixture is wrong: origin must be BEHIND, otherwise this test proves nothing")
    assert "refs/heads/orchestrator/dev" in containing


def test_local_staging_branch_counts_as_integrated(tmp_path, monkeypatch):
    """THE FIX: reachability from local orchestrator/dev is integration evidence."""
    monkeypatch.setenv("ORCH_STAGING_BRANCH", "orchestrator/dev")
    import integration_sweeper as s
    repo = _frozen_fleet(tmp_path)

    assert "refs/heads/orchestrator/dev" in s._integration_targets(repo)

    evidence = s._merged_branch_evidence(repo, "agent/shadow-demo")
    assert evidence is not None, (
        "landed-but-unpushed work read as lost -- this is the QUARANTINE bug")
    sha, ref = evidence
    assert sha == _git(repo, "rev-parse", "agent/shadow-demo").stdout.strip()
    assert ref == "refs/heads/orchestrator/dev"


def test_unmerged_branch_is_still_not_integrated(tmp_path, monkeypatch):
    """The fix must not make everything look integrated."""
    monkeypatch.setenv("ORCH_STAGING_BRANCH", "orchestrator/dev")
    import integration_sweeper as s
    repo = _frozen_fleet(tmp_path)
    _git(repo, "checkout", "-q", "-b", "agent/never-merged", "master")
    open(os.path.join(repo, "orphan.txt"), "w").write("nope")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "not merged anywhere")

    assert s._merged_branch_evidence(repo, "agent/never-merged") is None


def test_origin_is_preferred_when_both_contain_the_work(tmp_path, monkeypatch):
    """Once promoted, the recorded ref must be origin -- so 'landed locally' and
    'landed upstream' stay distinguishable in the evidence note."""
    monkeypatch.setenv("ORCH_STAGING_BRANCH", "orchestrator/dev")
    import integration_sweeper as s
    repo = _frozen_fleet(tmp_path)
    _git(repo, "push", "-q", "origin", "orchestrator/dev")
    _git(repo, "fetch", "-q", "origin")

    sha, ref = s._merged_branch_evidence(repo, "agent/shadow-demo")
    assert ref == "origin/orchestrator/dev"


def test_strict_mode_fails_closed_on_bad_repo(tmp_path):
    """A broken repo_path must read as 'cannot prove integration', never as
    'nothing is integrated'."""
    import integration_sweeper as s
    assert s._integration_evidence("/nonexistent/repo/path", "any-slug") is None
    assert s._merged_branch_evidence("/nonexistent/repo/path", "agent/x") is None


# ---------------------------------------------------------------------------
# The other half of the defect: the demotion was one-way.
# sweep() re-selects only DONE/BLOCKED/RUNNING, so a QUARANTINED row was never
# re-examined -- even after the branch was pushed and the evidence became
# undeniable. verify_phantom(include_quarantined=True) makes it idempotent.
# ---------------------------------------------------------------------------

def _stub_db(s, monkeypatch, tasks, repo, updates):
    def select(table, query=None, *a, **k):
        if table == "projects":
            return [{"id": "p1", "name": "apparently", "repo_path": repo}]
        if table == "tasks":
            want = (query or {}).get("state", "")
            return [t for t in tasks if t["state"] in want]
        return []
    monkeypatch.setattr(s.db, "select", select)
    monkeypatch.setattr(s.db, "localize_repo_path", lambda p: p)
    monkeypatch.setattr(s.db, "update",
                        lambda table, where, patch: updates.append((where, patch)))
    # raising=False on purpose: `_paused_project_ids` does not exist on master. It ships in a
    # different layer of PR #24 that this branch deliberately does not carry, and this suite
    # was originally written against a tree that had it. Stubbing unconditionally made every
    # test here die in setup with AttributeError -- the suite failed for a reason that had
    # nothing to do with what it tests. Keeping the stub (rather than deleting it) means the
    # isolation is already correct if that layer ever lands.
    monkeypatch.setattr(s, "_paused_project_ids", lambda projects, ttl=20.0: set(),
                        raising=False)


def test_quarantined_rows_are_not_scanned_by_default(tmp_path, monkeypatch):
    import integration_sweeper as s
    repo = _frozen_fleet(tmp_path)
    tasks = [{"id": "1", "slug": "shadow-demo", "project_id": "p1",
              "state": "QUARANTINED", "note": "branch lost and recovery exhausted"}]
    updates = []
    _stub_db(s, monkeypatch, tasks, repo, updates)

    out = s.verify_phantom(limit=10, dry_run=True)
    assert out["scanned"] == 0, "default behaviour must not change"


def test_quarantined_row_with_evidence_is_restored(tmp_path, monkeypatch):
    import integration_sweeper as s
    repo = _frozen_fleet(tmp_path)
    tasks = [{"id": "1", "slug": "shadow-demo", "project_id": "p1",
              "state": "QUARANTINED", "note": "branch lost and recovery exhausted"}]
    updates = []
    _stub_db(s, monkeypatch, tasks, repo, updates)
    monkeypatch.setattr(s, "_integration_evidence",
                        lambda r, slug: ("a" * 40, "refs/heads/orchestrator/dev", "feat"))

    out = s.verify_phantom(limit=10, dry_run=True, include_quarantined=True)
    assert out["scanned"] == 1
    assert [m["slug"] for m in out["merged"]] == ["shadow-demo"]


def test_quarantined_row_without_evidence_is_left_exactly_alone(tmp_path, monkeypatch):
    """Absence of evidence must change nothing -- no requeue, no attempt bump.
    Re-running the pass is a no-op, not a slow march toward rebuilding dead work."""
    import integration_sweeper as s
    repo = _frozen_fleet(tmp_path)
    tasks = [{"id": "1", "slug": "genuinely-dead", "project_id": "p1",
              "state": "QUARANTINED", "note": "branch lost and recovery exhausted"}]
    updates = []
    _stub_db(s, monkeypatch, tasks, repo, updates)
    monkeypatch.setattr(s, "_integration_evidence", lambda r, slug: None)

    out = s.verify_phantom(limit=10, dry_run=False, include_quarantined=True)
    assert out["scanned"] == 1
    assert out["merged"] == []
    assert out["requeued"] == [], "a quarantined row must never be requeued for rebuild"
    assert out["still_unproven"][0]["action"] == "left closed"
    assert updates == [], f"no writes expected, got {updates}"


def test_phantom_rows_keep_their_requeue_path(tmp_path, monkeypatch):
    """The quarantine guard must not disable requeue for real phantoms."""
    import integration_sweeper as s
    repo = _frozen_fleet(tmp_path)
    tasks = [{"id": "1", "slug": "phantom-demo", "project_id": "p1",
              "state": s.PHANTOM_STATE,
              "note": f"[verify-attempt {s.VERIFY_ATTEMPT_CAP}/{s.VERIFY_ATTEMPT_CAP}]"}]
    updates = []
    _stub_db(s, monkeypatch, tasks, repo, updates)
    monkeypatch.setattr(s, "_integration_evidence", lambda r, slug: None)

    out = s.verify_phantom(limit=10, dry_run=False, include_quarantined=True)
    assert [r["slug"] for r in out["requeued"]] == ["phantom-demo"]
    assert updates and updates[0][1]["state"] == "QUEUED"
