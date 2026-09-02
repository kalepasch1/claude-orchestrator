import os
import subprocess
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import production_push_guard


def test_only_production_branch_updates_are_guarded():
    sha = "a" * 40
    lines = [
        f"refs/heads/feature {sha} refs/heads/feature {'0' * 40}\n",
        f"refs/heads/main {sha} refs/heads/main {'b' * 40}\n",
        f"refs/heads/master {sha} refs/heads/master {'c' * 40}\n",
    ]
    updates = production_push_guard.guarded_updates(lines)
    assert [update[2] for update in updates] == ["refs/heads/main", "refs/heads/master"]


def test_branch_deletion_is_not_built():
    lines = [f"(delete) {'0' * 40} refs/heads/main {'a' * 40}\n"]
    assert production_push_guard.guarded_updates(lines) == []


def test_nested_deploy_root_skips_unrelated_changes():
    with tempfile.TemporaryDirectory() as repo:
        web = os.path.join(repo, "web")
        os.makedirs(web)
        with open(os.path.join(web, "vercel.json"), "w") as f:
            f.write("{}")
        with patch.object(production_push_guard.build_gate.dependency_prewarm, "package_roots", return_value=[web]):
            with patch.object(production_push_guard, "_git", return_value="runner/release_train.py"):
                assert production_push_guard.changes_affect_build(repo, "a" * 40, "b" * 40) is False
            with patch.object(production_push_guard, "_git", return_value="web/pages/index.vue"):
                assert production_push_guard.changes_affect_build(repo, "a" * 40, "b" * 40) is True


def test_unproved_production_commit_is_blocked():
    with tempfile.TemporaryDirectory() as repo:
        with patch.object(production_push_guard.build_gate, "detect_build_cmd", return_value="npm run build"):
            with patch.object(production_push_guard.proof_graph, "reusable_verification", return_value=None):
                ok, message = production_push_guard.verify(repo, "a" * 40)
    assert ok is False
    # Asserted on substance, not on a sentence. The refusal used to read "No green
    # release-train proof"; it now names the exact commit and the exact build
    # command it wants proof for, which is strictly more useful and made the old
    # substring assertion fail for an improvement. What must hold is that the push
    # is refused, that the message says a green proof is missing, and that it
    # identifies the commit — otherwise the operator cannot act on it.
    assert "green build proof" in message.lower(), message
    assert "a" * 12 in message, message
    assert "npm run build" in message, message


# --- the staging gate -------------------------------------------------------
#
# These build real git repositories rather than patching _git, because the whole
# point of the check is what git itself says about ancestry. A mocked answer
# would pass while the rule was wrong.

def _run(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True, timeout=30)


def _fleet_repo(tmp, staging=True):
    """An `origin` with main, plus a work clone. Returns (clone, origin)."""
    origin = os.path.join(tmp, "origin.git")
    work = os.path.join(tmp, "work")
    seed = os.path.join(tmp, "seed")
    os.makedirs(seed)
    _run(tmp, "git", "init", "--bare", "--initial-branch=main", origin)
    _run(seed, "git", "init", "--initial-branch=main")
    _run(seed, "git", "config", "user.email", "t@example.test")
    _run(seed, "git", "config", "user.name", "t")
    open(os.path.join(seed, "a.txt"), "w").write("one\n")
    _run(seed, "git", "add", "-A")
    _run(seed, "git", "commit", "-m", "base")
    _run(seed, "git", "remote", "add", "origin", origin)
    _run(seed, "git", "push", "-q", "origin", "main")
    if staging:
        _run(seed, "git", "push", "-q", "origin", "main:refs/heads/orchestrator/dev")
    _run(tmp, "git", "clone", "-q", origin, work)
    _run(work, "git", "config", "user.email", "t@example.test")
    _run(work, "git", "config", "user.name", "t")
    return work, origin


def _commit(repo, text):
    open(os.path.join(repo, "a.txt"), "a").write(text + "\n")
    _run(repo, "git", "add", "-A")
    _run(repo, "git", "commit", "-m", text)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                          capture_output=True, text=True, timeout=30).stdout.strip()


def test_a_commit_that_never_met_staging_is_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        work, _ = _fleet_repo(tmp)
        sha = _commit(work, "straight to main")
        ok, message = production_push_guard.verify_promoted_from_staging(work, sha)
        assert ok is False
        assert "orchestrator/dev" in message
        # The refusal has to say what to do, or it just teaches people the override.
        assert "git merge" in message
        assert "ORCH_ALLOW_DIRECT_PROD_PUSH" in message


def test_a_commit_merged_to_staging_first_is_allowed():
    with tempfile.TemporaryDirectory() as tmp:
        work, _ = _fleet_repo(tmp)
        sha = _commit(work, "integrated")
        _run(work, "git", "push", "-q", "origin", f"{sha}:refs/heads/orchestrator/dev")
        ok, message = production_push_guard.verify_promoted_from_staging(work, sha)
        assert ok is True
        assert "orchestrator/dev" in message


def test_an_ancestor_of_staging_is_allowed():
    # Promoting a commit that dev has already moved past is still an integrated
    # commit — the rule is containment, not tip equality.
    with tempfile.TemporaryDirectory() as tmp:
        work, _ = _fleet_repo(tmp)
        first = _commit(work, "integrated one")
        second = _commit(work, "integrated two")
        _run(work, "git", "push", "-q", "origin", f"{second}:refs/heads/orchestrator/dev")
        ok, _ = production_push_guard.verify_promoted_from_staging(work, first)
        assert ok is True


def test_a_repo_with_no_staging_branch_is_not_held_to_the_rule():
    with tempfile.TemporaryDirectory() as tmp:
        work, _ = _fleet_repo(tmp, staging=False)
        sha = _commit(work, "no dev branch here")
        ok, message = production_push_guard.verify_promoted_from_staging(work, sha)
        assert ok is True
        assert "does not apply" in message
