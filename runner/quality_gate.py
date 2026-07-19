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
import os, sys, subprocess, re

# Security: allowed command prefixes to prevent arbitrary execution via env vars
_ALLOWED_CMD_PREFIXES = ("npx ", "npm ", "node ", "python ", "python3 ", "pytest ", "jest ")


def _validate_repo_path(repo):
    """Validate repo path to prevent path-traversal and injection."""
    resolved = os.path.realpath(repo)
    if not os.path.isdir(resolved):
        raise ValueError(f"quality_gate: repo path does not exist: {resolved}")
    # Block paths outside typical project directories
    if "\x00" in repo or ".." in repo.split(os.sep):
        raise ValueError(f"quality_gate: suspicious path component in: {repo}")
    return resolved


def _validate_cmd(cmd, label):
    """Validate that a command from env matches allowed prefixes."""
    stripped = cmd.strip()
    if not any(stripped.startswith(p) for p in _ALLOWED_CMD_PREFIXES):
        raise ValueError(
            f"quality_gate: {label} command '{stripped[:40]}...' does not match "
            f"allowed prefixes: {_ALLOWED_CMD_PREFIXES}"
        )
    return stripped


def run(repo):
    repo = _validate_repo_path(repo)
    notes, ok = [], True
    mut = os.environ.get("MUTATION_CMD")
    if mut:
        mut = _validate_cmd(mut, "MUTATION_CMD")
        r = subprocess.run(mut, cwd=repo, shell=True, capture_output=True, text=True)
        m = re.search(r"(\d+(\.\d+)?)\s*%", r.stdout or "")
        score = float(m.group(1)) if m else None
        floor = float(os.environ.get("MUTATION_MIN_SCORE", "0"))
        if r.returncode != 0 or (score is not None and score < floor):
            ok = False; notes.append(f"mutation {score}% < {floor}%")
        else:
            notes.append(f"mutation {score}%")
    prop = os.environ.get("PROPERTY_CMD")
    if prop:
        prop = _validate_cmd(prop, "PROPERTY_CMD")
        r = subprocess.run(prop, cwd=repo, shell=True, capture_output=True, text=True)
        if r.returncode != 0:
            ok = False; notes.append("property tests failed")
        else:
            notes.append("property tests passed")
    return {"pass": ok, "notes": "; ".join(notes) or "no extra quality gates configured"}


if __name__ == "__main__":
    print(run(sys.argv[1] if len(sys.argv) > 1 else "."))
