#!/usr/bin/env python3
"""Block direct production pushes unless the exact committed tree is green — BUILD AND TESTS.

A green build proves the tree compiles. It says nothing about whether the code is correct, and
this guard used to stop there. On 2026-08-13 that gap was measured: master was serving
production with 14 failing tests across 8 files, some red for over a day, and every push had
been waved through because each one built cleanly. Among what was hiding behind them — a
production 404 on the first card of /licenses, a pricing module that threw
`TypeError: portfolio is not iterable` on every non-empty portfolio, and CEPL reading a
calibration field its own writer had renamed.

So the gate now requires both. See verify_tests().
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time

RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RUNNER_DIR)

import build_gate
import proof_graph

PRODUCTION_REFS = {"refs/heads/main", "refs/heads/master"}
ZERO_SHA = "0" * 40


# git exports these into a hook's environment, and they OVERRIDE cwd. This guard
# runs as a pre-push hook, so every git call it makes must be told which
# repository to look at rather than inheriting one. Same hazard that let four
# vitest suites commit to the wrong repository on 2026-08-13.
_GIT_REDIRECT_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                      "GIT_PREFIX", "GIT_OBJECT_DIRECTORY",
                      "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE")


def _clean_git_env():
    return {k: v for k, v in os.environ.items() if k not in _GIT_REDIRECT_VARS}


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, env=_clean_git_env(),
                          capture_output=True, text=True, check=True).stdout.strip()


def guarded_updates(lines):
    updates = []
    for line in lines:
        fields = line.strip().split()
        if len(fields) != 4:
            continue
        local_ref, local_sha, remote_ref, remote_sha = fields
        if remote_ref in PRODUCTION_REFS and local_sha != ZERO_SHA:
            updates.append((local_ref, local_sha, remote_ref, remote_sha))
    return updates


def changes_affect_build(repo, old_commit, new_commit):
    """Skip nested deploy packages when a push changes only files outside their Vercel root."""
    if not old_commit or old_commit == ZERO_SHA:
        return True
    try:
        roots = build_gate.dependency_prewarm.package_roots(repo)
    except (AttributeError, TypeError):
        return True  # fail-open: if build_gate doesn't have this, assume changes matter
    if not roots:
        return True
    package_root = next((root for root in roots if os.path.isfile(os.path.join(root, "vercel.json"))), roots[0])
    rel = os.path.relpath(package_root, repo)
    if rel == ".":
        return True
    changed = _git(repo, "diff", "--name-only", old_commit, new_commit).splitlines()
    prefix = rel.rstrip("/") + "/"
    return any(path == rel or path.startswith(prefix) for path in changed)


def verify(repo, commit):
    try:
        command = build_gate.detect_build_cmd(repo)
    except (AttributeError, TypeError) as err:
        # Was `return True, "not available; allowing push"`. A guard that allows
        # the push when its own machinery is missing is not a guard — it reports
        # GREEN loudest exactly when it verified nothing.
        return False, f"build_gate.detect_build_cmd unavailable ({err}); refusing to certify an unverified tree."
    if not command:
        return False, "No production build command could be detected."
    try:
        for kind in ("build", "vercel-build"):
            cached = proof_graph.reusable_verification(repo, commit, command, kind)
            if cached:
                return True, f"reused green {kind} proof for {commit[:12]}"
    except (AttributeError, TypeError) as err:
        return False, f"proof_graph.reusable_verification unavailable ({err}); refusing to certify an unverified tree."
    if os.environ.get("ORCH_ALLOW_UNVERIFIED_PROD_PUSH", "").lower() in {"1", "true", "yes", "on"}:
        return True, "BREAK-GLASS override: ORCH_ALLOW_UNVERIFIED_PROD_PUSH is set"
    return False, (
        f"No green build proof exists for exact commit {commit[:12]} using `{command}`.\n"
        "\n"
        "Earn one — it runs the real build in THIS checkout, and records nothing if it fails:\n"
        f"    python3 {os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tools', 'prove_build.py')} --repo {repo}\n"
        "\n"
        "Or push to orchestrator/dev and let release_train verify/promote it — but note the\n"
        "train records its proofs against an isolated integration worktree, so a proof it\n"
        "earns will not match a push from this path.\n"
        "Emergency only: set ORCH_ALLOW_UNVERIFIED_PROD_PUSH=1 after independently verifying the committed tree."
    )


# ── TEST GATE ────────────────────────────────────────────────────────────────

TEST_SCRIPT_PREFERENCE = ("test:ci", "test:run", "test")


def _runner_for(package_root):
    """Pick the package manager the repo is ACTUALLY installed with.

    Not build_gate._package_runner. apparently carries BOTH package-lock.json and a
    stale pnpm-lock.yaml, and that helper answers "pnpm". Measured on 2026-08-13:
    `pnpm test` in that repo spends 100 seconds in pnpm's dependency-status check
    and then dies inside pnpm itself, having run zero tests. A gate wired to that
    would block every production push for a reason that has nothing to do with the
    code — which is the mirror image of the fail-open defect, and just as useless.

    The lockfile the deploy uses wins: vercel.json installs with `npm ci`.
    """
    has = lambda n: os.path.isfile(os.path.join(package_root, n))
    if has("package-lock.json"):
        return "npm"
    if has("pnpm-lock.yaml"):
        return "pnpm"
    if has("yarn.lock"):
        return "yarn"
    return "npm"


def detect_test_cmd(repo):
    """The repo's own full-suite command, from the deployable package's package.json.

    Deliberately mirrors build_gate.detect_build_cmd rather than importing it: the
    build gate is on the release train's hot path and this must not change its
    behaviour. Returns "" when the repo has no test script, which is not the same
    as a repo whose tests fail — see verify_tests.
    """
    try:
        roots = build_gate.dependency_prewarm.package_roots(repo)
    except (AttributeError, TypeError):
        return ""
    for root in roots or []:
        try:
            scripts = build_gate._load_scripts(root)
        except (AttributeError, TypeError):
            continue
        for name in TEST_SCRIPT_PREFERENCE:
            if name not in scripts:
                continue
            mgr = _runner_for(root)
            rel = os.path.relpath(root, repo)
            run = f"{mgr} run {name}" if mgr == "npm" else f"{mgr} {name}"
            return run if rel == "." else f"cd {shlex.quote(rel)} && {run}"
    return ""


def _tree_is_exactly(repo, commit):
    """True when the working tree is clean AND checked out at `commit`.

    A suite run only attests the tree it ran against. Running it while HEAD is
    elsewhere, or while files are modified, produces a result about a tree that
    is not the one being pushed — which is the whole class of defect this guard
    exists to stop.
    """
    try:
        head = _git(repo, "rev-parse", "HEAD")
        dirty = _git(repo, "status", "--porcelain")
    except subprocess.CalledProcessError:
        return False
    return head == commit and dirty == ""


#: The re-run must not measure the tail of the run before it.
#:
#: The old code re-ran immediately. On 2026-08-13 that made the re-run useless:
#: three engine suites (agentic-10x, auto-remediation, licensing-autopilot) hit
#: vitest's 5000ms default timeout on both attempts, and the same tree, same
#: command, same commit came back 1018/1018 green when the suite was started on
#: a quiet machine. Four control runs isolated the variable — piped vs inherited
#: stdout and cleaned vs ambient env all failed identically, so it was neither —
#: and a quiet-start run through the identical piped invocation passed. The
#: machine had just finished a suite; ~18 vitest forks were still winding down.
#:
#: So: before the second attempt, wait for the 1-minute load average to come
#: back under LOAD_PER_CPU x cores, bounded. A gate that re-runs into its own
#: exhaust cannot tell flake from failure, which is the one job it has here.
#: 0.5, not 1.0. The first version used 1.0 and was measured too loose within the
#: hour: on an 18-core box it released the re-run at load 17.7 against a
#: threshold of 18.0 — "settled" by arithmetic, still saturated in fact. Every
#: green full-suite run that day was at load ~8; every red one at 16-26. One
#: runnable thread per two cores leaves room for the timing-sensitive tests that
#: started this, and the bounded wait below means a busy box still gets to push.
QUIET_LOAD_PER_CPU = float(os.environ.get("ORCH_QUIET_LOAD_PER_CPU", "0.5"))
QUIET_MAX_WAIT_S = int(os.environ.get("ORCH_QUIET_MAX_WAIT_S", "180"))


def _wait_for_quiet_machine(max_wait=None, per_cpu=None):
    """Block until the box is idle enough for a timing-sensitive suite, or give up."""
    max_wait = QUIET_MAX_WAIT_S if max_wait is None else max_wait
    per_cpu = QUIET_LOAD_PER_CPU if per_cpu is None else per_cpu
    # ORCH_QUIET_MAX_WAIT_S=0 turns the cool-down off. This exists because the
    # guard's own test suite deadlocked on it: test_red_suite_blocks_the_push
    # drives verify_tests through a genuinely red run, which reached the real
    # cool-down and sat there for the full budget on a machine that was busy —
    # running that very test suite. A wait that can block its own tests will be
    # deleted by whoever hits it at 3am, so it has an off switch and the tests
    # use it.
    if max_wait <= 0:
        return None
    try:
        cpus = os.cpu_count() or 1
        threshold = cpus * per_cpu
    except Exception:
        return None  # never let the cool-down itself break a push
    deadline = time.monotonic() + max_wait
    first = None
    while True:
        try:
            load = os.getloadavg()[0]
        except (OSError, AttributeError):
            return None  # not available on this platform; proceed immediately
        if first is None:
            first = load
        if load <= threshold:
            if first > threshold:
                print(f"production_push_guard: machine settled ({first:.1f} -> {load:.1f}, "
                      f"threshold {threshold:.1f}); re-running now", file=sys.stderr)
            return load
        if time.monotonic() >= deadline:
            print(f"production_push_guard: load still {load:.1f} (threshold {threshold:.1f}) after "
                  f"{max_wait}s — re-running anyway, but a red result here may be the machine, "
                  "not the code.", file=sys.stderr)
            return load
        time.sleep(5)


#: Seconds a full suite gets before the gate gives up on it. The old inline default
#: was 1800, which is SHORTER than this repo's own suite (~2330s for 14,352 tests),
#: so the gate could not finish the run it exists to perform.
TEST_GATE_TIMEOUT_DEFAULT = 3600


def _gate_timeout():
    """Seconds the suite gets, read at call time so fleet_config edits apply live.

    Fail-soft on a bad value, like _task_timeout in runner.py: an absent, empty or
    unparseable ORCH_TEST_GATE_TIMEOUT means "nobody set this", not "give the suite
    zero seconds". A non-positive number would make every run time out instantly
    and read as an unverifiable suite, so it falls back too.
    """
    # str(CONSTANT), not "", so scripts/gen_env_example.py can resolve and document
    # the real default; the fail-soft parse below still covers a SET but bad value.
    raw = str(os.environ.get("ORCH_TEST_GATE_TIMEOUT",
                             str(TEST_GATE_TIMEOUT_DEFAULT))).strip()
    try:
        seconds = int(raw)
    except ValueError:
        return TEST_GATE_TIMEOUT_DEFAULT
    return seconds if seconds > 0 else TEST_GATE_TIMEOUT_DEFAULT


class _SuiteTimedOut:
    """Stands in for a CompletedProcess that never completed.

    `returncode` is None, which no real CompletedProcess ever is, so a caller that
    checks `!= 0` treats an unfinished suite as not-green — the safe reading — and a
    caller that wants to say something more precise can test for None.
    """

    returncode = None

    def __init__(self, seconds):
        self.seconds = seconds
        self.stdout = ""
        self.stderr = ""


def _run_suite(repo, command):
    """Run COMMAND in REPO. Returns a CompletedProcess, or _SuiteTimedOut.

    A timeout used to escape as an uncaught subprocess.TimeoutExpired straight out
    of the pre-push hook. It blocked the push, which is right, but it reported a
    traceback rather than a diagnosis — and the diagnosis is the whole story: the
    clock was shorter than the suite, so nothing at all was learned about the code.
    """
    seconds = _gate_timeout()
    try:
        return subprocess.run(command, cwd=repo, shell=True, env=_clean_git_env(),
                              capture_output=True, text=True, timeout=seconds)
    except subprocess.TimeoutExpired:
        return _SuiteTimedOut(seconds)


def _tracked_content_still_matches(repo, commit):
    """True when HEAD is still `commit` and no TRACKED file has been modified.

    The POST-run counterpart to _tree_is_exactly, and deliberately weaker in one
    respect: it ignores untracked files. Plenty of test commands legitimately write
    into the repo while they run — coverage output, junit.xml, a scratch file — and
    a check that counted those would mean any such project could never earn a proof
    at all. Those artifacts also cannot retroactively change what the suite already
    measured, and the PRE-run _tree_is_exactly has already established that the run
    STARTED from a clean tree at this commit.

    What it does catch is the thing that matters: a tracked file edited, or HEAD
    moved, while the suite was running — which makes the result describe code that
    is not the commit being pushed.
    """
    try:
        head = _git(repo, "rev-parse", "HEAD")
        modified = _git(repo, "status", "--porcelain", "--untracked-files=no")
    except (subprocess.CalledProcessError, OSError):
        return False   # cannot confirm the tree held: refuse to certify
    return head == commit and modified == ""


def _tree_drifted_verdict(commit):
    """The message an operator needs when the tree moved under a running suite."""
    return (
        f"A tracked file changed WHILE the suite was running, so the result does not "
        f"describe {commit[:12]} and no proof has been recorded for it.\n"
        "Re-run with a clean tree checked out at that commit. (This is the same rule the "
        "pre-run check enforces — a suite only attests the tree it ran against — applied "
        "to the other end of a run that can take the better part of an hour. Untracked "
        "files the run itself writes are ignored; only tracked content and HEAD count.)"
    )


def _timed_out_verdict(command, seconds):
    """The message an operator needs when the suite never finished."""
    return (
        f"`{command}` did not finish within {seconds}s, so this guard has NO verdict on the "
        "suite. That is NOT the same as a red run — nothing here says the code is broken.\n"
        "Either the gate clock is shorter than the suite's real runtime (raise "
        "ORCH_TEST_GATE_TIMEOUT in runner/.env or fleet_config), or something is hanging. "
        "Blocking the push: an unfinished suite is not a green one."
    )


def verify_tests(repo, commit):
    """Require a green full suite for this exact commit. Reuse a proof, or earn one."""
    command = detect_test_cmd(repo)
    if not command:
        return True, "no test script in package.json; nothing to gate on"

    try:
        if proof_graph.reusable_verification(repo, commit, command, "test"):
            return True, f"reused green test proof for {commit[:12]}"
    except (AttributeError, TypeError) as err:
        return False, f"proof_graph.reusable_verification unavailable ({err}); refusing to certify untested code."

    if not _tree_is_exactly(repo, commit):
        return False, (
            f"No green test proof exists for {commit[:12]}, and the working tree is not clean at that "
            "commit, so this guard cannot earn one — a suite run here would describe a different tree.\n"
            "Check out the exact commit with a clean tree, or push through orchestrator/dev."
        )

    print(f"production_push_guard: no test proof for {commit[:12]} — running `{command}`", file=sys.stderr)
    proc = _run_suite(repo, command)

    # A TIMEOUT IS NOT A RED RUN, AND IT IS NOT RE-RUN.
    #
    # The flake re-run below exists because a red result under load can be the
    # machine. A timeout is different in kind: no result was produced at all, so
    # there is nothing to separate flake from failure, and a second attempt would
    # cost another full clock to learn the same nothing. Report it and stop.
    if proc.returncode is None:
        return False, _timed_out_verdict(command, proc.seconds)

    # A RED FIRST RUN IS NOT YET A VERDICT.
    #
    # This gate runs inside a pre-push hook, on whatever the machine happens to be
    # doing at that moment. Measured on 2026-08-13, pushing while five nuxt builds
    # were running: the suite came back red with two failures that both pass
    # standalone — one test timed out at 5000ms under load, and another died on a
    # transient .git/config.lock left by a concurrent git process. Blocking on that
    # is the same defect as allowing on a missing helper, pointed the other way: a
    # gate that stops good pushes gets switched off, and then it protects nothing.
    #
    # So a red run is re-run once. Flake does not survive a second attempt; a real
    # failure does. Both runs are reported, and a push allowed on the strength of a
    # second attempt says so rather than printing an unqualified GREEN.
    if proc.returncode != 0:
        print("production_push_guard: suite red — re-running once to separate flake from failure",
              file=sys.stderr)
        _wait_for_quiet_machine()
        second = _run_suite(repo, command)
        if second.returncode is None:
            return False, _timed_out_verdict(command, second.seconds)
        if second.returncode == 0:
            if not _tracked_content_still_matches(repo, commit):
                return False, _tree_drifted_verdict(commit)
            try:
                proof_graph.record_verification(repo, commit, command, "test", True)
            except (AttributeError, TypeError):
                pass
            return True, (
                f"full suite green for {commit[:12]} ON RE-RUN — the first attempt was red and the "
                "second was clean, which means the failures were environmental, not code. "
                "Worth a look if it keeps happening."
            )
        proc = second

    # THE TREE MUST STILL BE THE COMMIT WE JUST TESTED.
    #
    # _tree_is_exactly runs BEFORE the suite, and until now nothing checked the
    # other end. On this repo the suite takes ~40 minutes, so that pre-check
    # guaranteed nothing about a live development machine: any edit landing during
    # the run made the result describe a tree that is not the commit being pushed.
    # Worse than a one-off wrong verdict, the result is RECORDED in proof_graph and
    # handed back later by reusable_verification -- a green proof for a commit whose
    # suite was never run against it.
    #
    # TRACKED content only: a test command that writes coverage output or a scratch
    # file into the repo is doing its job, and counting that would mean such a
    # project could never earn a proof. See _tracked_content_still_matches.
    passed = proc.returncode == 0
    if not _tracked_content_still_matches(repo, commit):
        return False, _tree_drifted_verdict(commit)
    try:
        proof_graph.record_verification(repo, commit, command, "test", passed)
    except (AttributeError, TypeError):
        pass  # recording is an optimisation; the verdict below is what gates.

    if passed:
        return True, f"full suite green for {commit[:12]}"
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-40:]
    return False, (
        f"FULL SUITE RED for {commit[:12]} using `{command}`, twice.\n"
        "A green build only proves the tree compiles. These tests say it does not work.\n\n"
        + "\n".join(tail)
    )


# ── CONTENT GUARD ────────────────────────────────────────────────────────────
#
# Proof-based gating did not stop the 2026-08-13 incident and could not have.
# The build gate asks "is there a green proof for this commit". The test gate
# asks "does the suite pass". Neither asks whether the commit is obviously
# destructive, and neither noticed that the commit they approved was not the
# commit that shipped.
#
# What reached master:
#
#   ef27653f  author: test <test@example.com>  message: "init"
#   7063 files changed, 1 insertion(+), 1508930 deletions(-)
#
# It deleted package.json, vercel.json, every source file, and .github/workflows
# — which is why GitHub recorded no CI runs for it: the commit removed the CI.
#
# These checks are cheap, need no proof graph, no build and no network, and each
# refuses that push on its own.

#: Identities belonging to test fixtures. A commit authored by one of these was
#: written by a test, not a person, and has no business on a production ref.
FIXTURE_AUTHORS = {
    "test@example.com", "test@test", "t@t", "you@example.com",
    "test@localhost", "fixture@example.com",
}

#: A push may not remove more than this fraction of the tracked tree.
MAX_DELETION_RATIO = float(os.environ.get("ORCH_MAX_DELETION_RATIO", "0.5"))

#: ...unless the tree was smaller than this, where a large proportional delete
#: is unremarkable and blocking it would just train people to bypass the guard.
DELETION_FLOOR_FILES = 25


def _tree_file_count(repo, commit):
    out = _git(repo, "ls-tree", "-r", "--name-only", commit)
    return len([line for line in out.splitlines() if line.strip()])


def verify_content(repo, old_commit, new_commit):
    """Refuse a push on what it contains. No proof required, no network."""
    if not old_commit or old_commit == ZERO_SHA:
        return True, "new ref — no prior tree to compare"

    try:
        authors = _git(repo, "log", "--format=%ae", f"{old_commit}..{new_commit}").splitlines()
    except subprocess.CalledProcessError as err:
        return False, f"cannot read the commit range ({err}); refusing rather than guessing."
    fixture = sorted({a.strip() for a in authors if a.strip().lower() in FIXTURE_AUTHORS})
    if fixture:
        return False, (
            f"REFUSING: commits in this push are authored by a test fixture ({', '.join(fixture)}).\n"
            "A commit written by a test is not a change anyone made. This is how a vitest "
            "fixture's tree reached master on 2026-08-13.\n"
            "If a real person genuinely has this identity, fix the identity, not this guard."
        )

    try:
        before = _tree_file_count(repo, old_commit)
        after = _tree_file_count(repo, new_commit)
    except subprocess.CalledProcessError as err:
        return False, f"cannot count the trees ({err}); refusing rather than guessing."
    if before >= DELETION_FLOOR_FILES and after < before * (1 - MAX_DELETION_RATIO):
        removed = before - after
        return False, (
            f"REFUSING: this push removes {removed} of {before} tracked files "
            f"({removed / before:.0%} of the tree).\n"
            "A production ref does not lose most of its files in one push. If the deletion is "
            "real, do it on a branch and merge it where a human sees the diff.\n"
            "Override with ORCH_MAX_DELETION_RATIO if you mean it."
        )

    return True, f"content sane: {before} -> {after} files, no fixture authorship"


def verify_immutable_ref(local_ref, local_sha, repo):
    """A production push must name a SHA or a branch, never a moving target.

    THIS IS THE DEFECT THAT SHIPPED ef27653f, and it defeats every other check
    here. `git push origin HEAD:master` prints its plan, runs this hook, and only
    THEN resolves HEAD. The hook runs the repo's full suite. On 2026-08-13 that
    suite committed to the repository it was running in, HEAD moved, and git sent
    the new commit — so the guard verified 0c0a8048 and GitHub received ef27653f.

    A gate that approves one commit while a different one ships is not a gate.
    """
    if local_ref not in ("HEAD", "refs/heads/HEAD"):
        return True, f"immutable source ref {local_ref}"
    try:
        now = _git(repo, "rev-parse", "HEAD")
    except subprocess.CalledProcessError:
        now = "<unreadable>"
    moved = now != local_sha
    return False, (
        "REFUSING: this push names HEAD as its source.\n"
        "git resolves HEAD AFTER this hook runs, so anything the hook does — including running "
        "the test suite — can move it, and the commit that ships is then not the commit that "
        "was verified. That is exactly how ef27653f reached master on 2026-08-13.\n"
        f"  verified: {local_sha[:12]}\n"
        f"  HEAD now: {now[:12]}{'   <-- ALREADY MOVED' if moved else ''}\n"
        "Push an explicit commit instead:  git push origin <sha>:refs/heads/master"
    )


def main(stdin=None):
    repo = _git(os.getcwd(), "rev-parse", "--show-toplevel")
    updates = guarded_updates(stdin if stdin is not None else sys.stdin)
    for local_ref, commit, remote_ref, remote_commit in updates:
        # ORDER IS DELIBERATE, AND THESE TWO COME FIRST.
        #
        # They are the only checks that would have stopped 2026-08-13, they cost
        # milliseconds, and neither can be satisfied by a proof. Running them
        # before changes_affect_build also closes a hole: that function can SKIP
        # verification entirely when it decides no deploy-root files changed, and
        # a commit deleting the whole tree should never reach a code path that
        # can choose not to look at it.
        ref_ok, ref_log = verify_immutable_ref(local_ref, commit, repo)
        if not ref_ok:
            print("production_push_guard: BLOCKED — mutable source ref", file=sys.stderr)
            print(ref_log, file=sys.stderr)
            return 1

        content_ok, content_log = verify_content(repo, remote_commit, commit)
        if not content_ok:
            print("production_push_guard: BLOCKED — refused on content", file=sys.stderr)
            print(content_log, file=sys.stderr)
            return 1
        print(f"production_push_guard: CONTENT OK — {content_log}", file=sys.stderr)

        if not changes_affect_build(repo, remote_commit, commit):
            print(f"production_push_guard: SKIPPED build/test — no deploy-root changes for {remote_ref}", file=sys.stderr)
            continue
        print(f"production_push_guard: verifying {commit[:12]} for {remote_ref} in Vercel context", file=sys.stderr)
        ok, log = verify(repo, commit)
        if not ok:
            print("production_push_guard: BLOCKED red production push", file=sys.stderr)
            print(log[-6000:], file=sys.stderr)
            return 1
        print(f"production_push_guard: BUILD GREEN — {log.splitlines()[0] if log else commit[:12]}", file=sys.stderr)

        tests_ok, test_log = verify_tests(repo, commit)
        if not tests_ok:
            # DELIBERATELY A DIFFERENT SWITCH FROM THE BUILD OVERRIDE.
            #
            # ORCH_ALLOW_UNVERIFIED_PROD_PUSH means "I verified the build myself".
            # Letting it also wave through a red suite would mean anyone reaching for
            # it for a build reason silently waives the test gate too — the gate would
            # be off far more often than anyone intended, and nobody would know.
            # Shipping known-red tests is a separate decision and needs a separate,
            # explicit act.
            if os.environ.get("ORCH_ALLOW_RED_TESTS", "").lower() in {"1", "true", "yes", "on"}:
                print("production_push_guard: SHIPPING RED TESTS — ORCH_ALLOW_RED_TESTS is set", file=sys.stderr)
                print(test_log[-6000:], file=sys.stderr)
            else:
                print("production_push_guard: BLOCKED — production push without a green suite", file=sys.stderr)
                print(test_log[-6000:], file=sys.stderr)
                print("Set ORCH_ALLOW_RED_TESTS=1 to ship anyway. That is a separate switch from "
                      "ORCH_ALLOW_UNVERIFIED_PROD_PUSH on purpose.", file=sys.stderr)
                return 1
        else:
            print(f"production_push_guard: TESTS GREEN — {test_log.splitlines()[0]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
