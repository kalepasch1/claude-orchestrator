#!/usr/bin/env python3
"""
quality_gate.py - raise the bar on "tests pass" before an autonomous merge. Runs optional
mutation testing and property-based tests (if configured) in addition to the unit suite, so
green actually means something.

Configure per repo via env (or a .orchestrator-quality file):
  MUTATION_CMD="npx stryker run"      PROPERTY_CMD="npm run test:property"
  MUTATION_MIN_SCORE=60               # fail if mutation score below this
Returns {"pass": bool, "notes": "..."}; skips gracefully if nothing configured.
"""
import os, sys, subprocess, re, shlex


def _run_cmd(cmd_str, cwd):
    """Run a command string safely using shlex tokenisation instead of shell=True."""
    try:
        argv = shlex.split(cmd_str)
    except ValueError:
        # Malformed quoting — refuse to run rather than falling back to shell
        return subprocess.CompletedProcess(args=cmd_str, returncode=1,
                                           stdout="", stderr="shlex parse error")
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True)


def run(repo):
    notes, ok = [], True
    mut = os.environ.get("MUTATION_CMD")
    if mut:
        r = _run_cmd(mut, cwd=repo)
        m = re.search(r"(\d+(\.\d+)?)\s*%", r.stdout or "")
        score = float(m.group(1)) if m else None
        floor = float(os.environ.get("MUTATION_MIN_SCORE", "0"))
        if r.returncode != 0 or (score is not None and score < floor):
            ok = False; notes.append(f"mutation {score}% < {floor}%")
        else:
            notes.append(f"mutation {score}%")
    prop = os.environ.get("PROPERTY_CMD")
    if prop:
        r = _run_cmd(prop, cwd=repo)
        if r.returncode != 0:
            ok = False; notes.append("property tests failed")
        else:
            notes.append("property tests passed")
    return {"pass": ok, "notes": "; ".join(notes) or "no extra quality gates configured"}


if __name__ == "__main__":
    print(run(sys.argv[1] if len(sys.argv) > 1 else "."))
