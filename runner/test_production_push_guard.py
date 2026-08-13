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


def _head(d):
    """HEAD of the scratch repo, not of whatever GIT_DIR points at.

    Under a pre-push hook GIT_DIR is exported, and a bare `git rev-parse HEAD`
    would answer for the real repository even with cwd set here — the same
    mechanism that caused the 2026-08-13 incident, reproduced inside the test
    harness that exists to check for it.
    """
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=d, env=guard._clean_git_env(),
                          capture_output=True, text=True).stdout.strip()


def _repo(scripts=None, lockfiles=(), commit=True):
    d = tempfile.mkdtemp()
    if scripts is not None:
        with open(os.path.join(d, "package.json"), "w") as fh:
            json.dump({"name": "t", "scripts": scripts}, fh)
    for name in lockfiles:
        open(os.path.join(d, name), "w").close()
    if commit:
        # STRIP THE INHERITED GIT_* VARIABLES.
        #
        # This guard runs inside a pre-push hook, where git exports GIT_DIR and
        # GIT_INDEX_FILE. Anything spawning git from that environment targets the
        # REAL repository regardless of cwd. On 2026-08-13 four vitest suites with
        # this same shape committed a 1.5-million-deletion tree to apparently and
        # pushed it to master. These fixtures create repos and commit too, so they
        # are the same hazard.
        env = {k: v for k, v in os.environ.items()
               if k not in {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                            "GIT_PREFIX", "GIT_OBJECT_DIRECTORY",
                            "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE"}}
        env.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
                    "GIT_CEILING_DIRECTORIES": d,
                    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"})
        subprocess.run(["git", "init", "-q"], cwd=d, env=env, check=True)
        subprocess.run(["git", "add", "-A"], cwd=d, env=env, check=True)
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
    head = _head(d)
    open(os.path.join(d, "dirty.txt"), "w").write("uncommitted")
    assert guard._tree_is_exactly(d, head) is False


def test_clean_tree_at_the_commit_is_attestable():
    d = _repo(scripts={"test": "true"}, lockfiles=("package-lock.json",))
    head = _head(d)
    assert guard._tree_is_exactly(d, head) is True


def test_wrong_commit_is_not_attestable():
    d = _repo(scripts={"test": "true"}, lockfiles=("package-lock.json",))
    assert guard._tree_is_exactly(d, "0" * 40) is False


# ── the verdict ──────────────────────────────────────────────────────────────

def test_red_suite_blocks_the_push():
    d = _repo(scripts={"test": "sh -c 'echo 3 tests failed; exit 1'"}, lockfiles=("package-lock.json",))
    head = _head(d)
    ok, log = guard.verify_tests(d, head)
    assert ok is False
    assert "FULL SUITE RED" in log
    assert "3 tests failed" in log


def test_green_suite_allows_the_push():
    d = _repo(scripts={"test": "true"}, lockfiles=("package-lock.json",))
    head = _head(d)
    ok, log = guard.verify_tests(d, head)
    assert ok is True
    assert "green" in log


def test_the_gate_is_not_vacuous():
    """Same repo shape, same call, opposite verdicts — it is reading the result."""
    green = _repo(scripts={"test": "true"}, lockfiles=("package-lock.json",))
    red = _repo(scripts={"test": "false"}, lockfiles=("package-lock.json",))
    hg = _head(green)
    hr = _head(red)
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


# ── flake vs failure ─────────────────────────────────────────────────────────

def _flaky_repo(fail_times):
    """A repo whose suite fails the first `fail_times` runs, then passes.

    Models the measured case: pushing while five nuxt builds were running produced
    two failures that both pass standalone — one 5000ms timeout under load, one
    transient .git/config.lock from a concurrent git process.
    """
    d = _repo(scripts={"test": "sh -c 'c=$(cat .runs 2>/dev/null || echo 0); "
                               "echo $((c+1)) > .runs; "
                               f"[ $c -ge {fail_times} ] || {{ echo flaky failure; exit 1; }}'"},
              lockfiles=("package-lock.json",))
    return d


