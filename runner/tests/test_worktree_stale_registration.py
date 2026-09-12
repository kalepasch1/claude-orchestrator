#!/usr/bin/env python3
"""A worktree whose directory is gone must not wedge its branch forever.

Reproduced live, twice, on 2026-08-26:

    fatal: cannot force update the branch
           'agent/improve-implement-advanced-branch-management-recon-slice-4'
           used by worktree at '<path>'

git's worktree REGISTRY outlives the directory. A hand-deleted checkout, a
crashed cleanup or a reboot mid-run leaves an entry pointing at a path that no
longer exists, and git then refuses to create the branch for a new worktree.

ensure_task_worktree had no self-healing path for it. The only prune lived
inside the `os.path.isdir(worktree)` branch, which cannot fire when the problem
is precisely that the directory is missing — so the task failed, retried, and
failed identically, forever, on a condition one command clears.

`git worktree prune` removes an entry only when its checkout is missing from
disk, so the fix is narrow by construction. The tests below say so in the
direction that matters: a live worktree, a locked one, and one holding
uncommitted work all survive it.
"""

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import worktree_isolation as isolation  # noqa: E402


def git(repo, *args, check=True):
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                            text=True, timeout=60)
    if check and result.returncode:
        raise AssertionError("git %s failed: %s" % (" ".join(args), result.stderr))
    return result


def make_repo(root):
    """A repo with one commit on main."""
    os.makedirs(root, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    with open(os.path.join(root, "README"), "w") as handle:
        handle.write("x\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "--no-verify", "-m", "init")
    return root


def worktree_paths(repo):
    listing = git(repo, "worktree", "list", "--porcelain").stdout
    return [line.split(" ", 1)[1] for line in listing.splitlines()
            if line.startswith("worktree ")]


class TestTheWedge:
    def test_a_missing_directory_blocks_the_branch_until_pruned(self):
        with tempfile.TemporaryDirectory() as raw_root:
            temp_root = os.path.realpath(raw_root)
            repo = make_repo(os.path.join(temp_root, "repo"))
            stale = os.path.join(temp_root, "wt", "task")
            git(repo, "worktree", "add", "-q", "-b", "agent/task", stale, "main")

            # The checkout vanishes; the registry entry does not.
            subprocess.run(["rm", "-rf", stale], check=True, timeout=60)

            blocked = git(repo, "worktree", "add", "--force",
                          os.path.join(temp_root, "wt", "task2"),
                          "-B", "agent/task", "main", check=False)
            assert blocked.returncode != 0
            assert "used by worktree" in (blocked.stderr + blocked.stdout)

            assert isolation.prune_stale_registrations(repo) is True

            freed = git(repo, "worktree", "add", "--force",
                        os.path.join(temp_root, "wt", "task2"),
                        "-B", "agent/task", "main", check=False)
            assert freed.returncode == 0, freed.stderr

    def test_the_stale_entry_is_actually_removed(self):
        with tempfile.TemporaryDirectory() as raw_root:
            temp_root = os.path.realpath(raw_root)
            repo = make_repo(os.path.join(temp_root, "repo"))
            stale = os.path.join(temp_root, "wt", "gone")
            git(repo, "worktree", "add", "-q", "-b", "agent/gone", stale, "main")
            subprocess.run(["rm", "-rf", stale], check=True, timeout=60)

            assert stale in worktree_paths(repo)
            isolation.prune_stale_registrations(repo)
            assert stale not in worktree_paths(repo)


class TestItDestroysNothingInUse:
    def test_a_live_worktree_survives(self):
        with tempfile.TemporaryDirectory() as raw_root:
            temp_root = os.path.realpath(raw_root)
            repo = make_repo(os.path.join(temp_root, "repo"))
            live = os.path.join(temp_root, "wt", "live")
            git(repo, "worktree", "add", "-q", "-b", "agent/live", live, "main")

            isolation.prune_stale_registrations(repo)

            assert live in worktree_paths(repo)
            assert os.path.isdir(live)

    def test_a_worktree_holding_uncommitted_work_survives(self):
        with tempfile.TemporaryDirectory() as raw_root:
            temp_root = os.path.realpath(raw_root)
            repo = make_repo(os.path.join(temp_root, "repo"))
            busy = os.path.join(temp_root, "wt", "busy")
            git(repo, "worktree", "add", "-q", "-b", "agent/busy", busy, "main")
            with open(os.path.join(busy, "work-in-progress"), "w") as handle:
                handle.write("do not lose me\n")

            isolation.prune_stale_registrations(repo)

            assert os.path.exists(os.path.join(busy, "work-in-progress"))
            assert busy in worktree_paths(repo)

    def test_a_locked_worktree_survives(self):
        # setup-worktrees.sh locks every checkout it makes.
        with tempfile.TemporaryDirectory() as raw_root:
            temp_root = os.path.realpath(raw_root)
            repo = make_repo(os.path.join(temp_root, "repo"))
            locked = os.path.join(temp_root, "wt", "locked")
            git(repo, "worktree", "add", "-q", "-b", "agent/locked", locked, "main")
            git(repo, "worktree", "lock", locked)

            isolation.prune_stale_registrations(repo)

            assert locked in worktree_paths(repo)

    def test_only_the_stale_entry_goes_when_both_exist(self):
        with tempfile.TemporaryDirectory() as raw_root:
            temp_root = os.path.realpath(raw_root)
            repo = make_repo(os.path.join(temp_root, "repo"))
            live = os.path.join(temp_root, "wt", "live")
            stale = os.path.join(temp_root, "wt", "stale")
            git(repo, "worktree", "add", "-q", "-b", "agent/live", live, "main")
            git(repo, "worktree", "add", "-q", "-b", "agent/stale", stale, "main")
            subprocess.run(["rm", "-rf", stale], check=True, timeout=60)

            isolation.prune_stale_registrations(repo)

            paths = worktree_paths(repo)
            assert live in paths
            assert stale not in paths


class TestItFailsSoftly:
    def test_a_non_repo_returns_false_rather_than_raising(self):
        # A prune that cannot run leaves the caller exactly where it was; it
        # must not turn a recoverable setup into an exception.
        with tempfile.TemporaryDirectory() as raw_root:
            temp_root = os.path.realpath(raw_root)
            assert isolation.prune_stale_registrations(temp_root) is False

    def test_a_repo_with_no_worktrees_is_fine(self):
        with tempfile.TemporaryDirectory() as raw_root:
            temp_root = os.path.realpath(raw_root)
            repo = make_repo(os.path.join(temp_root, "repo"))
            assert isolation.prune_stale_registrations(repo) is True
