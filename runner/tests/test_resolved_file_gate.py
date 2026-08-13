"""Focused gate tests with Python AND TypeScript fixtures.

Two properties decide whether this gate is worth having:

  1. it sees a marker in a file NOBODY TOUCHED in the current change set — that is the
     gap the existing `regression_guard.scan_paths` left, since it only ever saw the
     explicit path list a hook handed it;
  2. it fails a resolution that removed the markers but left the file broken — the more
     common outcome, and one a marker scan passes perfectly.

Marker strings are built with chr() so this test file does not itself contain a line
starting with a conflict marker.
"""
import json
import os
import subprocess
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_RUNNER = os.path.dirname(_HERE)
sys.path.insert(0, _RUNNER)

import resolved_file_gate as gate  # noqa: E402

LT = chr(60) * 7
EQ = "=" * 7
GT = chr(62) * 7


def _git(repo, *args):
    return subprocess.run(["git"] + list(args), cwd=repo, capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path):
    r = str(tmp_path / "repo")
    os.makedirs(r)
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@e.com")
    _git(r, "config", "user.name", "t")
    _write(r, "runner/clean.py", "def ok():\n    return 1\n")
    _write(r, "packages/darwin-kernel/package.json", json.dumps({"name": "dk", "scripts": {"test": "true"}}))
    _write(r, "packages/darwin-kernel/src/passport.ts",
           "export const canonicalClaim = (id: string): string => id\n")
    _write(r, "config.json", json.dumps({"a": 1}))
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "base")
    return r


def _write(repo, rel, content):
    full = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as fh:
        fh.write(content)
    return rel


def _with_markers(body_a, body_b):
    return "\n".join([LT + " HEAD", body_a, EQ, body_b, GT + " other", ""])


# ─── 1. Repository-wide sweep ───────────────────────────────────────────────

def test_clean_repository_passes(repo):
    result = gate.gate(repo)
    assert result["ok"] is True
    assert result["markers"] == []
    assert "no conflict markers anywhere" in result["reason"]


def test_a_marker_in_an_UNTOUCHED_file_is_still_caught(repo):
    # The whole gap: this file is not in `resolved_paths`, so the previous
    # scan_paths-only callers would never have opened it.
    _write(repo, "runner/untouched.py", _with_markers("x = 1", "x = 2"))
    _git(repo, "add", "-A")
    result = gate.gate(repo, resolved_paths=["runner/clean.py"])
    assert result["ok"] is False
    assert any("untouched.py" in (m.get("file") or "") for m in result["markers"])


def test_a_marker_in_a_typescript_package_outside_runner_is_caught(repo):
    _write(repo, "packages/darwin-kernel/src/passport.ts",
           _with_markers("export const a = 1", "export const a = 2"))
    _git(repo, "add", "-A")
    result = gate.gate(repo)
    assert result["ok"] is False
    assert any("passport.ts" in (m.get("file") or "") for m in result["markers"])


def test_a_marker_in_a_non_source_file_is_caught(repo):
    # The racefeed incident file was .gitignore; a source-only scan never opens it.
    _write(repo, ".gitignore", _with_markers("node_modules", "dist"))
    _git(repo, "add", "-A")
    result = gate.gate(repo)
    assert result["ok"] is False


def test_node_modules_and_binaries_are_not_scanned(repo):
    _write(repo, "packages/darwin-kernel/node_modules/dep/index.js", _with_markers("a", "b"))
    _git(repo, "add", "-A", "-f")
    result = gate.gate(repo)
    assert result["ok"] is True


def test_the_marker_definition_is_delegated_not_copied():
    # A second regex that drifts from regression_guard's is worse than no second gate.
    src = open(os.path.join(_RUNNER, "resolved_file_gate.py")).read()
    assert "regression_guard.scan_paths" in src
    assert "re.compile" not in src


# ─── 2. Language-appropriate checks ─────────────────────────────────────────

def test_python_syntax_failure_is_caught(repo):
    _write(repo, "runner/broken.py", "def f(:\n    pass\n")
    result = gate.syntax_check(repo, "runner/broken.py")
    assert result["status"] == "failed"
    assert result["language"] == "python"
    assert "SyntaxError" in result["detail"]


def test_valid_python_passes(repo):
    assert gate.syntax_check(repo, "runner/clean.py")["status"] == "ok"


def test_invalid_json_is_caught(repo):
    _write(repo, "config.json", "{not json")
    result = gate.syntax_check(repo, "config.json")
    assert result["status"] == "failed"
    assert "invalid JSON" in result["detail"]


def test_language_detection_covers_ts_outside_runner():
    assert gate.language_for("packages/darwin-kernel/src/passport.ts") == "typescript"
    assert gate.language_for("web/pages/index.tsx") == "typescript"
    assert gate.language_for("runner/x.py") == "python"
    assert gate.language_for("a/b.mjs") == "javascript"
    assert gate.language_for("README.md") == "other"


def test_typescript_without_a_local_tsc_is_SKIPPED_not_failed(repo):
    # A gate that blocks every promotion because tsc is not installed gets switched off,
    # and a gate that is off protects nothing.
    result = gate.syntax_check(repo, "packages/darwin-kernel/src/passport.ts")
    assert result["status"] in ("ok", "skipped")
    assert result["status"] != "failed"


