#!/usr/bin/env python3
"""Tests for production_push_guard.py — the gate between a commit and production.

Context, because it explains what these assert. Until 2026-08-13 this guard
required a green BUILD and nothing else. Master was serving production with 14
failing tests across 8 files, some red for over a day, and every push was waved
through because each one compiled. The build gate was doing its job; it was just
never asked the second question.
"""
import os, sys, json, subprocess, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")
import production_push_guard as guard


def _repo(scripts=None, lockfiles=(), commit=True):
    d = tempfile.mkdtemp()
    if scripts is not None:
        with open(os.path.join(d, "package.json"), "w") as fh:
            json.dump({"name": "t", "scripts": scripts}, fh)
    for name in lockfiles:
        open(os.path.join(d, name), "w").close()
    if commit:
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        subprocess.run(["git", "add", "-A"], cwd=d, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=d, env=env, check=True)
    return d


# ── runner selection ─────────────────────────────────────────────────────────

def test_npm_wins_when_package_lock_present_even_beside_a_pnpm_lock():
    """The exact case that would have broken every push.

    apparently carries package-lock.json AND a stale pnpm-lock.yaml.
    build_gate._package_runner answers "pnpm"; `pnpm test` there spends 100
    seconds in a dependency-status check and dies inside pnpm having run zero
    tests. A gate wired to that blocks every push for a reason unrelated to the
    code.
    """
    d = _repo(lockfiles=("package-lock.json", "pnpm-lock.yaml"))
    assert guard._runner_for(d) == "npm"


def test_pnpm_used_when_it_is_the_only_lockfile():
    assert guard._runner_for(_repo(lockfiles=("pnpm-lock.yaml",))) == "pnpm"


def test_yarn_used_when_it_is_the_only_lockfile():
    assert guard._runner_for(_repo(lockfiles=("yarn.lock",))) == "yarn"


def test_defaults_to_npm_with_no_lockfile():
    # commit=False: an empty directory has nothing to commit, and _runner_for
    # reads the filesystem, not git.
    assert guard._runner_for(_repo(commit=False)) == "npm"


# ── command detection ────────────────────────────────────────────────────────

def test_no_test_script_is_not_a_failure():
    """A repo with no suite has nothing to gate on. It must not be blocked."""
    d = _repo(scripts={"build": "nuxt build"}, lockfiles=("package-lock.json",))
    assert guard.detect_test_cmd(d) == ""
    ok, log = guard.verify_tests(d, "deadbeef")
    assert ok is True
    assert "nothing to gate on" in log


def test_prefers_test_ci_over_test():
    d = _repo(scripts={"test": "vitest run", "test:ci": "vitest run --coverage"},
              lockfiles=("package-lock.json",))
    assert guard.detect_test_cmd(d) == "npm run test:ci"


# ── the tree a suite result actually describes ───────────────────────────────

def test_dirty_tree_cannot_earn_a_proof():
    """A suite run attests the tree it ran against, not the one being pushed."""
    d = _repo(scripts={"test": "true"}, lockfiles=("package-lock.json",))
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=d, capture_output=True, text=True).stdout.strip()
    open(os.path.join(d, "dirty.txt"), "w").write("uncommitted")
    assert guard._tree_is_exactly(d, head) is False


def test_clean_tree_at_the_commit_is_attestable():
    d = _repo(scripts={"test": "true"}, lockfiles=("package-lock.json",))
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=d, capture_output=True, text=True).stdout.strip()
    assert guard._tree_is_exactly(d, head) is True


def test_wrong_commit_is_not_attestable():
    d = _repo(scripts={"test": "true"}, lockfiles=("package-lock.json",))
    assert guard._tree_is_exactly(d, "0" * 40) is False


# ── the verdict ──────────────────────────────────────────────────────────────

def test_red_suite_blocks_the_push():
    d = _repo(scripts={"test": "sh -c 'echo 3 tests failed; exit 1'"}, lockfiles=("package-lock.json",))
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=d, capture_output=True, text=True).stdout.strip()
    ok, log = guard.verify_tests(d, head)
    assert ok is False
    assert "FULL SUITE RED" in log
    assert "3 tests failed" in log


def test_green_suite_allows_the_push():
    d = _repo(scripts={"test": "true"}, lockfiles=("package-lock.json",))
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=d, capture_output=True, text=True).stdout.strip()
    ok, log = guard.verify_tests(d, head)
    assert ok is True
    assert "green" in log


def test_the_gate_is_not_vacuous():
    """Same repo shape, same call, opposite verdicts — it is reading the result."""
    green = _repo(scripts={"test": "true"}, lockfiles=("package-lock.json",))
    red = _repo(scripts={"test": "false"}, lockfiles=("package-lock.json",))
    hg = subprocess.run(["git", "rev-parse", "HEAD"], cwd=green, capture_output=True, text=True).stdout.strip()
    hr = subprocess.run(["git", "rev-parse", "HEAD"], cwd=red, capture_output=True, text=True).stdout.strip()
    assert guard.verify_tests(green, hg)[0] is True
    assert guard.verify_tests(red, hr)[0] is False


# ── the fail-open paths that used to allow a push on the guard's own breakage ──

def test_missing_build_gate_helper_blocks_instead_of_allowing(monkeypatch=None):
    """Was `return True, "not available; allowing push"`.

    A guard that allows the push when its own machinery is missing reports GREEN
    loudest exactly when it verified nothing.
    """
    real = guard.build_gate.detect_build_cmd
    try:
        guard.build_gate.detect_build_cmd = None  # attribute exists but is not callable
        ok, log = guard.verify("/tmp", "deadbeef")
        assert ok is False
        assert "refusing to certify" in log
    finally:
        guard.build_gate.detect_build_cmd = real


def test_missing_proof_graph_helper_blocks_instead_of_allowing():
    real = guard.proof_graph.reusable_verification
    d = _repo(scripts={"test": "true"}, lockfiles=("package-lock.json",))
    try:
        guard.proof_graph.reusable_verification = None
        ok, log = guard.verify_tests(d, "deadbeef")
        assert ok is False
        assert "refusing to certify untested code" in log
    finally:
        guard.proof_graph.reusable_verification = real


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except AssertionError as err:
                fails += 1
                print(f"  FAIL  {name}: {err}")
            except Exception as err:  # noqa: BLE001
                fails += 1
                print(f"  ERROR {name}: {type(err).__name__}: {err}")
    print(f"\n{'FAILED' if fails else 'OK'} — {fails} failure(s)")
    raise SystemExit(1 if fails else 0)
