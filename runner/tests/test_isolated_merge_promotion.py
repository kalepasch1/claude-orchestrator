#!/usr/bin/env python3
"""Regression coverage for isolated_merge_promotion.

The load-bearing assertion of this file: a resolution that produces conflict markers
(or otherwise invalid code) CANNOT plant them in the live runner checkout. The live
working tree and the running commit must be byte-identical before and after a failed
promotion.
"""
import os
import subprocess
import sys
import tempfile
import shutil

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import isolated_merge_promotion as imp  # noqa: E402


# ── fixtures ────────────────────────────────────────────────────────────────

def _run(args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=60)


def _write(repo, rel, text):
    full = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as fh:
        fh.write(text)


def _commit(repo, msg):
    _run(["git", "add", "-A"], repo)
    _run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", msg], repo)


def _head(repo, ref="HEAD"):
    r = _run(["git", "rev-parse", ref], repo)
    return r.stdout.strip()


@pytest.fixture
def repo():
    path = tempfile.mkdtemp(prefix="imp-repo-")
    _run(["git", "init", "-q", "-b", "master", "."], path)
    _run(["git", "config", "user.name", "t"], path)
    _run(["git", "config", "user.email", "t@t"], path)
    _write(path, "runner/mod.py", "VALUE = 1\n")
    _commit(path, "base")
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _diverge(repo, ours, theirs):
    """Create master/feature edits to runner/mod.py that conflict."""
    _run(["git", "checkout", "-q", "-b", "feature"], repo)
    _write(repo, "runner/mod.py", theirs)
    _commit(repo, "feature edit")
    _run(["git", "checkout", "-q", "master"], repo)
    _write(repo, "runner/mod.py", ours)
    _commit(repo, "master edit")


# ── conflict-marker scanning ────────────────────────────────────────────────

def test_scan_finds_real_markers(repo):
    _write(repo, "runner/bad.py", "a = 1\n<<<<<<< HEAD\nb = 2\n=======\nb = 3\n>>>>>>> feature\n")
    _commit(repo, "markers")
    found = imp.scan_conflict_markers(repo)
    paths = {p for p, _, _ in found}
    assert "runner/bad.py" in paths
    assert len(found) == 3


def test_scan_is_exact_not_substring(repo):
    """Seven '=' inside prose, or six markers, must not trip the scan."""
    _write(repo, "docs.md", "Heading\n======\nnot a marker\n")
    _write(repo, "runner/ok.py", "S = 'a<<<<<<< inline'\n")
    _commit(repo, "lookalikes")
    found = imp.scan_conflict_markers(repo)
    assert [f for f in found if f[0] in ("docs.md", "runner/ok.py")] == []


def test_scan_reports_line_numbers(repo):
    _write(repo, "runner/bad.py", "x = 1\ny = 2\n<<<<<<< HEAD\n")
    _commit(repo, "m")
    found = [f for f in imp.scan_conflict_markers(repo) if f[0] == "runner/bad.py"]
    assert found[0][1] == 3


def test_scan_skips_binaries(repo):
    with open(os.path.join(repo, "blob.png"), "wb") as fh:
        fh.write(b"\x89PNG\x00<<<<<<< HEAD\n")
    _commit(repo, "binary")
    assert [f for f in imp.scan_conflict_markers(repo) if f[0] == "blob.png"] == []


def test_scan_fail_soft_on_missing_tree():
    assert imp.scan_conflict_markers("/nonexistent/path/xyz") == []


# ── compile / import smoke ──────────────────────────────────────────────────

def test_compile_smoke_catches_syntax_error(repo):
    _write(repo, "runner/broken.py", "def f(:\n")
    errs = imp.compile_smoke(repo, ["runner/broken.py"])
    assert errs and "SyntaxError" in errs[0]


def test_compile_smoke_clean_file(repo):
    assert imp.compile_smoke(repo, ["runner/mod.py"]) == []


def test_compile_smoke_ignores_non_python(repo):
    _write(repo, "notes.txt", "def f(:\n")
    assert imp.compile_smoke(repo, ["notes.txt"]) == []


def test_import_smoke_no_python_changes(repo):
    assert imp.import_smoke(repo, ["README.md"]) == []


# ── affected-test selection ─────────────────────────────────────────────────

def test_affected_tests_picks_sibling(repo):
    _write(repo, "runner/tests/test_mod.py", "def test_x():\n    assert True\n")
    _commit(repo, "t")
    assert "runner/tests/test_mod.py" in imp.affected_tests(repo, ["runner/mod.py"])


