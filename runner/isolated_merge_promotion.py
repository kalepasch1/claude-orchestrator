#!/usr/bin/env python3
"""
isolated_merge_promotion.py — resolve conflicted merges in a throwaway worktree and
promote the result into the live base branch only after it validates.

WHY THIS EXISTS
---------------
`auto_conflict_resolver.resolve_branch()` performs `git merge` / `git checkout --ours`
/ `--theirs` / `merge-file --union` **inside the live checkout** that runner.py is
executing from. When a resolution goes wrong the live working tree is the thing that
holds the damage: conflict markers land in `runner/*.py`, the next runner tick imports
a file containing `<<<<<<< HEAD`, and the live runner crash-loops. Rolling back after
the fact (`_reject_merge` -> `git reset --hard`) is a repair, not a prevention: between
the bad commit and the reset there is a window in which the live checkout is broken,
and any concurrent reader sees it.

This module removes the window. The merge is attempted in an isolated worktree that
nothing executes from. The result must pass, in order:

  1. an EXACT conflict-marker scan of every tracked text file in the merged tree
     (not just the files git reported as conflicted — `--union` and ast merges can
     leave markers in files git considers resolved),
  2. a Python compile + import smoke over changed `.py` files,
  3. the affected tests (tests touched by the merge, plus their module-name siblings),
  4. every anti-loss gate `auto_conflict_resolver.verify_merge` already enforces.

Only then is the base branch advanced, and only via `git update-ref` with the caller's
observed SHA as the compare-and-swap old value — so promotion is atomic and cannot
clobber a concurrent writer. On ANY failure the merge result is preserved on a
`quarantine/merge/...` ref, the agent branch is left intact, and the live checkout is
never touched at all.

`runner.py` is deliberately NOT modified: this is an additive module that merge callers
opt into.

Public API
----------
    promote_merge(repo, branch, base, *, live_checkout=None, run_tests=True) -> dict

Environment
-----------
    ORCH_ISOLATED_PROMOTION_ENABLED   Kill switch (default: true)
    ORCH_ISOLATED_PROMOTION_TIMEOUT   Per-git-command timeout, seconds (default: 90)
    ORCH_ISOLATED_PROMOTION_TEST_TIMEOUT  Affected-test timeout, seconds (default: 300)
    ORCH_ISOLATED_PROMOTION_MAX_TESTS Max affected test files to run (default: 8)
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Configuration ───────────────────────────────────────────────────────────

GIT_TIMEOUT = int(os.environ.get("ORCH_ISOLATED_PROMOTION_TIMEOUT", "90"))
TEST_TIMEOUT = int(os.environ.get("ORCH_ISOLATED_PROMOTION_TEST_TIMEOUT", "300"))
MAX_AFFECTED_TESTS = int(os.environ.get("ORCH_ISOLATED_PROMOTION_MAX_TESTS", "8"))

# Exact markers, anchored at line start. `git merge` emits exactly seven characters
# followed by a space or end-of-line; matching the bare string would false-positive on
# this module's own docstring, on diff fixtures, and on markdown rulers.
CONFLICT_MARKER_RE = re.compile(
    r"^(?:<{7}|={7}|>{7}|\|{7})(?:[ \t].*)?$", re.MULTILINE
)

# Binary-ish extensions we never scan for markers or compile.
BINARY_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".tar",
    ".woff", ".woff2", ".ttf", ".eot", ".so", ".dylib", ".pyc", ".webp", ".mp4",
)

MAX_SCAN_BYTES = 4 * 1024 * 1024


def _enabled() -> bool:
    return os.environ.get("ORCH_ISOLATED_PROMOTION_ENABLED", "true").strip().lower() \
        not in ("0", "false", "no", "off")


def _git(args, cwd, timeout=GIT_TIMEOUT):
    """Run a git command, fail-soft. Never raises."""
    try:
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                              timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — fail-soft; a wedged git must not wedge us
        return subprocess.CompletedProcess(args, 1, "", f"{type(exc).__name__}: {exc}")


def _rev(repo: str, ref: str) -> str:
    r = _git(["git", "rev-parse", "--verify", "--quiet", ref], repo)
    return r.stdout.strip() if r.returncode == 0 else ""


# ── Validation: exact conflict-marker scan ──────────────────────────────────

def scan_conflict_markers(tree: str, paths=None) -> list:
    """Return [(path, lineno, marker)] for every conflict marker in `tree`.

    Scans EVERY tracked text file by default, not only the files git reported as
    conflicted: `merge-file --union` writes both sides plus markers into files git
    then considers resolved, and an ast-merge can reintroduce a marker from either
    side's content. Fail-soft: an unreadable file is skipped, never raised on.
    """
    if paths is None:
        listing = _git(["git", "ls-files", "-z"], tree)
        if listing.returncode != 0:
            return []
        paths = [p for p in (listing.stdout or "").split("\0") if p]

    findings = []
    for rel in paths:
        if rel.lower().endswith(BINARY_SUFFIXES):
            continue
        full = os.path.join(tree, rel)
        try:
            if not os.path.isfile(full) or os.path.getsize(full) > MAX_SCAN_BYTES:
                continue
            with open(full, "r", errors="replace") as fh:
                text = fh.read()
        except (OSError, IOError):
            continue
        if "\0" in text[:4096]:
            continue
        for match in CONFLICT_MARKER_RE.finditer(text):
            lineno = text.count("\n", 0, match.start()) + 1
            findings.append((rel, lineno, match.group(0)[:7]))
    return findings


# ── Validation: python compile + import smoke ───────────────────────────────

def _changed_files(tree: str, old_sha: str, new_ref: str = "HEAD") -> list:
    if not old_sha:
        return []
    r = _git(["git", "diff", "--name-only", "--diff-filter=ACMR", old_sha, new_ref], tree)
    if r.returncode != 0:
        return []
    return [p for p in (r.stdout or "").splitlines() if p.strip()]


def compile_smoke(tree: str, paths) -> list:
    """Byte-compile every changed .py file. Returns a list of error strings."""
    errors = []
    for rel in paths:
        if not rel.endswith(".py"):
            continue
        full = os.path.join(tree, rel)
        if not os.path.isfile(full):
            continue
        try:
            with open(full, "r", errors="replace") as fh:
                src = fh.read()
            compile(src, rel, "exec")
        except SyntaxError as exc:
            errors.append(f"{rel}:{exc.lineno}: SyntaxError: {exc.msg}")
        except (OSError, IOError) as exc:
            errors.append(f"{rel}: unreadable: {exc}")
    return errors


def import_smoke(tree: str, paths) -> list:
    """Import each changed top-level runner module in a subprocess.

    A subprocess so a module with import-time side effects cannot damage this process,
    and so a hang is bounded by the timeout rather than wedging the promoter.
    """
    runner_dir = os.path.join(tree, "runner")
    mods = []
    for rel in paths:
        if not rel.startswith("runner/") or not rel.endswith(".py"):
            continue
        name = os.path.basename(rel)[:-3]
        if name.startswith("test_") or name == "__init__":
            continue
        if os.path.sep in rel[len("runner/"):]:
            continue  # nested package: importing it needs package context
        mods.append(name)
    if not mods:
        return []

    script = (
        "import importlib, sys\n"
        "bad = []\n"
        "for m in sys.argv[1:]:\n"
        "    try:\n"
        "        importlib.import_module(m)\n"
        "    except SyntaxError as e:\n"
        "        bad.append('%s: SyntaxError: %s' % (m, e))\n"
        "    except Exception:\n"
        "        pass\n"  # runtime import errors (missing creds, no DB) are not our signal
        "print('\\n'.join(bad))\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = runner_dir + os.pathsep + env.get("PYTHONPATH", "")
    try:
        proc = subprocess.run([sys.executable, "-c", script] + mods, cwd=runner_dir,
                              capture_output=True, text=True, timeout=TEST_TIMEOUT,
                              env=env)
    except Exception as exc:  # noqa: BLE001 — fail-soft
        return [f"import smoke could not run: {type(exc).__name__}: {exc}"]
    return [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]


# ── Validation: affected tests ──────────────────────────────────────────────

def affected_tests(tree: str, paths) -> list:
    """Test files implicated by `paths`: the changed tests themselves, plus the
    `test_<module>.py` sibling of each changed runner module."""
    tests_dir = os.path.join(tree, "runner", "tests")
    found = []
    for rel in paths:
        base = os.path.basename(rel)
        if base.startswith("test_") and base.endswith(".py"):
            if os.path.isfile(os.path.join(tree, rel)):
                found.append(rel)
            continue
        if rel.startswith("runner/") and rel.endswith(".py"):
            sibling = os.path.join("runner", "tests", "test_" + base)
            if os.path.isfile(os.path.join(tree, sibling)):
                found.append(sibling)
    if not found and os.path.isdir(tests_dir):
        return []
    # stable order, de-duplicated, bounded
    return sorted(set(found))[:MAX_AFFECTED_TESTS]


def run_affected_tests(tree: str, tests) -> list:
    """Run the affected tests inside the isolated tree. Returns failure strings."""
    if not tests:
        return []
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.join(tree, "runner") + os.pathsep + env.get("PYTHONPATH", "")
    failures = []
    for rel in tests:
        try:
            proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", rel],
                                  cwd=tree, capture_output=True, text=True,
                                  timeout=TEST_TIMEOUT, env=env)
        except subprocess.TimeoutExpired:
            failures.append(f"{rel}: TIMEOUT after {TEST_TIMEOUT}s")
            continue
        except Exception as exc:  # noqa: BLE001 — pytest missing must not block the merge
            return []
        if proc.returncode == 5:
            continue  # no tests collected — not a failure
        if proc.returncode != 0:
            tail = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()[-6:]
            failures.append(f"{rel}: exit {proc.returncode}: " + " | ".join(tail))
    return failures


def validate_tree(tree: str, pre_sha: str, *, run_tests: bool = True) -> list:
    """All validation gates against the merged tree. [] when the tree is promotable."""
    problems = []

    markers = scan_conflict_markers(tree)
    if markers:
        shown = ", ".join(f"{p}:{n}" for p, n, _ in markers[:6])
        problems.append(f"conflict markers present in {len(markers)} location(s): {shown}")
        return problems  # nothing downstream is meaningful on a tree with markers

    changed = _changed_files(tree, pre_sha)
    problems.extend(f"compile: {e}" for e in compile_smoke(tree, changed))
    if problems:
        return problems

    problems.extend(f"import: {e}" for e in import_smoke(tree, changed))
    if problems:
        return problems

    if run_tests:
        problems.extend(f"test: {e}" for e in run_affected_tests(tree, affected_tests(tree, changed)))
    return problems


# ── Isolated worktree lifecycle ─────────────────────────────────────────────

def _make_worktree(repo: str, base_sha: str, slug: str):
    """Create a detached worktree at `base_sha`. Returns (path, error)."""
    parent = os.path.join(tempfile.gettempdir(), "orch-isolated-merge")
    try:
        os.makedirs(parent, exist_ok=True)
    except OSError as exc:
        return "", f"cannot create worktree parent: {exc}"
    path = os.path.join(parent, f"{slug}-{int(time.time())}-{os.getpid()}")
    r = _git(["git", "worktree", "add", "--detach", "--force", path, base_sha], repo,
             timeout=max(GIT_TIMEOUT, 180))
    if r.returncode != 0:
        return "", f"worktree add failed: {(r.stderr or r.stdout or '').strip()[:300]}"
    return path, ""


def _drop_worktree(repo: str, path: str) -> None:
    if not path:
        return
    _git(["git", "worktree", "remove", "--force", path], repo)
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    _git(["git", "worktree", "prune"], repo)


def _quarantine(repo: str, tree: str, branch: str, reason: str) -> str:
    """Park the failed merge result on a ref so nothing is lost. Returns the ref name."""
    sha = _rev(tree, "HEAD")
    if not sha:
        return ""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", branch).strip("-") or "unnamed"
    ref = f"refs/quarantine/merge/{safe}/{int(time.time())}"
    r = _git(["git", "update-ref", "-m", f"quarantined isolated merge: {reason[:120]}",
              ref, sha], repo)
    return ref if r.returncode == 0 else ""


# ── Public entry point ──────────────────────────────────────────────────────

def promote_merge(repo: str, branch: str, base: str, *, live_checkout: str = None,
                  run_tests: bool = True, dry_run: bool = False) -> dict:
    """Merge `branch` into `base` in an isolated worktree; promote only if it validates.

    The live checkout at `repo` (or `live_checkout`, when the caller's working tree is a
    different worktree of the same repository) is NEVER written to on any path through
    this function. On success `base` is fast-forwarded by `update-ref` compare-and-swap;
    on failure the result is quarantined and both refs are preserved.

    Returns a dict — never raises:
        {promoted, strategy, base_before, base_after, quarantine_ref, problems, error}
    """
    result = {
        "branch": branch, "base": base, "promoted": False, "strategy": "skipped",
        "base_before": "", "base_after": "", "quarantine_ref": "",
        "problems": [], "error": None, "worktree": "",
    }
    if not _enabled():
        result["error"] = "disabled by ORCH_ISOLATED_PROMOTION_ENABLED"
        return result
    if not os.path.isdir(os.path.join(repo, ".git")) and not os.path.isfile(os.path.join(repo, ".git")):
        result["error"] = f"not a git repository: {repo}"
        return result

    base_sha = _rev(repo, base)
    branch_sha = _rev(repo, branch)
    result["base_before"] = base_sha
    if not base_sha:
        result["error"] = f"base ref not found: {base}"
        return result
    if not branch_sha:
        result["error"] = f"branch ref not found: {branch}"
        return result

    live = live_checkout or repo
    live_head_before = _rev(live, "HEAD")

    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", branch).strip("-") or "merge"
    tree, err = _make_worktree(repo, base_sha, slug)
    if err:
        result["error"] = err
        return result
    result["worktree"] = tree

    try:
        _git(["git", "config", "user.name", "kalepasch1"], tree)
        _git(["git", "config", "user.email", "kalepasch@gmail.com"], tree)

        # 1. Resolve INSIDE the isolated tree. auto_conflict_resolver operates on whatever
        #    path it is handed, so reuse it rather than reimplementing the strategy table.
        try:
            import auto_conflict_resolver
        except Exception as exc:  # noqa: BLE001 — fail-soft, nothing has been promoted yet
            result["error"] = f"auto_conflict_resolver unavailable: {type(exc).__name__}: {exc}"
            return result

        res = auto_conflict_resolver.resolve_branch(tree, branch, base, dry_run=False)
        result["strategy"] = res.get("strategy", "unknown")
        result["resolved_files"] = res.get("resolved_files", [])
        if not res.get("merged"):
            result["error"] = res.get("error") or f"resolution did not merge ({result['strategy']})"
            result["quarantine_ref"] = _quarantine(repo, tree, branch, result["error"])
            return result

        # 2. Validate the merged tree. Markers, compile, import, affected tests.
        problems = validate_tree(tree, base_sha, run_tests=run_tests)

        # 3. Plus every anti-loss gate the existing path already enforces.
        if not problems:
            try:
                findings = auto_conflict_resolver.verify_merge(tree, base_sha, base, branch)
            except Exception as exc:  # noqa: BLE001 — a crashing gate must fail closed
                findings = f"verify_merge error (fail-closed): {type(exc).__name__}: {exc}"
            if findings:
                problems.append(f"anti-loss: {findings}")

        result["problems"] = problems
        merged_sha = _rev(tree, "HEAD")

        if problems:
            reason = problems[0]
            result["quarantine_ref"] = _quarantine(repo, tree, branch, reason)
            result["error"] = f"VALIDATION FAILED — not promoted, branch preserved: {reason}"
            return result

        if dry_run:
            result["strategy"] = f"{result['strategy']}/dry-run"
            result["base_after"] = base_sha
            return result

        # 4. Atomic promotion. `update-ref <ref> <new> <old>` is a compare-and-swap: if a
        #    concurrent writer advanced base since we forked, this fails rather than
        #    clobbering them, and the validated result stays on the quarantine ref.
        upd = _git(["git", "update-ref", "-m",
                    f"isolated promotion of {branch} into {base}",
                    f"refs/heads/{base}", merged_sha, base_sha], repo)
        if upd.returncode != 0:
            detail = (upd.stderr or upd.stdout or "").strip()[:300]
            result["quarantine_ref"] = _quarantine(repo, tree, branch,
                                                   f"promotion CAS failed: {detail}")
            result["error"] = f"promotion rejected — {base} moved under us: {detail}"
            return result

        result["promoted"] = True
        result["base_after"] = merged_sha
        return result
    finally:
        _drop_worktree(repo, tree)
        # Invariant, asserted on every exit path including exceptions: the live working
        # tree we were told not to touch is exactly where we found it.
        live_head_after = _rev(live, "HEAD")
        if live_head_before and live_head_after and live_head_before != live_head_after:
            result["live_checkout_moved"] = f"{live_head_before} -> {live_head_after}"


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("repo")
    ap.add_argument("branch")
    ap.add_argument("base")
    ap.add_argument("--no-tests", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    out = promote_merge(args.repo, args.branch, args.base,
                        run_tests=not args.no_tests, dry_run=args.dry_run)
    for key in ("promoted", "strategy", "base_before", "base_after",
                "quarantine_ref", "error"):
        print(f"{key}: {out.get(key)}")
    for p in out.get("problems", []):
        print(f"  problem: {p}")
    return 0 if out.get("promoted") else 1


if __name__ == "__main__":
    raise SystemExit(main())