def test_a_single_red_run_is_retried_and_flake_does_not_block():
    d = _flaky_repo(fail_times=1)
    head = _head(d)
    ok, log = guard.verify_tests(d, head)
    assert ok is True, log
    assert "ON RE-RUN" in log, log
    assert int(open(os.path.join(d, ".runs")).read().strip()) == 2


def test_a_push_allowed_on_a_second_attempt_says_so():
    """It must not print an unqualified GREEN. The operator should see the retry."""
    d = _flaky_repo(fail_times=1)
    head = _head(d)
    _, log = guard.verify_tests(d, head)
    assert "environmental, not code" in log


def test_a_real_failure_survives_the_retry_and_blocks():
    d = _flaky_repo(fail_times=99)
    head = _head(d)
    ok, log = guard.verify_tests(d, head)
    assert ok is False, log
    assert "twice" in log
    assert int(open(os.path.join(d, ".runs")).read().strip()) == 2


def test_a_green_first_run_is_not_run_twice():
    """The retry is for red runs only; every push must not pay for two suites."""
    d = _repo(scripts={"test": "sh -c 'c=$(cat .runs 2>/dev/null || echo 0); echo $((c+1)) > .runs'"},
              lockfiles=("package-lock.json",))
    head = _head(d)
    ok, _ = guard.verify_tests(d, head)
    assert ok is True
    assert int(open(os.path.join(d, ".runs")).read().strip()) == 1


# ── the two overrides are separate on purpose ────────────────────────────────

def test_build_override_does_not_wave_through_red_tests():
    """ORCH_ALLOW_UNVERIFIED_PROD_PUSH means "I verified the BUILD myself".

    If it also waived the suite, anyone reaching for it for a build reason would
    silently switch the test gate off, and nobody would know it had happened.
    """
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "production_push_guard.py")).read()
    after_tests = src.split("tests_ok, test_log = verify_tests(repo, commit)", 1)[1]
    # Comments in that block explain WHY the switches are separate and name both,
    # so compare against code only.
    gate_code = "\n".join(
        line for line in after_tests.split("else:", 1)[0].splitlines()
        if not line.strip().startswith("#")
    )
    assert "ORCH_ALLOW_RED_TESTS" in gate_code
    assert "ORCH_ALLOW_UNVERIFIED_PROD_PUSH" not in gate_code


def test_the_block_message_names_the_switch_that_would_bypass_it():
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "production_push_guard.py")).read()
    assert "Set ORCH_ALLOW_RED_TESTS=1 to ship anyway" in src


# ── content guard: refuse on what the push CONTAINS ──────────────────────────

def _clean_env(author=("dev", "dev@example.com")):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_AUTHOR_NAME": author[0], "GIT_AUTHOR_EMAIL": author[1],
                "GIT_COMMITTER_NAME": author[0], "GIT_COMMITTER_EMAIL": author[1],
                "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"})
    return env


def _commit(d, files, author=("dev", "dev@example.com"), msg="c", delete_all=False):
    env = _clean_env(author)
    if delete_all:
        subprocess.run(["git", "rm", "-rq", "."], cwd=d, env=env, check=True)
    for name, body in files.items():
        p = os.path.join(d, name)
        if os.path.dirname(p):
            os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(body)
    subprocess.run(["git", "add", "-A"], cwd=d, env=env, check=True)
    subprocess.run(["git", "commit", "-qm", msg], cwd=d, env=env, check=True)
    return _head(d)


def _repo_with(n_files):
    d = _repo(scripts={"test": "true"}, lockfiles=("package-lock.json",))
    base = _commit(d, {f"src/f{i}.ts": f"export const x{i} = {i}\n" for i in range(n_files)})
    return d, base


def test_a_commit_authored_by_a_test_fixture_is_refused():
    """The exact shape that reached master: author test <test@example.com>."""
    d, base = _repo_with(40)
    bad = _commit(d, {"src/new.ts": "x"}, author=("test", "test@example.com"))
    ok, log = guard.verify_content(d, base, bad)
    assert ok is False, log
    assert "test fixture" in log and "test@example.com" in log


