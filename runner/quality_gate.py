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


def _validate_repo_path(repo):
    """Validate and normalize a repo path. Raise if doesn't exist or isn't a directory."""
    if not repo:
        raise ValueError("repo path cannot be empty")
    repo = os.path.abspath(os.path.expanduser(repo))
    if not os.path.isdir(repo):
        raise FileNotFoundError(f"repo path not a directory: {repo}")
    return repo


def _run_cmd(cmd_str, cwd):
    """Run a command string safely using shlex tokenisation instead of shell=True."""
    try:
        argv = shlex.split(cmd_str)
    except ValueError:
        # Malformed quoting — refuse to run rather than falling back to shell
        return subprocess.CompletedProcess(args=cmd_str, returncode=1,
                                           stdout="", stderr="shlex parse error")
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True)


#: Lines that state the mutation score, most specific first. Stryker's summary line is
#: "Mutation score: 72.40%"; other runners spell it "mutation score based on covered code".
_SCORE_PATTERNS = (
    r"mutation\s+score[^\n%]*?(\d+(?:\.\d+)?)\s*%",
    r"(\d+(?:\.\d+)?)\s*%[^\n]*mutation\s+score",
)


def _mutation_score(stdout):
    """The mutation score percentage in `stdout`, or None if it cannot be read.

    Prefers a percentage explicitly labelled as the mutation score. A bare percentage is
    only used as a last resort, and then the LAST one — mutation runners stream progress
    ("12% of files done") and coverage percentages before the summary, so the first match is
    almost never the score. The old `re.search(r"(\\d+(\\.\\d+)?)\\s*%", ...)` took the first
    one it found and compared that to the floor.
    """
    for pattern in _SCORE_PATTERNS:
        matches = re.findall(pattern, stdout or "", re.IGNORECASE)
        if matches:
            return float(matches[-1])
    bare = re.findall(r"(\d+(?:\.\d+)?)\s*%", stdout or "")
    return float(bare[-1]) if bare else None


def run(repo):
    repo = _validate_repo_path(repo)
    notes, ok = [], True
    mut = os.environ.get("MUTATION_CMD")
    if mut:
        r = _run_cmd(mut, cwd=repo)
        floor = float(os.environ.get("MUTATION_MIN_SCORE", "0"))
        score = _mutation_score(r.stdout or "")

        # A GATE THAT CANNOT FAIL IS NOT A GATE.
        #
        # Two ways this one could not: it read the FIRST percentage in stdout (see
        # _mutation_score — stryker prints progress and coverage percentages long before the
        # score, so the gate routinely compared the wrong number against the floor), and an
        # unparseable score was treated as a pass. `score is not None and score < floor` means
        # a run whose output format changed, or that printed no percentage at all, sailed
        # through with "mutation None%" recorded as success. That is the exact failure a
        # quality gate exists to prevent, and it is silent.
        #
        # Now: no score with a floor configured is a failure. With no floor (the default 0)
        # there is nothing to enforce, so an unreadable score stays a pass and merely says so.
        if r.returncode != 0:
            ok = False; notes.append(f"mutation command failed (exit {r.returncode})")
        elif score is None:
            if floor > 0:
                ok = False; notes.append(f"mutation score unreadable, floor {floor}% unverified")
            else:
                notes.append("mutation score unreadable (no floor configured)")
        elif score < floor:
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
