"""Agents commit in worktrees, never in the primary checkout (runner/hooks/pre-commit §0.5)."""
import os
import subprocess
import sys
import tempfile

HOOKS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "hooks"))


def _run(cwd, *args, env=None, check=True):
    return subprocess.run(args, cwd=cwd, env=env, check=check, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=60)


def _clean_env(**extra):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE", "ORCH_ALLOW_PRIMARY_COMMIT", "GIT_"))}
    env.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
                # §4 of the same hook refuses this throwaway author; that gate has its
                # own tests, and this file is about §0.5 only.
                "SKIP_IDENTITY_GATE": "1"})
    env.update(extra)
    return env


def _repo(tmp):
    repo = os.path.join(tmp, "primary")
    os.makedirs(repo)
    _run(repo, "git", "init", "-q", "-b", "master", env=_clean_env())
    _run(repo, "git", "config", "core.hooksPath", HOOKS, env=_clean_env())
    # A first commit with the hook disabled, so the fixture does not depend on it.
    open(os.path.join(repo, "a.txt"), "w").write("one\n")
    _run(repo, "git", "add", "a.txt", env=_clean_env())
    _run(repo, "git", "commit", "-q", "--no-verify", "-m", "seed", env=_clean_env())
    return repo


def _stage(repo, text):
    open(os.path.join(repo, "a.txt"), "a").write(text + "\n")
    _run(repo, "git", "add", "a.txt", env=_clean_env())


def test_a_claude_code_session_cannot_commit_in_the_primary_checkout():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _repo(tmp)
        _stage(repo, "from an agent")
        r = _run(repo, "git", "commit", "-q", "-m", "agent commit", env=_clean_env(CLAUDECODE="1"), check=False)
        assert r.returncode != 0
        assert "PRIMARY checkout" in r.stderr
        assert "a Claude Code session" in r.stderr
        assert "git worktree add" in r.stderr
        assert "ORCH_ALLOW_PRIMARY_COMMIT=1" in r.stderr


def test_a_process_with_no_terminal_cannot_commit_in_the_primary_checkout():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _repo(tmp)
        _stage(repo, "from a script")
        r = _run(repo, "git", "commit", "-q", "-m", "script commit", env=_clean_env(), check=False)
        assert r.returncode != 0
        assert "a process with no terminal" in r.stderr


def test_the_same_agent_commits_freely_in_a_linked_worktree():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _repo(tmp)
        wt = os.path.join(tmp, "primary-wt", "work")
        _run(repo, "git", "worktree", "add", "-q", "-b", "agent/work", wt, env=_clean_env())
        _stage(wt, "from an agent, in its worktree")
        r = _run(wt, "git", "commit", "-q", "-m", "agent commit", env=_clean_env(CLAUDECODE="1"), check=False)
        assert r.returncode == 0, r.stderr
        assert "PRIMARY checkout" not in r.stderr


def test_the_escape_hatch_is_explicit():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _repo(tmp)
        _stage(repo, "deliberate")
        r = _run(repo, "git", "commit", "-q", "-m", "deliberate",
                 env=_clean_env(CLAUDECODE="1", ORCH_ALLOW_PRIMARY_COMMIT="1"), check=False)
        assert r.returncode == 0, r.stderr


def test_no_verify_still_skips_the_hook_as_the_runner_relies_on():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _repo(tmp)
        _stage(repo, "runner")
        r = _run(repo, "git", "commit", "-q", "--no-verify", "-m", "runner", env=_clean_env(CLAUDECODE="1"), check=False)
        assert r.returncode == 0, r.stderr