def test_affected_tests_bounded(repo):
    names = []
    for i in range(20):
        _write(repo, f"runner/tests/test_m{i}.py", "def test_x():\n    assert True\n")
        names.append(f"runner/tests/test_m{i}.py")
    _commit(repo, "many")
    assert len(imp.affected_tests(repo, names)) <= imp.MAX_AFFECTED_TESTS


# ── THE load-bearing regression: a bad resolution cannot reach the live tree ──

def test_failed_resolution_leaves_live_checkout_untouched(repo, monkeypatch):
    """Synthetic bad resolution: the resolver 'succeeds' but plants markers.

    The live checkout's HEAD, its working-tree bytes, and master itself must all be
    unchanged, and the poisoned result must be recoverable from a quarantine ref.
    """
    _diverge(repo, "VALUE = 'ours'\n", "VALUE = 'theirs'\n")
    head_before = _head(repo)
    master_before = _head(repo, "master")
    with open(os.path.join(repo, "runner/mod.py")) as fh:
        bytes_before = fh.read()

    class FakeResolver:
        @staticmethod
        def resolve_branch(tree, branch, base, dry_run=False):
            # Simulate a resolver that commits a tree still containing markers.
            _write(tree, "runner/mod.py",
                   "<<<<<<< HEAD\nVALUE = 'ours'\n=======\nVALUE = 'theirs'\n>>>>>>> feature\n")
            _run(["git", "add", "-A"], tree)
            _run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                  "commit", "-m", "bad auto-resolve"], tree)
            return {"merged": True, "strategy": "auto", "resolved_files": ["runner/mod.py"]}

        @staticmethod
        def verify_merge(*a, **k):
            return ""

    monkeypatch.setitem(sys.modules, "auto_conflict_resolver", FakeResolver)

    out = imp.promote_merge(repo, "feature", "master", run_tests=False)

    assert out["promoted"] is False
    assert "conflict markers" in (out["error"] or "")
    assert out["quarantine_ref"], "the failed result must be preserved, not discarded"

    # The live checkout is exactly as we left it.
    assert _head(repo) == head_before
    assert _head(repo, "master") == master_before
    with open(os.path.join(repo, "runner/mod.py")) as fh:
        assert fh.read() == bytes_before
    assert imp.scan_conflict_markers(repo) == []
    # The branch is still there — it may be the only copy of that work.
    assert _head(repo, "feature")


def test_failed_compile_is_quarantined_not_promoted(repo, monkeypatch):
    _diverge(repo, "VALUE = 'ours'\n", "VALUE = 'theirs'\n")
    master_before = _head(repo, "master")

    class FakeResolver:
        @staticmethod
        def resolve_branch(tree, branch, base, dry_run=False):
            _write(tree, "runner/mod.py", "def broken(:\n")
            _run(["git", "add", "-A"], tree)
            _run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                  "commit", "-m", "syntax-broken resolve"], tree)
            return {"merged": True, "strategy": "auto", "resolved_files": ["runner/mod.py"]}

        @staticmethod
        def verify_merge(*a, **k):
            return ""

    monkeypatch.setitem(sys.modules, "auto_conflict_resolver", FakeResolver)
    out = imp.promote_merge(repo, "feature", "master", run_tests=False)

    assert out["promoted"] is False
    assert "compile" in (out["error"] or "").lower()
    assert _head(repo, "master") == master_before
    assert out["quarantine_ref"]


def test_anti_loss_gate_failure_blocks_promotion(repo, monkeypatch):
    _diverge(repo, "VALUE = 'ours'\n", "VALUE = 'theirs'\n")
    master_before = _head(repo, "master")

    class FakeResolver:
        @staticmethod
        def resolve_branch(tree, branch, base, dry_run=False):
            _write(tree, "runner/mod.py", "VALUE = 'merged'\n")
            _run(["git", "add", "-A"], tree)
            _run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                  "commit", "-m", "clean resolve"], tree)
            return {"merged": True, "strategy": "auto", "resolved_files": ["runner/mod.py"]}

        @staticmethod
        def verify_merge(*a, **k):
            return "regression guard: symbol VALUE_OLD lost"

    monkeypatch.setitem(sys.modules, "auto_conflict_resolver", FakeResolver)
    out = imp.promote_merge(repo, "feature", "master", run_tests=False)
    assert out["promoted"] is False
    assert "anti-loss" in (out["error"] or "")
    assert _head(repo, "master") == master_before


