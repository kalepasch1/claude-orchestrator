"""Regression: a sha on the LOCAL integration branch is not a phantom.

merge_truth._resolve_target_ref() documented itself as "prefer origin/<target>; fall
back to the local ref if origin is not present" — but it returned the FIRST ref that
resolved and verify_merge_reachable() then tested ancestry against that one ref only.
`origin/<target>` almost always resolves, so the local fallback was effectively dead
code: it triggered only when origin was entirely absent.

Under the deliberate dev->prod freeze the staging branch is landed locally and NOT
pushed, so origin resolves but is STALE. Every commit landed since the last promotion
was therefore reported PHANTOM despite being reachable from the branch it was merged
into — and because guarded_task_update() consults this check before writing,
integration_sweeper's correct MERGED write was silently downgraded to
PHANTOM_UNVERIFIED. The evidence trail recorded the opposite of what was verified.
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


def _frozen_repo(tmp_path):
    """origin/<target> resolves but is BEHIND local <target>."""
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
    _git(repo, "push", "-q", "origin", "master", "orchestrator/dev")

    # Land work on the LOCAL staging branch only — never pushed.
    _git(repo, "checkout", "-q", "orchestrator/dev")
    open(os.path.join(repo, "landed.txt"), "w").write("landed")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "landed but not promoted")
    sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "fetch", "-q", "origin")
    return repo, sha


def test_fixture_is_honest(tmp_path):
    """origin really must NOT contain the sha, or the test proves nothing."""
    repo, sha = _frozen_repo(tmp_path)
    on_origin = subprocess.run(
        ["git", "merge-base", "--is-ancestor", sha, "origin/orchestrator/dev"],
        cwd=repo, capture_output=True).returncode
    on_local = subprocess.run(
        ["git", "merge-base", "--is-ancestor", sha, "orchestrator/dev"],
        cwd=repo, capture_output=True).returncode
    assert on_origin == 1, "fixture wrong: origin must be behind"
    assert on_local == 0


def test_local_landing_is_OK_not_phantom(tmp_path):
    import merge_truth
    repo, sha = _frozen_repo(tmp_path)

    verdict, reason = merge_truth.verify_merge_reachable(
        repo, sha, "orchestrator/dev", fetch=False)

    assert verdict == merge_truth.OK, f"got {verdict}: {reason}"
    assert "orchestrator/dev" in reason


def test_all_candidate_refs_are_reported_when_none_match(tmp_path):
    """A real phantom must name every ref that was actually checked, so the note
    cannot claim more (or less) verification than happened."""
    import merge_truth
    repo, _ = _frozen_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "orphan", "master")
    open(os.path.join(repo, "orphan.txt"), "w").write("nope")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "never merged")
    orphan = _git(repo, "rev-parse", "HEAD").stdout.strip()

    verdict, reason = merge_truth.verify_merge_reachable(
        repo, orphan, "orchestrator/dev", fetch=False)

    assert verdict == merge_truth.PHANTOM
    assert "origin/orchestrator/dev" in reason and "not an ancestor of any of" in reason


def test_unresolvable_target_is_infra_error_not_phantom(tmp_path):
    """Not being able to ask the question must never read as the answer being no."""
    import merge_truth
    repo, sha = _frozen_repo(tmp_path)

    verdict, _ = merge_truth.verify_merge_reachable(
        repo, sha, "no/such/branch", fetch=False)

    assert verdict == merge_truth.INFRA_ERROR


def test_missing_commit_is_still_phantom(tmp_path):
    import merge_truth
    repo, _ = _frozen_repo(tmp_path)

    verdict, _ = merge_truth.verify_merge_reachable(
        repo, "0" * 40, "orchestrator/dev", fetch=False)

    assert verdict == merge_truth.PHANTOM
