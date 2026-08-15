"""Every .env on this machine must stay owner-only, continuously.

Guards the 2026-08-02 finding: 45 .env files across the repos were group/world-readable
(0644). A one-time chmod does not hold — agent worktrees under {repo}-wt/ are created
and destroyed continuously and each new tree's .env lands with the default umask. 28 more
readable files had appeared within minutes of the first sweep. Permissions have to be
maintained, not fixed once.
"""
import os
import stat
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import blocked_triage as bt


def _mk(path, mode):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("SECRET=x\n")
    os.chmod(path, mode)


def test_readable_env_is_hardened():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "repo", ".env")
        _mk(p, 0o644)
        bt.env_permission_sweep(root=d)
        assert stat.S_IMODE(os.stat(p).st_mode) == 0o600


def test_worktree_copies_are_reached():
    """The regenerating case: {repo}-wt/{slug}/.env is where new readable files appear."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "proj-wt", "some-slug", ".env")
        _mk(p, 0o644)
        bt.env_permission_sweep(root=d)
        assert stat.S_IMODE(os.stat(p).st_mode) == 0o600


def test_env_variants_are_covered():
    with tempfile.TemporaryDirectory() as d:
        paths = [os.path.join(d, n) for n in
                 (".env.local", ".env.production.local", ".env.bak.20260713", ".env.growth")]
        for p in paths:
            _mk(p, 0o644)
        bt.env_permission_sweep(root=d)
        for p in paths:
            assert stat.S_IMODE(os.stat(p).st_mode) == 0o600, p


def test_templates_are_left_readable():
    """.env.example holds no secrets and is meant to be readable — do not touch it."""
    with tempfile.TemporaryDirectory() as d:
        for name in (".env.example", ".env.sample"):
            p = os.path.join(d, name)
            _mk(p, 0o644)
            bt.env_permission_sweep(root=d)
            assert stat.S_IMODE(os.stat(p).st_mode) == 0o644, name


def test_already_locked_files_are_not_reported_as_work():
    with tempfile.TemporaryDirectory() as d:
        _mk(os.path.join(d, ".env"), 0o600)
        r = bt.env_permission_sweep(root=d)
        assert r["hardened"] == 0
        assert r["scanned"] >= 1


def test_noisy_directories_are_skipped():
    """node_modules can hold thousands of files; walking it would make the sweep useless."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "node_modules", "pkg", ".env")
        _mk(p, 0o644)
        r = bt.env_permission_sweep(root=d)
        assert r["scanned"] == 0, "node_modules must not be walked"


def test_sweep_is_wired_into_the_triage_loop():
    src = open(bt.__file__, encoding="utf-8").read()
    assert "env_permission_sweep()" in src, "sweep is defined but never runs"
