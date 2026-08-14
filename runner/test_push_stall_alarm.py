"""Push-visibility alarm tests — CORE INTEGRITY AUDIT §6.

The proof the brief asks for is exactly two claims:

  "PAT absent from remotes/logs; push alarm fires on a fixture stall"

so both are asserted against REAL git fixtures, not mocks. A push stall is a
property of the object graph (local branch ahead of origin/<branch> with an old
commit date); asserting it against a stubbed `_git` would only prove the stub
agrees with itself, and this alarm exists precisely because everyone's mental
model of "the push worked" was the thing that was wrong.

The stall clock is deliberately keyed to the OLDEST unpushed commit. A repo that
keeps committing while pushes fail always has a brand-new newest commit, so an
alarm keyed on the newest one stays silent for as long as the breakage keeps
producing work — the exact shape of failure being guarded against.
"""
import os
import subprocess
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.modules.setdefault("db", type(sys)("db"))  # imported at module scope, unused here

import push_stall_alarm as psa  # noqa: E402


def _git(repo, *args, env=None):
    e = dict(os.environ)
    e.update({
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    })
    if env:
        e.update(env)
    return subprocess.run(["git"] + list(args), cwd=repo, env=e,
                          capture_output=True, text=True, check=True)


def _commit(repo, name, text, when=None):
    (repo / name).write_text(text)
    _git(repo, "add", "-A")
    env = {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when} if when else None
    _git(repo, "commit", "-m", f"add {name}", env=env)


@pytest.fixture()
def repo_pair(tmp_path):
    """A bare 'origin' plus a clone with master pushed and in sync."""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git(origin, "init", "--bare", "--initial-branch=master", ".")

    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "--initial-branch=master", ".")
    _git(work, "remote", "add", "origin", str(origin))
    _commit(work, "base.txt", "base\n")
    _git(work, "push", "-u", "origin", "master")
    _git(work, "fetch", "origin")
    return work


# ── push stall ───────────────────────────────────────────────────────────────

def test_in_sync_branch_reports_no_unpushed_commits(repo_pair):
    info = psa.unpushed_commits(str(repo_pair), "master")
    assert info == {"count": 0, "oldest_ts": None, "age_s": 0.0}


def test_local_only_commit_is_detected(repo_pair):
    _commit(repo_pair, "local.txt", "unpushed\n")
    info = psa.unpushed_commits(str(repo_pair), "master")
    assert info["count"] == 1


def test_age_tracks_the_oldest_unpushed_commit_not_the_newest(repo_pair):
    """The whole point of the clock: new work must not reset the alarm."""
    old = "2001-01-01T00:00:00+0000"
    _commit(repo_pair, "old.txt", "stalled long ago\n", when=old)
    _commit(repo_pair, "new.txt", "committed just now\n")  # newest == now

    info = psa.unpushed_commits(str(repo_pair), "master")
    assert info["count"] == 2
    # Keyed on the 2001 commit, so this is years, not seconds.
    assert info["age_s"] > 365 * 24 * 3600
    assert info["age_s"] >= psa.STALL_THRESHOLD_S


def test_fresh_commit_is_below_threshold(repo_pair):
    """A just-made commit is not yet a stall — the push may still be in flight."""
    _commit(repo_pair, "fresh.txt", "just committed\n")
    info = psa.unpushed_commits(str(repo_pair), "master")
    assert info["age_s"] < psa.STALL_THRESHOLD_S


def test_pushing_clears_the_stall(repo_pair):
    _commit(repo_pair, "local.txt", "unpushed\n", when="2001-01-01T00:00:00+0000")
    assert psa.unpushed_commits(str(repo_pair), "master")["count"] == 1
    _git(repo_pair, "push", "origin", "master")
    _git(repo_pair, "fetch", "origin")
    assert psa.unpushed_commits(str(repo_pair), "master")["count"] == 0


def test_missing_branch_and_untracked_branch_are_not_stalls(repo_pair):
    """
    Absent branch, or a branch never pushed at all, returns None rather than a
    false stall — a brand-new local branch is the merge train's business.
    """
    assert psa.unpushed_commits(str(repo_pair), "does-not-exist") is None
    _git(repo_pair, "checkout", "-b", "never-pushed")
    _commit(repo_pair, "x.txt", "x\n")
    assert psa.unpushed_commits(str(repo_pair), "never-pushed") is None


# ── credential in remote URL ─────────────────────────────────────────────────

def test_clean_https_remote_reports_no_credential(repo_pair):
    _git(repo_pair, "remote", "set-url", "origin",
         "https://github.com/kalepasch1/claude-orchestrator.git")
    assert psa.scan_remotes(str(repo_pair)) == []


def test_ssh_remote_is_not_a_credential_leak(repo_pair):
    """git@host:owner/repo carries no secret — the identity is the key agent."""
    _git(repo_pair, "remote", "set-url", "origin",
         "git@github.com:kalepasch1/claude-orchestrator.git")
    assert psa.scan_remotes(str(repo_pair)) == []


@pytest.mark.parametrize("url", [
    "https://ghp_AAAAAAAAAAAAAAAAAAAA@github.com/o/r.git",
    "https://user:ghp_AAAAAAAAAAAAAAAAAAAA@github.com/o/r.git",
])
def test_token_in_remote_url_is_detected(repo_pair, url):
    """The 2026-08-02 incident shape: PAT embedded in the URL."""
    _git(repo_pair, "remote", "set-url", "origin", url)
    leaks = psa.scan_remotes(str(repo_pair))
    assert len(leaks) == 1
    assert leaks[0]["remote"] == "origin"


def test_detected_leak_never_echoes_the_secret(repo_pair):
    """
    Reporting the PAT to prove the PAT leaked would just be a second copy of the
    incident, this time in the approvals table.
    """
    token = "ghp_SUPERSECRETVALUE0000"
    _git(repo_pair, "remote", "set-url", "origin", f"https://{token}@github.com/o/r.git")
    leaks = psa.scan_remotes(str(repo_pair))
    assert token not in leaks[0]["url"]
    assert "***@" in leaks[0]["url"]


def test_redact_leaves_credential_free_urls_untouched():
    clean = "https://github.com/kalepasch1/claude-orchestrator.git"
    assert psa.redact(clean) == clean
    assert psa.redact("https://tok@github.com/o/r.git") == "https://***@github.com/o/r.git"


# ── this repo, right now ─────────────────────────────────────────────────────

def test_this_repo_has_no_credential_in_any_remote():
    """
    Standing assertion of the §6 proof against the live checkout: if anyone
    re-adds a token-bearing origin, this fails in CI rather than at audit time.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    assert psa.scan_remotes(here) == []
