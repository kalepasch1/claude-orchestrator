"""env_permission_sweep's walk was rewritten for speed. These pin that it did not change.

WHY THIS FILE EXISTS. On 2026-09-08 the sweep was measured at ~14 seconds per triage
cycle, walking 114,403 directories under the operator's ~/Documents. cProfile showed
7.17s of that in 109,504 posix.lstat calls that nothing in the function had asked for:
os.walk, with followlinks=False, calls os.path.islink() on every directory before
recursing into it. Rewriting the traversal on os.scandir -- which already stats each entry
as it lists it -- removed all of them, measured 29.98s -> 14.43s, 21.33s -> 11.78s and
15.44s -> 6.19s over the live tree.

A traversal rewrite is exactly the kind of change that silently stops finding things, and
this one already did, twice, before it landed:

  * The first draft was off by one on the depth cap. It visited 39,061 directories instead
    of 114,403 and missed 10 real .env files, including live ones under
    .runtime/integration-worktrees/. Only an equivalence check against the old walk caught
    it -- the sweep's own tests all still passed, because none of them nested five deep.

  * The second draft used is_dir(follow_symlinks=False), which reclassifies a symlink
    pointing at a directory as a FILE, and read the mode with stat(follow_symlinks=False),
    which reads the link's own 0777 rather than its target's.

So these tests compare the shipped implementation against a from-scratch os.walk reference
on trees built to hit precisely those edges. They are about EQUIVALENCE, not about
permissions -- test_env_permission_sweep.py owns the permission behaviour.
"""
import os
import stat
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import blocked_triage as bt

#: Matches the sweep's own default; the depth tests build trees around this exact value.
SWEEP_MAX_DEPTH = 5
#: One level deeper than the cap, to prove the boundary is where it claims to be.
BEYOND_CAP = SWEEP_MAX_DEPTH + 1
GROUP_AND_WORLD_READABLE = 0o644
OWNER_ONLY = 0o600
EXPECTED_NONE = 0


def _make_env(path, mode=GROUP_AND_WORLD_READABLE):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("SUPABASE_SERVICE_KEY=pretend\n")
    os.chmod(path, mode)
    return path


def _reference_walk(root):
    """The traversal exactly as it shipped before 2026-09-08, kept only as an oracle."""
    max_depth = int(os.environ.get("ORCH_ENV_SWEEP_DEPTH", str(SWEEP_MAX_DEPTH)))
    root_depth = root.rstrip("/").count("/")
    found = set()
    for dirpath, dirnames, filenames in os.walk(root):
        if dirpath.count("/") - root_depth >= max_depth:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames
                       if d not in ("node_modules", ".git", "Library", ".venv", "venv")]
        for name in filenames:
            if name.startswith(".env") and not name.endswith((".example", ".sample")):
                found.add(os.path.join(dirpath, name))
    return found


def _hardened_by_sweep(root):
    """Which .env files the live sweep actually reached, read back from their modes."""
    before = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                before[path] = stat.S_IMODE(os.stat(path).st_mode)
            except OSError:
                continue
    bt.env_permission_sweep(root=root)
    reached = set()
    for path, old_mode in before.items():
        try:
            if stat.S_IMODE(os.stat(path).st_mode) != old_mode:
                reached.add(path)
        except OSError:
            continue
    return reached


def test_a_file_at_the_depth_cap_is_still_reached():
    """The off-by-one that shipped in the first draft and missed 10 real files."""
    with tempfile.TemporaryDirectory() as workspace:
        parts = [f"level{index}" for index in range(SWEEP_MAX_DEPTH)]
        deep = _make_env(os.path.join(workspace, *parts, ".env"))
        assert deep in _reference_walk(workspace), "the oracle must see it, or the test lies"
        assert stat.S_IMODE(os.stat(deep).st_mode) == OWNER_ONLY or deep in _hardened_by_sweep(
            workspace), "a .env at the depth cap must still be hardened"


def test_the_sweep_and_the_old_walk_reach_the_same_files():
    """A tree with worktree-shaped nesting, excluded dirs, templates and depth edges."""
    with tempfile.TemporaryDirectory() as workspace:
        _make_env(os.path.join(workspace, ".env"))
        _make_env(os.path.join(workspace, "proj-wt", "slug", "runner", ".env.local"))
        _make_env(os.path.join(workspace, "a", "b", "c", "d", ".env.bak.20260713"))
        _make_env(os.path.join(workspace, "node_modules", "pkg", ".env"))
        _make_env(os.path.join(workspace, "keep", ".env.example"))
        at_cap = [f"cap{index}" for index in range(SWEEP_MAX_DEPTH)]
        _make_env(os.path.join(workspace, *at_cap, ".env"))
        beyond = [f"deep{index}" for index in range(BEYOND_CAP)]
        _make_env(os.path.join(workspace, *beyond, ".env"))

        expected = _reference_walk(workspace)
        reached = _hardened_by_sweep(workspace)
        assert reached == expected, (
            f"walk diverged.\n  missed: {sorted(expected - reached)}\n"
            f"  extra:  {sorted(reached - expected)}")


def test_a_symlinked_directory_is_not_descended_into():
    """os.walk with followlinks=False does not recurse through a directory symlink.

    Reproduced deliberately: a loop here would hang the triage cycle, not slow it.
    """
    with tempfile.TemporaryDirectory() as workspace:
        real = os.path.join(workspace, "real")
        os.makedirs(real)
        hidden = _make_env(os.path.join(real, ".env"))
        os.chmod(hidden, OWNER_ONLY)
        link_parent = os.path.join(workspace, "links")
        os.makedirs(link_parent)
        os.symlink(real, os.path.join(link_parent, "pointer"))

        result = bt.env_permission_sweep(root=link_parent)
        assert result["scanned"] == EXPECTED_NONE, (
            "the sweep descended through a directory symlink; os.walk did not")


def test_a_symlinked_env_is_judged_by_its_targets_mode():
    """entry.stat() must FOLLOW the link, the way os.stat and os.chmod both do.

    A symlink's own mode is 0777 on macOS. Reading that instead of the target's would
    report every symlinked .env as insecure and rewrite a target that was already correct.
    """
    with tempfile.TemporaryDirectory() as workspace:
        target = _make_env(os.path.join(workspace, "store", ".env"), mode=OWNER_ONLY)
        link_dir = os.path.join(workspace, "app")
        os.makedirs(link_dir)
        os.symlink(target, os.path.join(link_dir, ".env"))

        result = bt.env_permission_sweep(root=link_dir)
        assert result["hardened"] == EXPECTED_NONE, (
            "an already-0600 target reached through a symlink was rewritten; the link's "
            "own mode was read instead of the target's")
        assert stat.S_IMODE(os.stat(target).st_mode) == OWNER_ONLY