def test_a_commit_by_a_real_author_passes():
    d, base = _repo_with(40)
    good = _commit(d, {"src/new.ts": "x"}, author=("Bear", "kale@heretomorrow.us"))
    assert guard.verify_content(d, base, good)[0] is True


def test_deleting_most_of_the_tree_is_refused():
    """7063 files -> 1, which is what ef27653f did."""
    d, base = _repo_with(40)
    wiped = _commit(d, {"only.txt": "x"}, delete_all=True, msg="init")
    ok, log = guard.verify_content(d, base, wiped)
    assert ok is False, log
    assert "removes" in log and "of the tree" in log


def test_an_ordinary_deletion_is_allowed():
    """A gate that cries wolf gets switched off. Normal cleanup must pass."""
    d, base = _repo_with(40)
    env = _clean_env()
    for i in range(5):
        os.remove(os.path.join(d, f"src/f{i}.ts"))
    subprocess.run(["git", "add", "-A"], cwd=d, env=env, check=True)
    subprocess.run(["git", "commit", "-qm", "cleanup"], cwd=d, env=env, check=True)
    assert guard.verify_content(d, base, _head(d))[0] is True


def test_a_tiny_repo_may_shrink_freely():
    d, base = _repo_with(4)
    wiped = _commit(d, {"only.txt": "x"}, delete_all=True)
    assert guard.verify_content(d, base, wiped)[0] is True


def test_content_guard_is_not_vacuous():
    """Same call, opposite verdicts — it reads the push rather than waving it through."""
    d, base = _repo_with(40)
    good = _commit(d, {"src/new.ts": "x"}, author=("Bear", "kale@heretomorrow.us"))
    assert guard.verify_content(d, base, good)[0] is True
    bad = _commit(d, {"src/other.ts": "y"}, author=("test", "test@example.com"))
    assert guard.verify_content(d, good, bad)[0] is False


def test_a_new_ref_has_nothing_to_compare():
    d, _ = _repo_with(10)
    ok, log = guard.verify_content(d, guard.ZERO_SHA, _head(d))
    assert ok is True and "new ref" in log


# ── immutable ref: the defect that actually shipped ef27653f ─────────────────

def test_pushing_HEAD_is_refused():
    """`git push origin HEAD:master` resolves HEAD AFTER the hook runs.

    The hook runs the full suite. If anything in that suite moves HEAD, the
    commit that ships is not the commit that was verified — the guard approved
    0c0a8048 and GitHub received ef27653f.
    """
    d, base = _repo_with(10)
    ok, log = guard.verify_immutable_ref("HEAD", base, d)
    assert ok is False, log
    assert "resolves HEAD AFTER this hook runs" in log
    assert "<sha>:refs/heads/master" in log


def test_pushing_an_explicit_sha_is_allowed():
    d, base = _repo_with(10)
    ok, log = guard.verify_immutable_ref(base, base, d)
    assert ok is True, log


def test_pushing_a_named_branch_is_allowed():
    d, base = _repo_with(10)
    assert guard.verify_immutable_ref("refs/heads/release", base, d)[0] is True


def test_the_refusal_shows_that_HEAD_already_moved():
    """The operator should see the divergence, not just be told it is possible."""
    d, base = _repo_with(10)
    moved = _commit(d, {"src/after.ts": "x"})
    _, log = guard.verify_immutable_ref("HEAD", base, d)
    assert "ALREADY MOVED" in log
    assert moved[:12] in log


# ── ordering: no proof may buy its way past content ──────────────────────────

def test_content_and_ref_checks_run_before_build_and_test_gates():
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "production_push_guard.py")).read()
    body = src.split("def main(", 1)[1]
    assert body.index("verify_immutable_ref(") < body.index("ok, log = verify(")
    assert body.index("verify_content(") < body.index("ok, log = verify(")
    # ...and ahead of changes_affect_build, which can SKIP verification entirely.
    assert body.index("verify_content(") < body.index("changes_affect_build(")


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
