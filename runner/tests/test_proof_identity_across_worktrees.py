"""A green build proof filed where nothing can find it is not a proof.

2026-09-02. Every release on this fleet failed for three days:

    releases in the previous 3 days                   106
    of those that succeeded                             0
    sustainable-barks alone                            45 failed

with, in the release row, `error: failed to push some refs`. That is not GitHub
rejecting anything. It is production_push_guard, the fleet's own pre-push hook,
refusing to certify an unverified tree -- for a tree that had been verified.

Proof identity was (repo DIRECTORY NAME, commit, dependency fingerprint, command,
kind). merge_train and release_train do their work in
.runtime/integration-worktrees/<sha1-of-path>, so the green production build of
sustainable-barks' dev tip was filed as:

    repo=f2949212f83b76aa831e  kind=merge-build  ok=True  cmd='npm run build'

while the guard, running against the real checkout, looked for one under
`Sustainable_Barks`. Across the whole proof graph, 5,873 of 13,894 verification rows
(42%) were filed under a worktree-hash name that nothing else would ever ask for.

A LINKED WORKTREE IS THE SAME REPOSITORY, and git says so in a file: a worktree's
`.git` is a FILE reading `gitdir: <main>/.git/worktrees/<name>`. Resolving it is pure
filesystem, which matters on a path that runs for every proof written and read.

Nothing is weakened. The commit sha and the dependency fingerprint are unchanged and
still discriminate -- and they were verified identical between the worktree and the
main checkout (f98fa7e299d3 in both) before this was written. Two checkouts of one
repository, at one commit, with one lockfile set and one build command, have the same
build result. That is what "the same repository" means.
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import proof_graph  # noqa: E402


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          timeout=60)


@pytest.fixture
def repo_with_worktree(tmp_path):
    """A real git repo with a real linked worktree -- the thing being tested is a
    git-on-disk convention, so faking it would test nothing."""
    main = tmp_path / "MyProject"
    main.mkdir()
    _git(str(main), "init", "-q", "-b", "main", ".")
    _git(str(main), "config", "user.email", "t@t")
    _git(str(main), "config", "user.name", "t")
    (main / "package.json").write_text('{"scripts": {"build": "nuxt build"}}')
    _git(str(main), "add", "-A")
    _git(str(main), "commit", "-qm", "init")
    wt = tmp_path / "integration-worktrees" / "f2949212f83b76aa831e"
    wt.parent.mkdir(parents=True, exist_ok=True)
    r = _git(str(main), "worktree", "add", "-q", str(wt), "HEAD")
    if r.returncode != 0:
        pytest.skip("git worktree unavailable: " + (r.stderr or "")[:120])
    proof_graph._MAIN_REPO_CACHE.clear()
    return str(main), str(wt)


def test_a_worktree_reports_the_main_repo_name(repo_with_worktree):
    """The regression, in one line."""
    main, wt = repo_with_worktree
    assert proof_graph._repo_name(wt) == "MyProject"
    assert proof_graph._repo_name(main) == "MyProject"


def test_a_proof_earned_in_a_worktree_is_found_from_the_main_repo(repo_with_worktree,
                                                                  monkeypatch, tmp_path):
    """This is the release that failed 45 times."""
    main, wt = repo_with_worktree
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path / "home"))
    commit = _git(main, "rev-parse", "HEAD").stdout.strip()
    proof_graph.record_verification(wt, commit, "npm run build", "build", True)
    assert proof_graph.reusable_verification(main, commit, "npm run build", "build")


def test_a_proof_earned_in_the_main_repo_is_found_from_a_worktree(repo_with_worktree,
                                                                  monkeypatch, tmp_path):
    main, wt = repo_with_worktree
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path / "home"))
    commit = _git(main, "rev-parse", "HEAD").stdout.strip()
    proof_graph.record_verification(main, commit, "npm run build", "build", True)
    assert proof_graph.reusable_verification(wt, commit, "npm run build", "build")


def test_the_worktree_and_the_main_repo_agree_on_the_dependency_fingerprint(
        repo_with_worktree):
    """The other half of proof identity. If these diverged, the name fix would be
    cosmetic -- so assert it rather than assume it."""
    main, wt = repo_with_worktree
    assert (proof_graph.dependency_fingerprint(main)
            == proof_graph.dependency_fingerprint(wt))


# ── what must NOT be merged ──────────────────────────────────────────────────

def test_a_different_repository_is_still_a_different_repository(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path / "home"))
    a, b = tmp_path / "A", tmp_path / "B"
    for d in (a, b):
        d.mkdir()
    proof_graph._MAIN_REPO_CACHE.clear()
    proof_graph.record_verification(str(a), "c" * 40, "npm run build", "build", True)
    assert not proof_graph.reusable_verification(str(b), "c" * 40, "npm run build",
                                                 "build")


def test_a_different_commit_is_still_unproven(repo_with_worktree, monkeypatch, tmp_path):
    main, wt = repo_with_worktree
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path / "home"))
    proof_graph.record_verification(wt, "a" * 40, "npm run build", "build", True)
    assert not proof_graph.reusable_verification(main, "b" * 40, "npm run build",
                                                 "build")


def test_a_different_command_is_still_unproven(repo_with_worktree, monkeypatch, tmp_path):
    main, wt = repo_with_worktree
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path / "home"))
    commit = _git(main, "rev-parse", "HEAD").stdout.strip()
    proof_graph.record_verification(wt, commit, "npm run build", "build", True)
    assert not proof_graph.reusable_verification(main, commit, "pnpm build", "build")


def test_a_red_build_is_never_reusable(repo_with_worktree, monkeypatch, tmp_path):
    main, wt = repo_with_worktree
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path / "home"))
    commit = _git(main, "rev-parse", "HEAD").stdout.strip()
    proof_graph.record_verification(wt, commit, "npm run build", "build", False)
    assert not proof_graph.reusable_verification(main, commit, "npm run build", "build")


# ── the resolver itself ──────────────────────────────────────────────────────

def test_a_plain_directory_resolves_to_itself(tmp_path):
    proof_graph._MAIN_REPO_CACHE.clear()
    d = tmp_path / "plain"
    d.mkdir()
    assert proof_graph._main_repo(str(d)) == os.path.realpath(str(d))


def test_a_normal_checkout_resolves_to_itself(repo_with_worktree):
    main, _wt = repo_with_worktree
    assert proof_graph._main_repo(main) == os.path.realpath(main)


def test_a_corrupt_git_file_does_not_raise(tmp_path):
    proof_graph._MAIN_REPO_CACHE.clear()
    d = tmp_path / "weird"
    d.mkdir()
    (d / ".git").write_text("this is not a gitdir line")
    assert proof_graph._main_repo(str(d)) == os.path.realpath(str(d))


def test_a_gitdir_pointing_nowhere_does_not_raise(tmp_path):
    proof_graph._MAIN_REPO_CACHE.clear()
    d = tmp_path / "dangling"
    d.mkdir()
    (d / ".git").write_text("gitdir: /nope/.git/worktrees/x")
    assert proof_graph._main_repo(str(d)) == os.path.realpath(str(d))


def test_the_cache_is_bounded(tmp_path):
    """runner.py lives for days and worktrees are created constantly."""
    proof_graph._MAIN_REPO_CACHE.clear()
    for i in range(proof_graph._MAIN_REPO_CACHE_MAX + 5):
        proof_graph._main_repo(str(tmp_path / ("d%d" % i)))
    assert len(proof_graph._MAIN_REPO_CACHE) <= proof_graph._MAIN_REPO_CACHE_MAX
