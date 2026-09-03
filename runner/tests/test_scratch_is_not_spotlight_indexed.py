"""Spotlight must not index the fleet's throwaway build trees.

MEASURED 2026-09-03 on this Mac:

    mds_stores  76.6% CPU, continuously, for 1 day 2 hours
    mds         33.4% CPU
    mdfind      a query under ~/.orch-scratch did not return in three minutes

Roughly a permanent core and a bit, spent indexing content nobody will ever
search for: build overlays, staging checkouts and node_modules clones -- 76,928
files per clone, cloned again per merge candidate, then deleted. Each is an
FSEvents storm and an index update for files that live for minutes.

It costs more than the core. LOAD is what resource_governor clamps lanes on, and
with the box at load/core 2.5 the fleet was down to one task lane and one merge
worker -- so indexing throwaway trees directly costs merge throughput. Same
argument the CPU clamp and the orphan reapers already make.

Best-effort and reversible by design: deleting the marker restores indexing, and
nothing in the fleet depends on the exclusion having taken effect. The guaranteed
mechanism is System Settings -> Spotlight -> Privacy, which needs a person.
"""
import os

import pytest

import scratch


def test_the_default_root_is_noindex_suffixed():
    """The mechanism that actually works, after the marker demonstrably did not.

    8a6c0305 wrote `.metadata_never_index` and said plainly it was best-effort. Over
    the following hour on the same machine mds_stores read 76.6% -> 8.8% -> 132.7%:
    the marker is honoured at a volume root, not dependably for a directory. macOS
    DOES skip any directory whose NAME ends in `.noindex`, and that needs no admin
    password and no per-machine setup a new Mac could miss.
    """
    assert scratch.DEFAULT_ROOT.endswith(".noindex")
    assert not scratch.is_purgeable(scratch.DEFAULT_ROOT)


def test_the_legacy_root_is_still_recognised_as_fleet_owned():
    """An overlay left under the old name must still be reapable, not orphaned."""
    import resource_medic
    assert any(".orch-scratch/" in p for p in resource_medic._GATE_OWNED_PATHS)
    assert any(".orch-scratch.noindex/" in p for p in resource_medic._GATE_OWNED_PATHS)
    assert scratch.LEGACY_ROOT.endswith(".orch-scratch")


def test_an_explicitly_configured_root_still_wins(monkeypatch, tmp_path):
    """The default moved; ORCH_SCRATCH_ROOT is still authoritative."""
    monkeypatch.setattr(scratch, "is_purgeable", lambda path: False)
    chosen = tmp_path / "somewhere-else"
    monkeypatch.setenv("ORCH_SCRATCH_ROOT", str(chosen))
    assert scratch.root() == str(chosen)


def test_the_scratch_root_is_marked(monkeypatch, tmp_path):
    # pytest's tmp_path lives under /private/tmp, which scratch.root() refuses on
    # purpose -- that refusal is the point of this module and has its own test
    # below. Here we are testing the marking, so stand the purge check down for
    # this one call rather than pointing the suite at a real durable root.
    monkeypatch.setattr(scratch, "is_purgeable", lambda path: False)
    monkeypatch.setenv("ORCH_SCRATCH_ROOT", str(tmp_path / "scratch"))
    root = scratch.root()
    assert os.path.exists(os.path.join(root, scratch.NEVER_INDEX_MARKER))


def test_marking_is_idempotent(tmp_path):
    assert scratch.exclude_from_spotlight(str(tmp_path)) is True
    assert scratch.exclude_from_spotlight(str(tmp_path)) is True
    assert os.path.exists(os.path.join(str(tmp_path), scratch.NEVER_INDEX_MARKER))


def test_marking_an_unwritable_path_is_survivable():
    """Best-effort: a directory that cannot take the marker must not raise."""
    assert scratch.exclude_from_spotlight("/nonexistent/for/this/test") is False


def test_the_marker_does_not_disturb_what_lives_in_the_directory(tmp_path):
    (tmp_path / "build-overlay-x").mkdir()
    scratch.exclude_from_spotlight(str(tmp_path))
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == [scratch.NEVER_INDEX_MARKER, "build-overlay-x"]


def test_the_purgeable_root_guard_still_fires_first(monkeypatch):
    """A marker must never be written into a root we are about to refuse."""
    monkeypatch.setenv("ORCH_SCRATCH_ROOT", "/tmp/orch-should-be-refused")
    with pytest.raises(scratch.PurgeableScratchRoot):
        scratch.root()
    assert not os.path.exists(
        os.path.join("/tmp/orch-should-be-refused", scratch.NEVER_INDEX_MARKER))


def test_integration_worktrees_are_marked(monkeypatch, tmp_path):
    import integration_runtime
    monkeypatch.setattr(integration_runtime, "_home", lambda: str(tmp_path))
    path = integration_runtime._worktree_path(str(tmp_path))
    parent = os.path.dirname(path)
    assert os.path.basename(parent) == "integration-worktrees"
    assert os.path.exists(os.path.join(parent, scratch.NEVER_INDEX_MARKER))


def test_a_worktree_path_is_still_what_it_was(monkeypatch, tmp_path):
    """The marking must not change where a worktree goes -- paths are keys."""
    import hashlib
    import integration_runtime
    monkeypatch.setattr(integration_runtime, "_home", lambda: str(tmp_path))
    repo = str(tmp_path)
    expected_key = hashlib.sha256(os.path.realpath(repo).encode()).hexdigest()[:20]
    assert integration_runtime._worktree_path(repo).endswith(expected_key)
