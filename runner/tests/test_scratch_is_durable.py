"""Durable scratch, because macOS purged /tmp out from under a running build.

On 2026-09-01 the purge ran MID-SESSION and destroyed two live git worktrees and
one commit that had not been pushed. TMPDIR is empty on these machines, so every
tempfile.mkdtemp() in the fleet was landing in /tmp — including the build overlay
that holds an exact commit for the twenty-five minutes a production build takes
on a loaded Mac.

The tests that matter here are the ones that FAIL if that comes back. The
behavioural version — "did the directory survive?" — cannot be written: it needs
the OS to purge, and it would pass every time until the day it mattered.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import commit_overlay  # noqa: E402
import scratch  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("ORCH_SCRATCH_ROOT", raising=False)


def test_every_purgeable_root_is_recognised():
    # /var/folders is macOS's normal per-user TMPDIR. It is purged too, just less
    # eagerly — and "less eagerly" is not a guarantee a 25-minute build can lean on.
    for p in ("/tmp", "/tmp/x", "/private/tmp/build-overlay-abc", "/var/folders/aa/bb/T/x",
              "/private/var/folders/aa/bb/T/x", "/var/tmp/y", "/dev/shm/z"):
        assert scratch.is_purgeable(p), p


def test_the_durable_root_is_not_purgeable():
    assert not scratch.is_purgeable(scratch.DEFAULT_ROOT)
    assert not scratch.is_purgeable(scratch.root())


def test_a_purgeable_root_is_refused_rather_than_obeyed(monkeypatch):
    # Silently accepting /tmp would reintroduce the exact bug while LOOKING
    # configured, which is worse than not having the setting at all.
    monkeypatch.setenv("ORCH_SCRATCH_ROOT", "/tmp/orch")
    with pytest.raises(scratch.PurgeableScratchRoot):
        scratch.root()


def test_mkdtemp_lands_somewhere_durable():
    d = scratch.mkdtemp(prefix="pytest-")
    try:
        assert os.path.isdir(d)
        assert not scratch.is_purgeable(d), d
    finally:
        os.rmdir(d)


def test_symlinked_paths_cannot_smuggle_a_purgeable_root(tmp_path, monkeypatch):
    # /tmp is itself a symlink to /private/tmp on macOS. Comparing strings without
    # resolving would call one of those durable and the other not.
    link = tmp_path / "sneaky"
    os.symlink("/tmp", link)
    assert scratch.is_purgeable(str(link))


def test_the_build_overlay_uses_it():
    # This is the one that matters: build_gate materializes the commit under test
    # here and runs the production build inside it. Asserted structurally because
    # the failure it prevents only appears when the OS decides to purge.
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "commit_overlay.py"), encoding="utf-8").read()
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    body = code[code.index("def materialize("):]
    assert "tempfile.mkdtemp(" not in body.split("def _mkdtemp")[0] or "_mkdtemp(" in body, \
        "materialize() and checkout() must allocate through _mkdtemp, not tempfile directly"
    assert 'destination or _mkdtemp(' in code
    assert 'root = _mkdtemp(' in code


def test_the_overlay_actually_materializes_outside_tmp(tmp_path):
    repo = os.path.expanduser("~/Documents/smarter")
    if not os.path.isdir(os.path.join(repo, ".git")):
        pytest.skip("smarter checkout not present on this machine")
    with commit_overlay.checkout(repo, "HEAD", prefix="pytest-overlay-") as o:
        assert not scratch.is_purgeable(o["path"]), o["path"]
        assert o["files"], "overlay materialized no files"
