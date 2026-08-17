"""Framework-type generation must use the linked toolchain, not download one.

Observed on the live fleet 2026-08-17, in the first release attempts after the stderr
digest made release notes legible again:

    [gate:qa] staging QA failed (tests required) — self-heal queued: QA overlay failed:
    Command '['bash', '-lc', 'npx nuxi prepare']' timed out after 180 seconds

QA runs in an ephemeral overlay -- a clean checkout of a git ref. node_modules is
gitignored, so the overlay has none, and _link_shared_runtime symlinks it at the worktree
ROOT only. _prepare_generated_types then runs once per PACKAGE root, so a monorepo
sub-package had no node_modules of its own and `npx nuxi` fell through to fetching nuxi
from the registry -- which is what actually consumed the 180 seconds.

This is the same class as the July failures that destroyed ~2,000 releases:
`sh: tsc: command not found`, `sh: expo: command not found`, `sh: nuxt: command not found`.
The toolchain was present; the command could not see it.
"""

import os
import stat
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import release_train as rt


def _make_bin(root, name):
    d = os.path.join(root, "node_modules", ".bin")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    with open(p, "w") as fh:
        fh.write("#!/bin/sh\nexit 0\n")
    os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
    return p


def test_finds_the_binary_in_the_same_directory(tmp_path):
    root = str(tmp_path)
    want = _make_bin(root, "nuxi")
    assert rt._local_bin(root, "nuxi") == want


def test_walks_up_to_the_worktree_root(tmp_path):
    """The actual failure: node_modules linked at the top, prepare run in a sub-package."""
    root = str(tmp_path)
    want = _make_bin(root, "nuxi")
    pkg = os.path.join(root, "packages", "web")
    os.makedirs(pkg)
    assert rt._local_bin(pkg, "nuxi", stop_at=root) == want


def test_does_not_escape_above_the_worktree(tmp_path):
    """Never pick up a binary from outside the checkout under test."""
    outer = tmp_path / "outer"
    inner = outer / "worktree" / "pkg"
    inner.mkdir(parents=True)
    _make_bin(str(outer), "nuxi")            # deliberately above the worktree
    assert rt._local_bin(str(inner), "nuxi", stop_at=str(outer / "worktree")) is None


def test_returns_none_when_absent(tmp_path):
    assert rt._local_bin(str(tmp_path), "nuxi") is None


def test_never_raises_on_junk():
    assert rt._local_bin(None, "nuxi") is None
    assert rt._local_bin(12345, "nuxi") is None


def test_prefers_the_local_binary_over_npx(tmp_path):
    root = str(tmp_path)
    want = _make_bin(root, "nuxi")
    cmd, how = rt._prepare_cmd(root, root)
    assert cmd == [want, "prepare"], cmd
    assert "npx" not in how
    assert "bash" not in cmd, "no login shell when the binary is right there"


def test_falls_back_to_npx_without_installing(tmp_path):
    """A missing toolchain must fail fast, not silently download for minutes."""
    root = str(tmp_path)
    cmd, how = rt._prepare_cmd(root, root)
    joined = " ".join(cmd)
    assert "npx" in joined
    assert "--no-install" in joined, "npx must not be allowed to fetch from the registry"


def test_nuxt_is_accepted_when_nuxi_is_missing(tmp_path):
    root = str(tmp_path)
    want = _make_bin(root, "nuxt")
    cmd, _how = rt._prepare_cmd(root, root)
    assert cmd == [want, "prepare"]


def test_timeout_is_configurable_and_longer_than_the_old_hardcoded_180(monkeypatch):
    assert rt.PREPARE_TIMEOUT_S > 180, "180s was too tight for a cold prepare"


def test_source_no_longer_downloads_the_toolchain():
    """Guard against `npx nuxi prepare` (installing form) coming back."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "release_train.py")).read()
    assert "npx nuxi prepare" not in src, "bare npx re-introduced; it downloads and times out"
    # Anchored to the prepare call specifically. A bare "timeout=180" substring also matches
    # the unrelated timeout=1800 on _qa_ref, which would make this fail for the wrong reason.
    assert "timeout=180)" not in src, "the 180s hard-coded prepare timeout is back"
    assert "PREPARE_TIMEOUT_S" in src, "prepare timeout must stay configurable"