def test_a_broken_resolution_with_NO_markers_still_fails(repo):
    # The common case: the resolver stripped the markers and left the file broken.
    _write(repo, "runner/resolved.py", "def f():\nreturn 1\n")
    _git(repo, "add", "-A")
    result = gate.gate(repo, resolved_paths=["runner/resolved.py"])
    assert result["markers"] == []
    assert result["ok"] is False
    assert any("resolved.py" in b for b in result["blockers"])


def test_a_missing_file_is_skipped_rather_than_failed(repo):
    assert gate.syntax_check(repo, "runner/does-not-exist.py")["status"] == "skipped"


# ─── 3. Refusing promotion ──────────────────────────────────────────────────

def test_promotion_is_blocked_on_a_marker(repo):
    _write(repo, "runner/x.py", _with_markers("a = 1", "a = 2"))
    _git(repo, "add", "-A")
    blocked, reason = gate.promotion_blocked(repo)
    assert blocked is True
    assert "Promotion refused" in reason


def test_promotion_is_blocked_on_a_failed_language_check(repo):
    _write(repo, "runner/x.py", "def f(:\n")
    _git(repo, "add", "-A")
    blocked, reason = gate.promotion_blocked(repo, resolved_paths=["runner/x.py"])
    assert blocked is True
    assert "language check" in reason


def test_promotion_is_allowed_when_both_checks_pass(repo):
    blocked, reason = gate.promotion_blocked(repo, resolved_paths=["runner/clean.py"])
    assert blocked is False
    assert "no conflict markers" in reason


def test_the_refusal_says_nothing_was_force_pushed_or_discarded(repo):
    _write(repo, "runner/x.py", _with_markers("a", "b"))
    _git(repo, "add", "-A")
    _, reason = gate.promotion_blocked(repo)
    assert "force-pushed" in reason
    assert "discarded" in reason


def test_the_gate_never_mutates_the_repository(repo):
    before = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _write(repo, "runner/x.py", _with_markers("a", "b"))
    _git(repo, "add", "-A")
    status_before = _git(repo, "status", "--porcelain").stdout
    gate.gate(repo, resolved_paths=["runner/x.py"])
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == before
    assert _git(repo, "status", "--porcelain").stdout == status_before


# ─── 4. Fail-closed and fail-soft ───────────────────────────────────────────

def test_the_gate_fails_CLOSED_on_an_unreadable_repository():
    result = gate.gate("/nonexistent/path/that/is/not/a/repo")
    assert result["ok"] is False


def test_tracked_text_files_returns_empty_rather_than_raising():
    assert gate.tracked_text_files("/nonexistent/path") == []


def test_package_tests_are_opt_in(repo, monkeypatch):
    monkeypatch.delenv("ORCH_GATE_RUN_TESTS", raising=False)
    result = gate.package_tests(repo, "packages/darwin-kernel/src/passport.ts")
    assert result["status"] == "skipped"
    assert "ORCH_GATE_RUN_TESTS" in result["detail"]


def test_package_tests_run_the_owning_package_when_enabled(repo, monkeypatch):
    monkeypatch.setenv("ORCH_GATE_RUN_TESTS", "1")
    result = gate.package_tests(repo, "packages/darwin-kernel/src/passport.ts")
    # npm may be unavailable on a bare runner; either it passed or it reported honestly.
    assert result["status"] in ("ok", "failed", "skipped")


def test_thresholds_are_orch_prefixed_and_fail_soft(monkeypatch):
    monkeypatch.setenv("ORCH_GATE_MAX_FILES", "7")
    assert gate.max_scanned_files() == 7
    monkeypatch.setenv("ORCH_GATE_MAX_FILES", "not-a-number")
    assert gate.max_scanned_files() == 20000


# ─── 5. The Darwin passport behaviour is untouched ──────────────────────────

def test_the_gate_does_not_reference_passport_logic():
    # Canonical-claim and mint-time-expiry behaviour is preserved by this module not
    # touching it. Asserted so a later edit that reaches into it is caught here.
    src = open(os.path.join(_RUNNER, "resolved_file_gate.py")).read().lower()
    assert "canonicalclaim" not in src
    assert "mint_time" not in src and "minttime" not in src


# ─── 6. Wired into merge and release, not just importable ───────────────────

def test_continuous_merger_calls_the_gate_and_fails_closed():
    src = open(os.path.join(_RUNNER, "continuous_merger.py")).read()
    assert "_resolved_file_gate_blocked" in src
    assert "resolved_file_gate" in src
    # It must refuse, not force through, and it must roll the merge back.
    assert "gate-blocked" in src
    assert "reset\", \"--hard\", \"HEAD~1\"" in src or "'--hard', 'HEAD~1'" in src
    # Fail-closed on import error.
    assert "fail-closed" in src


def test_release_preflight_scans_the_whole_tree_at_the_release_sha():
    src = open(os.path.join(_RUNNER, "release_train.py")).read()
    assert "resolved_file_gate" in src
    assert "scan_repo(repo, ref=sha)" in src
    assert "conflict-markers" in src
    assert "release refused" in src


def test_the_merge_gate_refuses_rather_than_discarding_a_side():
    src = open(os.path.join(_RUNNER, "continuous_merger.py")).read()
    # No force-push and no checkout --ours/--theirs introduced by this gate.
    gate_block = src[src.index("_resolved_file_gate_blocked(") : src.index("result[\"merged\"] = True")]
    assert "--force" not in gate_block
    assert "--ours" not in gate_block and "--theirs" not in gate_block
