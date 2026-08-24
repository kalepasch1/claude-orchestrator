#!/usr/bin/env python3
"""ci_gate.py — what `npm test` runs. Exits non-zero when it should.

WHY THIS EXISTS
---------------
`npm test` used to be:

    python3 -m pytest runner/tests/ -x --tb=short -q 2>&1 || true

The `|| true` meant it exited 0 unconditionally. Verified against
origin/master@5c4eaf2f: the suite is red, `-x` stops at the first failure, and
`npm test` still exited 0.

That is not a cosmetic problem, because `npm test` is the DEFAULT `TEST_CMD` for six
production modules — approval_merge.py (the merge gate), autonomous_test_runner.py,
continuous_test_runner.py, continuous_test.py, cade_tournaments.py and build_gate.py.
Every one of them was reading an unconditional success as "tests passed". The fleet's
merge gate had no test signal at all; it only believed it did.

WHY NOT JUST DELETE `|| true`
-----------------------------
Because the full suite is red today (~70+ pre-existing failures) and does not reliably
terminate — two full runs stalled at 31% and 14%. Removing the swallow with nothing
else would take the merge train from "always green" to "always red", which is not an
improvement, and `.github/workflows/ci.yml` argues at length against exactly that
("a CI job that is red on arrival just teaches people to ignore CI").

So `npm test` now runs the same beachhead CI actually gates on: the offline guard
tests plus a syntax check of every module. It is fast, it is green today, and — the
whole point — it can fail. `npm run test:full` runs the entire suite, also honestly.

Keeping this in one Python file rather than a shell one-liner means the behaviour is
testable, which is what test_ci_gate.py does.
"""
from __future__ import annotations

import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNNER = os.path.join(REPO, "runner")


def _root_modules():
    """Root-level *.py files, sorted. Empty list if the repo cannot be read."""
    try:
        return sorted(f for f in os.listdir(REPO) if f.endswith(".py"))
    except OSError:
        return []


# Mirrors .github/workflows/ci.yml's `runner-guards` job. If that job changes, change
# this with it — the value of the gate is that local and CI agree.
STEPS = [
    ("offline guard tests",
     [sys.executable, "-m", "pytest", "tests/test_ci_offline.py", "-q", "--no-header"],
     RUNNER),
    ("syntax-check every runner module",
     [sys.executable, "-m", "compileall", "-q", "."],
     RUNNER),
    # CI runs `python -m compileall -q *.py` at the repo root — the shell expands the
    # glob, so it is root-level modules only, NOT a recursive walk. Expanded here rather
    # than passing "." so this gate agrees with CI exactly; a local gate that is stricter
    # than CI fails builds CI would pass, which is its own way of teaching people to
    # ignore it.
    ("syntax-check repo-root modules",
     [sys.executable, "-m", "compileall", "-q"] + _root_modules(),
     REPO),
]

# CI unsets these so a test that quietly reaches for the control plane fails here
# rather than passing and lying about what it covered.
OFFLINE_ENV = {"SUPABASE_URL": "", "SUPABASE_SERVICE_KEY": ""}

TIMEOUT_SEC = int(os.environ.get("ORCH_CI_GATE_TIMEOUT_SEC", "600"))


def run_step(name, cmd, cwd, env=None):
    """Run one step. Returns (ok, output). Never raises."""
    environ = dict(os.environ)
    environ.update(OFFLINE_ENV)
    if env:
        environ.update(env)
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=environ, capture_output=True,
                              text=True, timeout=TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        return False, f"{name}: timed out after {TIMEOUT_SEC}s"
    except OSError as exc:
        return False, f"{name}: could not run ({exc})"
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, output


def main(argv=None) -> int:
    failures = []
    for name, cmd, cwd in STEPS:
        ok, output = run_step(name, cmd, cwd)
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            failures.append((name, output))

    if failures:
        print("\n" + "=" * 70)
        for name, output in failures:
            print(f"\n--- {name} ---")
            print(output[-4000:])
        print("=" * 70)
        print(f"\nci_gate: {len(failures)} of {len(STEPS)} steps FAILED")
        return 1

    print(f"\nci_gate: all {len(STEPS)} steps passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
