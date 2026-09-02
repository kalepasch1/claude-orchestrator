"""The suite proof, recorded under the name the guard actually reads.

The fourth layer of one failure, and it only became visible when the three above it
stopped failing first. sustainable-barks' promotion, through the real hook:

    production_push_guard: INTEGRATED — promoting the tip of origin/orchestrator/dev
    production_push_guard: CONTENT OK — content sane: 191 -> 253 files
    production_push_guard: BUILD GREEN — reused green build proof for 11fad7ff6a31
    production_push_guard: BLOCKED — production push without a green suite

verify_tests() asks proof_graph for kind="test" under detect_test_cmd(repo). The
release train recorded kind="qa" under its own qa_cmd. Same commit, same tree, a name
the reader never asks for -- the identical mismatch _persist_production_build_proof()
was written to fix for the BUILD proof, still live for the SUITE.

WHAT THIS MUST NEVER DO is the point of most of these tests. sustainable-barks'
configured test_cmd is literally `true`, while the guard wants `npm run test`. Writing
a kind="test" proof from a `true` run would certify that a no-op passed. A proof that
can be fabricated is worse than no proof at all, so the mismatch is REPORTED -- the
release fails with a sentence naming both commands instead of with git's "failed to
push some refs".
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import release_train  # noqa: E402


@pytest.fixture
def recorded(monkeypatch):
    """Capture what would be written to the proof graph."""
    rows = []

    class _PG:
        @staticmethod
        def record_verification(repo, commit, command, kind, success):
            rows.append({"repo": repo, "commit": commit, "command": command,
                         "kind": kind, "success": success})

        @staticmethod
        def reusable_verification(repo, commit, command, kind, limit=5000):
            return next((r for r in rows if r["commit"] == commit
                         and r["command"] == command and r["kind"] == kind), None)

    monkeypatch.setitem(sys.modules, "proof_graph", _PG)
    return rows


def _guard(monkeypatch, test_cmd):
    class _G:
        @staticmethod
        def detect_test_cmd(repo):
            return test_cmd
    monkeypatch.setitem(sys.modules, "production_push_guard", _G)


SHA = "a" * 40


# ── the fix ───────────────────────────────────────────────────────────────────

def test_the_proof_is_recorded_under_the_kind_the_guard_reads(monkeypatch, recorded):
    _guard(monkeypatch, "npm run test")
    ok, note = release_train._persist_production_test_proof("/repo", SHA, "npm run test")
    assert ok, note
    assert recorded and recorded[0]["kind"] == "test", (
        "recorded under a kind verify_tests() never asks for")
    assert recorded[0]["command"] == "npm run test"
    assert recorded[0]["success"] is True


def test_the_proof_is_read_back_before_it_is_claimed(monkeypatch):
    """Proof persistence is part of the gate, not best-effort telemetry."""
    class _PG:
        @staticmethod
        def record_verification(*a, **k):
            return None

        @staticmethod
        def reusable_verification(*a, **k):
            return None          # the write did not stick
    monkeypatch.setitem(sys.modules, "proof_graph", _PG)
    _guard(monkeypatch, "npm run test")
    ok, note = release_train._persist_production_test_proof("/repo", SHA, "npm run test")
    assert ok is False
    assert "durably readable" in note


# ── what it must never do ────────────────────────────────────────────────────

def test_a_suite_that_did_not_run_is_never_certified(monkeypatch, recorded):
    """sustainable-barks, verbatim: the guard wants `npm run test`, the release ran
    `true`. Certifying that would be a fabricated green."""
    _guard(monkeypatch, "npm run test")
    ok, note = release_train._persist_production_test_proof("/repo", SHA, "true")
    assert ok is False
    assert recorded == [], "a proof was written for a command that never ran"
    assert "true" in note and "npm run test" in note, (
        "the refusal must name BOTH commands, or nobody can act on it")


def test_a_narrowed_selective_suite_is_not_certified_as_the_full_one(monkeypatch,
                                                                     recorded):
    _guard(monkeypatch, "npm run test")
    ok, _note = release_train._persist_production_test_proof(
        "/repo", SHA, "npx vitest run tests/pricing.spec.ts")
    assert ok is False
    assert recorded == []


def test_an_empty_command_is_not_certified(monkeypatch, recorded):
    _guard(monkeypatch, "npm run test")
    ok, note = release_train._persist_production_test_proof("/repo", SHA, "")
    assert ok is False
    assert recorded == []
    assert "(nothing)" in note


def test_a_repo_with_no_test_script_gates_on_nothing(monkeypatch, recorded):
    """pasch has no test script; the guard itself passes, so there is nothing to
    certify and nothing to refuse."""
    _guard(monkeypatch, "")
    ok, note = release_train._persist_production_test_proof("/repo", SHA, "npm run build")
    assert ok is True
    assert recorded == [], "a proof was invented for a repo the guard does not gate"
    assert "nothing to gate on" in note


def test_a_broken_proof_graph_fails_closed(monkeypatch):
    class _PG:
        @staticmethod
        def record_verification(*a, **k):
            raise RuntimeError("disk full")

        @staticmethod
        def reusable_verification(*a, **k):
            return None
    monkeypatch.setitem(sys.modules, "proof_graph", _PG)
    _guard(monkeypatch, "npm run test")
    ok, note = release_train._persist_production_test_proof("/repo", SHA, "npm run test")
    assert ok is False
    assert "persistence failed" in note


# ── the wiring ───────────────────────────────────────────────────────────────

def test_it_runs_beside_the_build_proof_before_the_push():
    import ast
    runner = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(runner, "release_train.py")) as fh:
        src = fh.read()
    tree = ast.parse(src)
    node = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "_integrate_regate_and_push")
    seg = ast.get_source_segment(src, node) or ""
    build_at = seg.find("_persist_production_build_proof")
    test_at = seg.find("_persist_production_test_proof")
    push_at = seg.find('f"{STAGING}:{prod}"')
    assert test_at != -1, "the suite proof is never persisted before the push"
    assert build_at < test_at < push_at, (
        "the suite proof must sit with the build proof, before production moves")
    window = seg[test_at:push_at]
    assert "return False" in window, "a refused suite proof does not stop the release"
    assert "test-proof" in window, (
        "the failure is not recorded under its own gate name")