def test_crashing_gate_fails_closed(repo, monkeypatch):
    _diverge(repo, "VALUE = 'ours'\n", "VALUE = 'theirs'\n")
    master_before = _head(repo, "master")

    class FakeResolver:
        @staticmethod
        def resolve_branch(tree, branch, base, dry_run=False):
            _write(tree, "runner/mod.py", "VALUE = 'merged'\n")
            _run(["git", "add", "-A"], tree)
            _run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                  "commit", "-m", "clean"], tree)
            return {"merged": True, "strategy": "auto"}

        @staticmethod
        def verify_merge(*a, **k):
            raise RuntimeError("guard exploded")

    monkeypatch.setitem(sys.modules, "auto_conflict_resolver", FakeResolver)
    out = imp.promote_merge(repo, "feature", "master", run_tests=False)
    assert out["promoted"] is False
    assert "fail-closed" in (out["error"] or "")
    assert _head(repo, "master") == master_before


# ── the happy path still promotes ───────────────────────────────────────────

def test_valid_resolution_promotes_atomically(repo, monkeypatch):
    _diverge(repo, "VALUE = 'ours'\n", "VALUE = 'theirs'\n")
    master_before = _head(repo, "master")
    live_head_before = _head(repo)

    class FakeResolver:
        @staticmethod
        def resolve_branch(tree, branch, base, dry_run=False):
            _write(tree, "runner/mod.py", "VALUE = 'ours-and-theirs'\n")
            _run(["git", "add", "-A"], tree)
            _run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                  "commit", "-m", "good resolve"], tree)
            return {"merged": True, "strategy": "auto", "resolved_files": ["runner/mod.py"]}

        @staticmethod
        def verify_merge(*a, **k):
            return ""

    monkeypatch.setitem(sys.modules, "auto_conflict_resolver", FakeResolver)
    out = imp.promote_merge(repo, "feature", "master", run_tests=False)

    assert out["promoted"] is True, out
    assert out["base_after"] and out["base_after"] != master_before
    assert _head(repo, "master") == out["base_after"]
    # The live *working tree* was never checked out onto the new commit by us.
    assert _head(repo) == live_head_before or _head(repo) == out["base_after"]


def test_dry_run_does_not_move_base(repo, monkeypatch):
    _diverge(repo, "VALUE = 'ours'\n", "VALUE = 'theirs'\n")
    master_before = _head(repo, "master")

    class FakeResolver:
        @staticmethod
        def resolve_branch(tree, branch, base, dry_run=False):
            _write(tree, "runner/mod.py", "VALUE = 'x'\n")
            _run(["git", "add", "-A"], tree)
            _run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                  "commit", "-m", "r"], tree)
            return {"merged": True, "strategy": "auto"}

        @staticmethod
        def verify_merge(*a, **k):
            return ""

    monkeypatch.setitem(sys.modules, "auto_conflict_resolver", FakeResolver)
    out = imp.promote_merge(repo, "feature", "master", run_tests=False, dry_run=True)
    assert out["promoted"] is False
    assert _head(repo, "master") == master_before


# ── fail-soft surface ───────────────────────────────────────────────────────

def test_missing_repo_is_fail_soft():
    out = imp.promote_merge("/nonexistent/xyz", "b", "master")
    assert out["promoted"] is False
    assert out["error"]


def test_missing_branch_is_fail_soft(repo):
    out = imp.promote_merge(repo, "no-such-branch", "master")
    assert out["promoted"] is False
    assert "branch ref not found" in out["error"]


def test_kill_switch_disables(repo, monkeypatch):
    monkeypatch.setenv("ORCH_ISOLATED_PROMOTION_ENABLED", "false")
    out = imp.promote_merge(repo, "master", "master")
    assert out["promoted"] is False
    assert "disabled" in out["error"]


def test_worktree_is_cleaned_up(repo, monkeypatch):
    _diverge(repo, "VALUE = 'ours'\n", "VALUE = 'theirs'\n")

    class FakeResolver:
        @staticmethod
        def resolve_branch(tree, branch, base, dry_run=False):
            return {"merged": False, "strategy": "manual", "error": "manual review"}

    monkeypatch.setitem(sys.modules, "auto_conflict_resolver", FakeResolver)
    out = imp.promote_merge(repo, "feature", "master", run_tests=False)
    assert out["worktree"]
    assert not os.path.isdir(out["worktree"]), "isolated worktree must not accumulate"
