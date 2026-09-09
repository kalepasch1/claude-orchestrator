"""Supersession-by-touch-date must not fail open when the creator date is absent.

Regression cover for the classifier defect where step 5 of
`tools/reconcile_local_branches.py::classify` was guarded by
`if item.created_at and all(...)`. A tip whose `%(creatordate:unix)` resolved
to 0 skipped the supersession check entirely and fell through to step 6, which
labels anything still-appliable RECOVERABLE_VALUE.

That direction is the dangerous one: the recovery task generated from such a
tip proposes re-applying an old snapshot over paths base has since rewritten,
i.e. it proposes a regression rather than merely wasting a run.

These tests build real git repositories, because the behaviour under test is
entirely about what `git log -1 --format=%ct` reports for a path on base
versus the tip's own timestamp.
"""

import os
import subprocess
import sys

import pytest

TOOLS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"
)
sys.path.insert(0, TOOLS)

import reconcile_local_branches as R  # noqa: E402


DAY = 86400
BASE_T = 1_700_000_000


def _run(cwd, *args, env=None):
    subprocess.run(
        args, cwd=cwd, check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
    )


def _commit(repo, message, when):
    """Commit staged changes with both author and committer date pinned."""
    env = dict(os.environ)
    env.update(
        GIT_AUTHOR_DATE=f"{when} +0000",
        GIT_COMMITTER_DATE=f"{when} +0000",
        GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
    )
    _run(repo, "git", "commit", "--no-verify", "-m", message, env=env)


def _write(repo, name, text):
    with open(os.path.join(repo, name), "w") as fh:
        fh.write(text)


@pytest.fixture
def repo(tmp_path):
    r = str(tmp_path / "r")
    os.makedirs(r)
    _run(r, "git", "init", "-q", "-b", "main")
    _run(r, "git", "config", "user.email", "t@t")
    _run(r, "git", "config", "user.name", "t")

    # Root commit carrying both files.
    _write(r, "alpha.txt", "root\n")
    _write(r, "beta.txt", "root\n")
    _run(r, "git", "add", "-A")
    _commit(r, "root", BASE_T)
    return r


def _classify_tip(repo, branch, created_at):
    """Classify `branch` against main, with a caller-supplied created_at."""
    sha = subprocess.run(
        ["git", "rev-parse", branch], cwd=repo,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    item = R.Item(ref="refs/heads/" + branch, sha=sha,
                  subject="tip", created_at=created_at)
    cwd = os.getcwd()
    os.chdir(repo)
    try:
        R.classify(item, "main", set())
    finally:
        os.chdir(cwd)
    return item


def _build_tip(repo, branch, files, tip_time):
    """Branch off root, modify `files`, leave main checked out afterwards."""
    _run(repo, "git", "checkout", "-q", "-b", branch, "HEAD")
    for name in files:
        _write(repo, name, "tip change\n")
    _run(repo, "git", "add", "-A")
    _commit(repo, "tip work", tip_time)
    _run(repo, "git", "checkout", "-q", "main")


def _advance_base(repo, files, when):
    for name in files:
        _write(repo, name, f"base rewrite {name}\n")
    _run(repo, "git", "add", "-A")
    _commit(repo, "base moves on", when)


# --- the defect -------------------------------------------------------------

@pytest.mark.parametrize(
    "created_at, label",
    [
        (BASE_T + DAY, "creator date available"),
        (0, "creator date unavailable"),
    ],
)
def test_superseded_when_base_rewrote_every_touched_path(repo, created_at, label):
    """Base rewrote every touched path after the tip -> SUPERSEDED_BY_NEWER.

    The created_at=0 case is the regression: it used to skip step 5 and come
    back RECOVERABLE_VALUE, which is what generates a reverting recovery task.
    """
    _build_tip(repo, "safety/tip", ["alpha.txt", "beta.txt"], BASE_T + DAY)
    _advance_base(repo, ["alpha.txt", "beta.txt"], BASE_T + 10 * DAY)

    item = _classify_tip(repo, "safety/tip", created_at)

    assert item.classification == "SUPERSEDED_BY_NEWER", (
        f"[{label}] expected SUPERSEDED_BY_NEWER, got "
        f"{item.classification}: {item.disposition}"
    )


# --- the guard against over-correcting --------------------------------------

@pytest.mark.parametrize("created_at", [BASE_T + DAY, 0])
def test_partial_rewrite_stays_recoverable(repo, created_at):
    """Only some touched paths rewritten -> genuine work is NOT dropped."""
    _build_tip(repo, "safety/partial", ["alpha.txt", "beta.txt"], BASE_T + DAY)
    _advance_base(repo, ["alpha.txt"], BASE_T + 10 * DAY)  # beta.txt untouched

    item = _classify_tip(repo, "safety/partial", created_at)

    assert item.classification != "SUPERSEDED_BY_NEWER", (
        "a tip with an un-rewritten path must not be discarded as superseded; "
        f"got {item.classification}: {item.disposition}"
    )


def test_tip_newer_than_base_is_not_superseded(repo):
    """A tip authored after base last moved is not superseded."""
    _advance_base(repo, ["alpha.txt", "beta.txt"], BASE_T + DAY)
    _build_tip(repo, "safety/fresh", ["alpha.txt", "beta.txt"], BASE_T + 10 * DAY)

    item = _classify_tip(repo, "safety/fresh", 0)

    assert item.classification != "SUPERSEDED_BY_NEWER", (
        "a tip newer than every base touch must stay recoverable; "
        f"got {item.classification}: {item.disposition}"
    )


def test_tip_timestamp_reads_commit_committer_date(repo):
    """The fallback used by step 5 reports the tip commit's own date."""
    _build_tip(repo, "safety/stamp", ["alpha.txt"], BASE_T + 5 * DAY)
    sha = subprocess.run(
        ["git", "rev-parse", "safety/stamp"], cwd=repo,
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    cwd = os.getcwd()
    os.chdir(repo)
    try:
        assert R.tip_timestamp(sha) == BASE_T + 5 * DAY
    finally:
        os.chdir(cwd)
