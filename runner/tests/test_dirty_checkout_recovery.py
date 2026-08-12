#!/usr/bin/env python3
"""Coverage for dirty_checkout_recovery.

Required scenarios (from the queue task): clean fast-forward, valid dirty layer,
invalid dirty layer, concurrent writer, upstream overlap. Plus the standing
sacred-checkout invariants: untracked operator evidence is never touched, and nothing
is ever stashed or hard-reset away.
"""
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dirty_checkout_recovery as dcr  # noqa: E402


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          timeout=60)


def _write(root, rel, text):
    full = os.path.join(root, rel)
    os.makedirs(os.path.dirname(full) or root, exist_ok=True)
    with open(full, "w") as fh:
        fh.write(text)


def _read(root, rel):
    with open(os.path.join(root, rel)) as fh:
        return fh.read()


def _head(root, ref="HEAD"):
    return _git(root, "rev-parse", ref).stdout.strip()


@pytest.fixture
def fleet(tmp_path):
    """An 'upstream' repo plus a local clone standing in for the orchestrator host."""
    upstream = str(tmp_path / "upstream")
    os.makedirs(upstream)
    _git(upstream, "init", "-q", "-b", "master", ".")
    _git(upstream, "config", "user.name", "t")
    _git(upstream, "config", "user.email", "t@t")
    _write(upstream, "runner/mod.py", "VALUE = 1\n")
    _write(upstream, "runner/other.py", "OTHER = 1\n")
    _git(upstream, "add", "-A")
    _git(upstream, "commit", "-q", "-m", "base")

    host = str(tmp_path / "host")
    _git(str(tmp_path), "clone", "-q", upstream, host)
    _git(host, "config", "user.name", "t")
    _git(host, "config", "user.email", "t@t")
    yield {"upstream": upstream, "host": host}


def _advance_upstream(upstream, rel="runner/other.py", text="OTHER = 2\n", msg="upstream"):
    _write(upstream, rel, text)
    _git(upstream, "add", "-A")
    _git(upstream, "commit", "-q", "-m", msg)


# ── inventory ───────────────────────────────────────────────────────────────

def test_inventory_clean(fleet):
    inv = dcr.inventory(fleet["host"])
    assert inv["clean"] is True
    assert inv["tracked"] == []


def test_inventory_separates_tracked_from_untracked(fleet):
    host = fleet["host"]
    _write(host, "runner/mod.py", "VALUE = 99\n")
    _write(host, "OPERATOR_NOTES.md", "do not delete\n")
    inv = dcr.inventory(host)
    assert [c["path"] for c in inv["tracked"]] == ["runner/mod.py"]
    assert "OPERATOR_NOTES.md" in inv["untracked"]
    assert inv["clean"] is False


def test_inventory_fail_soft_on_non_repo(tmp_path):
    inv = dcr.inventory(str(tmp_path))
    assert inv["head"] == ""
    assert inv["clean"] is True


# ── validation ──────────────────────────────────────────────────────────────

def test_validate_flags_markers_and_syntax(tmp_path):
    root = str(tmp_path)
    _write(root, "a.py", "x = 1\n<<<<<<< HEAD\n")
    _write(root, "b.py", "def broken(:\n")
    _write(root, "c.py", "ok = True\n")
    problems = dcr.validate_paths(root, ["a.py", "b.py", "c.py"])
    joined = " ".join(problems)
    assert "conflict marker" in joined
    assert "SyntaxError" in joined
    assert "c.py" not in joined


def test_validate_ignores_deleted_paths(tmp_path):
    assert dcr.validate_paths(str(tmp_path), ["gone.py"]) == []


# ── preservation ────────────────────────────────────────────────────────────

def test_preserve_creates_recovery_ref_without_moving_head(fleet):
    host = fleet["host"]
    before = _head(host)
    _write(host, "runner/mod.py", "VALUE = 42\n")
    out = dcr.preserve(host, ["runner/mod.py"])
    assert out["error"] is None
    assert out["ref"].startswith("refs/recovery/dirty/")
    assert _head(host) == before, "preservation must not move HEAD"
    # The content is genuinely recoverable from the ref.
    blob = _git(host, "show", f"{out['sha']}:runner/mod.py").stdout
    assert blob == "VALUE = 42\n"
    # And the working tree still has it.
    assert _read(host, "runner/mod.py") == "VALUE = 42\n"


def test_preserve_leaves_index_untouched(fleet):
    host = fleet["host"]
    _write(host, "runner/mod.py", "VALUE = 42\n")
    _write(host, "runner/other.py", "OTHER = 42\n")
    _git(host, "add", "runner/mod.py")  # operator staged one of the two
    staged_before = _git(host, "diff", "--cached", "--name-only").stdout
    dcr.preserve(host, ["runner/mod.py", "runner/other.py"])
    assert _git(host, "diff", "--cached", "--name-only").stdout == staged_before


