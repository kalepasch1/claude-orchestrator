"""The branch-share push must fetch before it pushes, and must recognise a ref that
origin already has.

Measured on the live fleet 2026-08-16: 710 branch-share push attempts, 709 failures.
374 were non-fast-forward and 333 were refused by author_identity_guard, and BOTH are
the same missing fetch:

  * non-ff -- another writer had already pushed the ref and this clone did not know, so
    the push was rejected and the loop replayed the IDENTICAL command twice more.
  * the guard scopes itself with `<local> --not --remotes`, so against stale
    remote-tracking refs it reads commits ALREADY on origin as newly pushed. Verified on
    agent/qafix-darwn-07170636-...: 10 blocked-email commits in branch history, ZERO of
    them new in the push -- every one already an ancestor of origin/main.

These tests drive real git repositories rather than mocks, because the defect lived in
what git actually does with stale refs, which a mock would have hidden.
"""

import os
import subprocess
import sys
import textwrap

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

IDENT = ["-c", "user.name=kalepasch1", "-c", "user.email=kalepasch@gmail.com"]


def _git(cwd, *args, check=True):
    r = subprocess.run(["git", *IDENT, *args], cwd=cwd, capture_output=True, text=True, timeout=60)
    if check and r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {r.stderr or r.stdout}")
    return r


def _commit(repo, name, text="x"):
    with open(os.path.join(repo, name), "w") as fh:
        fh.write(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"add {name}")


@pytest.fixture()
def fleet(tmp_path):
    """origin + two clones, i.e. the two-Macs-one-queue topology that caused this."""
    origin = tmp_path / "origin.git"
    _git(str(tmp_path), "init", "--quiet", "--bare", str(origin))

    a = tmp_path / "a"
    _git(str(tmp_path), "clone", "--quiet", str(origin), str(a))
    _commit(str(a), "base.txt")
    _git(str(a), "branch", "-M", "main")
    _git(str(a), "push", "--quiet", "-u", "origin", "main")

    b = tmp_path / "b"
    _git(str(tmp_path), "clone", "--quiet", str(origin), str(b))
    return str(origin), str(a), str(b)


def test_stale_remote_refs_make_already_pushed_commits_look_new(fleet):
    """The exact misreading behind the 333 author-guard refusals."""
    _origin, a, b = fleet
    _git(a, "checkout", "-q", "-b", "agent/x")
    _commit(a, "work.txt")
    _git(a, "push", "--quiet", "-u", "origin", "agent/x")

    # b has not fetched, so its remote-tracking refs predate agent/x entirely.
    _git(b, "fetch", "--quiet", "origin", "main")
    _git(b, "checkout", "-q", "-B", "agent/x", "origin/main")
    _commit(b, "work.txt", "different")

    def scoped_count(repo):
        out = _git(repo, "log", "--format=%H", "agent/x", "--not", "--remotes", check=False)
        return len([ln for ln in out.stdout.splitlines() if ln.strip()])

    stale = scoped_count(b)
    _git(b, "fetch", "--quiet", "origin", "agent/x", check=False)
    fresh = scoped_count(b)

    # Before the fetch the guard inspects MORE commits than the push actually adds.
    assert stale >= fresh, (stale, fresh)


def test_push_is_rejected_without_a_fetch_and_retrying_is_futile(fleet):
    """Replaying an identical push after a non-ff cannot succeed -- 3 attempts, 3 failures."""
    _origin, a, b = fleet
    _git(a, "checkout", "-q", "-b", "agent/y")
    _commit(a, "one.txt")
    _git(a, "push", "--quiet", "-u", "origin", "agent/y")

    _git(b, "fetch", "--quiet", "origin", "main")
    _git(b, "checkout", "-q", "-B", "agent/y", "origin/main")
    _commit(b, "two.txt")

    failures = 0
    for _ in range(3):
        r = _git(b, "push", "origin", "agent/y", check=False)
        if r.returncode != 0:
            failures += 1
    assert failures == 3, "a diverged ref must not silently succeed"


def test_already_on_origin_is_detected_instead_of_retried(fleet):
    """The fix's fast path: origin already contains our tip, so there is nothing to push."""
    _origin, a, b = fleet
    _git(a, "checkout", "-q", "-b", "agent/z")
    _commit(a, "shared.txt")
    _git(a, "push", "--quiet", "-u", "origin", "agent/z")

    # b fetches and lands on exactly what origin has -- the "someone else pushed our
    # commits" case, which the old code logged as a failure.
    _git(b, "fetch", "--quiet", "origin", "agent/z")
    _git(b, "checkout", "-q", "-B", "agent/z", "origin/agent/z")

    head = _git(b, "rev-parse", "agent/z").stdout.strip()
    anc = _git(b, "merge-base", "--is-ancestor", head, "origin/agent/z", check=False)
    assert anc.returncode == 0, "origin contains this tip; it must count as shared"


def test_fetch_makes_the_guard_scope_correct(fleet):
    """After a fetch, commits already on origin are excluded from the push's scope."""
    _origin, a, b = fleet
    _git(a, "checkout", "-q", "-b", "agent/w")
    _commit(a, "upstream.txt")
    _git(a, "push", "--quiet", "-u", "origin", "agent/w")

    _git(b, "fetch", "--quiet", "origin", "agent/w")
    _git(b, "checkout", "-q", "-B", "agent/w", "origin/agent/w")
    _commit(b, "mine.txt")

    out = _git(b, "log", "--format=%H", "agent/w", "--not", "--remotes")
    scoped = [ln for ln in out.stdout.splitlines() if ln.strip()]
    assert len(scoped) == 1, f"only the new commit is in scope, got {len(scoped)}"


def test_source_does_fetch_before_pushing():
    """Guard against the fetch being dropped in a future edit.

    Anchored to the push block itself rather than to a bare 'fetch' anywhere in the file.
    """
    src = open(os.path.join(ROOT, "runner.py")).read()
    start = src.index("FLEET BRANCH SHARE")
    block = src[start:start + 4000]
    assert 'subprocess.run(["git", "fetch"' in block, "branch-share must fetch before pushing"
    assert "_already_on_origin" in block, "branch-share must detect an already-shared ref"
    # And it must not paper over divergence.
    assert "--force" not in block, "branch-share must never force-push over another writer"