# ── scenario 1: clean fast-forward ──────────────────────────────────────────

def test_clean_fast_forward(fleet):
    host, upstream = fleet["host"], fleet["upstream"]
    _advance_upstream(upstream)
    card = dcr.recover(host, "master")
    assert card["outcome"] == "fast-forward", card
    assert card["sha_after"] != card["sha_before"]
    assert _read(host, "runner/other.py") == "OTHER = 2\n"
    assert dcr.inventory(host)["clean"] is True


def test_noop_when_current_and_clean(fleet):
    card = dcr.recover(fleet["host"], "master")
    assert card["outcome"] == "noop"


# ── scenario 2: valid dirty layer ───────────────────────────────────────────

def test_valid_dirty_layer_converges_clean_without_loss(fleet):
    host, upstream = fleet["host"], fleet["upstream"]
    _advance_upstream(upstream)  # host is now behind
    _write(host, "runner/mod.py", "VALUE = 'local work'\n")

    card = dcr.recover(host, "master")

    assert card["outcome"] == "layered", card
    assert card["recovery_ref"]
    # Both sides survive.
    assert _read(host, "runner/mod.py") == "VALUE = 'local work'\n"
    assert _read(host, "runner/other.py") == "OTHER = 2\n"
    # And we resumed from a clean checkout.
    assert dcr.inventory(host)["clean"] is True
    assert card["sha_after"] != card["sha_before"]


def test_valid_dirty_layer_multi_commit_behind(fleet):
    """The reported live shape: many commits behind, compatible local edits."""
    host, upstream = fleet["host"], fleet["upstream"]
    for i in range(16):
        _advance_upstream(upstream, "runner/other.py", f"OTHER = {i}\n", f"c{i}")
    _write(host, "runner/mod.py", "VALUE = 'local'\n")

    card = dcr.recover(host, "master")
    assert card["outcome"] == "layered", card
    assert _read(host, "runner/mod.py") == "VALUE = 'local'\n"
    assert _read(host, "runner/other.py") == "OTHER = 15\n"
    assert dcr.inventory(host)["clean"] is True


# ── scenario 3: invalid dirty layer ─────────────────────────────────────────

def test_invalid_dirty_layer_is_quarantined_not_promoted(fleet):
    host, upstream = fleet["host"], fleet["upstream"]
    _advance_upstream(upstream)
    _write(host, "runner/mod.py", "def broken(:\n")
    before = _head(host)

    card = dcr.recover(host, "master")

    assert card["outcome"] == "quarantined", card
    assert card["quarantine_ref"]
    assert any("SyntaxError" in p for p in card["tests"])
    # Broken code never became history on the base branch...
    assert _head(host) == before
    # ...and the operator's bytes are still exactly where they left them.
    assert _read(host, "runner/mod.py") == "def broken(:\n"


def test_conflict_markers_in_dirt_are_quarantined(fleet):
    host, upstream = fleet["host"], fleet["upstream"]
    _advance_upstream(upstream)
    _write(host, "runner/mod.py", "<<<<<<< HEAD\nVALUE = 1\n=======\nVALUE = 2\n>>>>>>> x\n")
    card = dcr.recover(host, "master")
    assert card["outcome"] == "quarantined"
    assert any("conflict marker" in p for p in card["tests"])


def test_quarantined_work_is_recoverable_from_the_ref(fleet):
    host, upstream = fleet["host"], fleet["upstream"]
    _advance_upstream(upstream)
    _write(host, "runner/mod.py", "def broken(:\n")
    card = dcr.recover(host, "master")
    ref = card["quarantine_ref"]
    assert _git(host, "show", f"{ref}:runner/mod.py").stdout == "def broken(:\n"


# ── scenario 4: upstream overlap ────────────────────────────────────────────

def test_upstream_overlap_conflicting_is_quarantined(fleet):
    """Upstream edited the same lines we did — do not silently pick a winner."""
    host, upstream = fleet["host"], fleet["upstream"]
    _advance_upstream(upstream, "runner/mod.py", "VALUE = 'upstream wins'\n")
    _write(host, "runner/mod.py", "VALUE = 'local wins'\n")
    before = _head(host)

    card = dcr.recover(host, "master")

    assert card["outcome"] == "quarantined", card
    assert card["recovery_ref"]
    assert _head(host) == before
    assert _read(host, "runner/mod.py") == "VALUE = 'local wins'\n"
    assert "does not apply" in " ".join(card["problems"]) or card["problems"]


def test_upstream_overlap_compatible_layers_and_is_reported(fleet):
    """Same FILE, non-colliding regions: compatible work must layer, and the overlap
    must still be named on the card so a human can see what was touched twice."""
    host, upstream = fleet["host"], fleet["upstream"]
    _write(upstream, "runner/mod.py", "HEADER = 0\n" + ("PAD = 0\n" * 30) + "VALUE = 1\n")
    _git(upstream, "add", "-A")
    _git(upstream, "commit", "-q", "-m", "pad")
    _git(host, "pull", "-q", "origin", "master")

    _advance_upstream(upstream, "runner/mod.py",
                      "HEADER = 'upstream'\n" + ("PAD = 0\n" * 30) + "VALUE = 1\n")
    _write(host, "runner/mod.py",
           "HEADER = 0\n" + ("PAD = 0\n" * 30) + "VALUE = 'local'\n")

    card = dcr.recover(host, "master")

    assert card["outcome"] == "layered", card
    assert "runner/mod.py" in card["overlap"]
    body = _read(host, "runner/mod.py")
    assert "HEADER = 'upstream'" in body
    assert "VALUE = 'local'" in body
    assert dcr.inventory(host)["clean"] is True


# ── scenario 5: concurrent writer ───────────────────────────────────────────

def test_concurrent_writer_holding_the_fence_defers(fleet, monkeypatch):
    import contextlib

    @contextlib.contextmanager
    def busy(repo, timeout=None):
        yield False

    fake = type("M", (), {"hold": staticmethod(busy)})
    monkeypatch.setitem(sys.modules, "repo_lock", fake)

    host, upstream = fleet["host"], fleet["upstream"]
    _advance_upstream(upstream)
    _write(host, "runner/mod.py", "VALUE = 'local'\n")
    before = _head(host)

    card = dcr.recover(host, "master")

    assert card["outcome"] == "blocked"
    assert "fence busy" in card["error"]
    assert _head(host) == before
    assert _read(host, "runner/mod.py") == "VALUE = 'local'\n"


def test_missing_lock_module_fails_soft_to_unlocked(fleet, monkeypatch):
    """A lock bug must not become a fleet outage."""
    import builtins
    real_import = builtins.__import__

    def no_repo_lock(name, *a, **k):
        if name == "repo_lock":
            raise ImportError("simulated")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_repo_lock)
    _advance_upstream(fleet["upstream"])
    card = dcr.recover(fleet["host"], "master")
    assert card["outcome"] == "fast-forward", card


# ── sacred-checkout invariants ──────────────────────────────────────────────

def test_untracked_operator_evidence_is_never_touched(fleet):
    host, upstream = fleet["host"], fleet["upstream"]
    _advance_upstream(upstream)
    _write(host, "intake/PROMPT-critical.md", "operator evidence\n")
    _write(host, "runner/mod.py", "VALUE = 'local'\n")

    card = dcr.recover(host, "master")

    assert os.path.isfile(os.path.join(host, "intake/PROMPT-critical.md"))
    assert _read(host, "intake/PROMPT-critical.md") == "operator evidence\n"
    assert "intake/PROMPT-critical.md" in card["untracked_preserved"]


def test_recovery_never_stashes(fleet):
    host, upstream = fleet["host"], fleet["upstream"]
    _advance_upstream(upstream)
    _write(host, "runner/mod.py", "VALUE = 'local'\n")
    dcr.recover(host, "master")
    assert _git(host, "stash", "list").stdout.strip() == "", \
        "recovery must resolve, not defer onto the stash pile"


def test_dry_run_changes_nothing(fleet):
    host, upstream = fleet["host"], fleet["upstream"]
    _advance_upstream(upstream)
    _write(host, "runner/mod.py", "VALUE = 'local'\n")
    before = _head(host)
    card = dcr.recover(host, "master", dry_run=True)
    assert card["outcome"].endswith("dry-run")
    assert _head(host) == before
    assert _read(host, "runner/mod.py") == "VALUE = 'local'\n"


# ── incident card + fail-soft surface ───────────────────────────────────────

def test_card_carries_before_after_and_files(fleet):
    host, upstream = fleet["host"], fleet["upstream"]
    _advance_upstream(upstream)
    _write(host, "runner/mod.py", "VALUE = 'local'\n")
    card = dcr.recover(host, "master")
    assert card["sha_before"] and card["sha_after"]
    assert card["changed_files"] == ["runner/mod.py"]
    assert card["host"]
    assert card["card_path"] and os.path.isfile(card["card_path"])


def test_kill_switch(fleet, monkeypatch):
    monkeypatch.setenv("ORCH_DIRTY_RECOVERY_ENABLED", "false")
    card = dcr.recover(fleet["host"], "master")
    assert card["outcome"] == "blocked"
    assert "disabled" in card["error"]


def test_non_repo_is_fail_soft(tmp_path):
    card = dcr.recover(str(tmp_path), "master")
    assert card["outcome"] == "blocked"
    assert card["error"]


def test_missing_upstream_ref_is_fail_soft(fleet):
    card = dcr.recover(fleet["host"], "no-such-base", fetch=False)
    assert card["outcome"] == "blocked"
    assert "upstream ref not found" in card["error"]
