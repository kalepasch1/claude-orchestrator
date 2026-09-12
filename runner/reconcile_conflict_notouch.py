#!/usr/bin/env python3
"""
reconcile_conflict_notouch.py — prove a reconciliation left CONFLICTED evidence alone.

WHY THIS EXISTS
---------------
`reconcile_followup_queue.py` already turns every CONFLICTED_NEEDS_FOCUSED_TASK item
into exactly one durable queue row. That covers half the contract. The other half is
the *negative* claim: that the recovery worktree did NOT quietly resolve those same
conflicts on the side — a `git checkout --theirs`, a "while I was in there" hunk, an
overwrite that looks like progress and silently discards the newer implementation.

A summary saying "left conflicted items for focused tasks" is unverifiable. This module
makes it a boolean by diffing the recovery branch against its pre-recovery baseline and
intersecting the changed paths with the paths attributable to conflicted evidence. Any
overlap is a violation, named path by path.

Two gates, both pure and therefore testable without a repo:

  * `notouch_gate(records, changed_paths)`  — no conflicted path was modified.
  * `exactly_one_gate(records, plans)`      — one follow-up per conflicted item, no
                                              more (fan-out) and no fewer (silent drop).

`run()` wires them to a real repo via `changed_paths()`, which is fail-soft: an
unreadable repo yields an explicit error rather than a false pass. A gate that cannot
see the diff must not claim the diff was clean.

Public API
----------
    conflicted_paths(records)                         -> {path: [source, ...]}
    changed_paths(repo, baseline_ref, branch_ref)     -> (paths, error)
    notouch_gate(records, changed)                    -> dict
    exactly_one_gate(records, plans)                  -> dict
    run(records, plans, *, repo, baseline_ref, ...)   -> dict

Environment
-----------
    ORCH_NOTOUCH_GATE_ENABLED   Kill switch (default: true)
    ORCH_NOTOUCH_GIT_TIMEOUT    Seconds for each git call (default: 60)
"""
from __future__ import annotations

import json
import os
import subprocess
import time

CONFLICTED = "CONFLICTED_NEEDS_FOCUSED_TASK"

GIT_TIMEOUT = int(os.environ.get("ORCH_NOTOUCH_GIT_TIMEOUT", "60"))


def _enabled() -> bool:
    return os.environ.get("ORCH_NOTOUCH_GATE_ENABLED", "true").strip().lower() \
        not in ("0", "false", "no", "off")


def _git(repo, *args, timeout: int = GIT_TIMEOUT):
    """Run git in `repo`. Returns (rc, stdout, stderr); never raises."""
    try:
        proc = subprocess.run(("git", "-C", str(repo)) + tuple(args),
                              capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except (OSError, subprocess.SubprocessError) as exc:  # noqa: BLE001 — fail-soft
        return 1, "", f"{type(exc).__name__}: {exc}"


# ── Attribution (pure) ──────────────────────────────────────────────────────

def _record_paths(record: dict) -> list:
    """Every path a record points at, from whichever field carries it.

    Classifiers have historically written `paths`, `files` or a single `path`; a gate
    that only reads one of them silently passes items it never inspected.
    """
    out = []
    for key in ("paths", "files"):
        value = record.get(key)
        if isinstance(value, (list, tuple)):
            out.extend(str(v).strip() for v in value if str(v).strip())
        elif isinstance(value, str) and value.strip():
            out.append(value.strip())
    single = record.get("path")
    if isinstance(single, str) and single.strip():
        out.append(single.strip())
    # Normalise leading "./" so "./runner/x.py" and "runner/x.py" collide as they should.
    return [p[2:] if p.startswith("./") else p for p in out]


def conflicted_paths(records) -> dict:
    """Map every conflicted-evidence path to the source refs that claim it."""
    attributed: dict = {}
    for record in records or []:
        if str(record.get("classification") or "").upper() != CONFLICTED:
            continue
        source = record.get("source") or record.get("name") or ""
        for path in _record_paths(record):
            attributed.setdefault(path, [])
            if source not in attributed[path]:
                attributed[path].append(source)
    return attributed


# ── Observation (fail-soft) ─────────────────────────────────────────────────

def changed_paths(repo, baseline_ref: str, branch_ref: str = "HEAD"):
    """Paths the branch changed relative to the merge base with `baseline_ref`.

    Returns `(paths, error)`. `error` non-empty means the diff could not be read, and
    the caller MUST treat that as gate failure — an unobserved diff is not a clean one.
    """
    if not baseline_ref:
        return [], "no baseline ref given"
    rc, out, err = _git(repo, "diff", "--name-only", f"{baseline_ref}...{branch_ref}")
    if rc != 0:
        # Fall back to a two-dot diff: a shallow clone or a detached baseline can make
        # the merge base unresolvable while a direct comparison still works.
        rc, out, err = _git(repo, "diff", "--name-only", baseline_ref, branch_ref)
    if rc != 0:
        return [], (err or "git diff failed").strip().splitlines()[-1][:300]
    return [line.strip() for line in out.splitlines() if line.strip()], ""


# ── Gates (pure) ────────────────────────────────────────────────────────────

def notouch_gate(records, changed) -> dict:
    """Fail if the recovery branch modified any path attributable to conflicted items."""
    attributed = conflicted_paths(records)
    changed_set = {p[2:] if p.startswith("./") else p for p in (changed or [])}
    violations = [
        {"path": path, "sources": sources}
        for path, sources in sorted(attributed.items()) if path in changed_set
    ]
    return {
        "ok": not violations,
        "violations": violations,
        "conflicted_paths": sorted(attributed),
        "changed_count": len(changed_set),
    }


def exactly_one_gate(records, plans) -> dict:
    """Each conflicted item must map to exactly one queued/adopted follow-up slug."""
    by_source: dict = {}
    for plan in plans or []:
        source = plan.get("source") or ""
        if str(plan.get("classification") or "").upper() != CONFLICTED:
            continue
        slug = plan.get("queued_slug") or plan.get("slug") or ""
        by_source.setdefault(source, [])
        if slug and slug not in by_source[source]:
            by_source[source].append(slug)

    missing, duplicated, covered = [], [], 0
    for record in records or []:
        if str(record.get("classification") or "").upper() != CONFLICTED:
            continue
        source = record.get("source") or record.get("name") or ""
        slugs = by_source.get(source) or []
        if not slugs:
            missing.append(source)
        elif len(slugs) > 1:
            duplicated.append({"source": source, "slugs": slugs})
        else:
            covered += 1

    return {"ok": not missing and not duplicated, "missing": missing,
            "duplicated": duplicated, "covered": covered}


def run(records, plans, *, repo, baseline_ref: str, branch_ref: str = "HEAD") -> dict:
    """Observe the diff and run both gates. Returns a report; never raises."""
    report = {"ok": False, "notouch": None, "exactly_one": None, "error": None,
              "baseline_ref": baseline_ref, "branch_ref": branch_ref,
              "stamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if not _enabled():
        report["error"] = "disabled by ORCH_NOTOUCH_GATE_ENABLED"
        return report

    changed, err = changed_paths(repo, baseline_ref, branch_ref)
    report["exactly_one"] = exactly_one_gate(records, plans)
    if err:
        # Deliberately NOT fail-soft into a pass: the whole point is the negative claim.
        report["error"] = f"could not read diff: {err}"
        report["notouch"] = {"ok": False, "violations": [], "conflicted_paths": [],
                             "changed_count": 0}
        return report

    report["notouch"] = notouch_gate(records, changed)
    report["ok"] = bool(report["notouch"]["ok"] and report["exactly_one"]["ok"])
    return report


def main(argv=None) -> int:
    import argparse
    import sys
    ap = argparse.ArgumentParser(
        description="Verify a recovery branch left CONFLICTED evidence untouched.")
    ap.add_argument("records_json", help="JSON list of classified records, or - for stdin")
    ap.add_argument("--plans-json", default="",
                    help="JSON list of plans from reconcile_followup_queue.plan_followups")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--baseline-ref", required=True,
                    help="pre-recovery baseline, e.g. origin/master")
    ap.add_argument("--branch-ref", default="HEAD")
    args = ap.parse_args(argv)

    try:
        raw = sys.stdin.read() if args.records_json == "-" else open(args.records_json).read()
        records = json.loads(raw)
        plans = json.loads(open(args.plans_json).read()) if args.plans_json else []
    except (OSError, ValueError) as exc:
        print(f"could not read input: {exc}")
        return 2

    report = run(records, plans, repo=args.repo, baseline_ref=args.baseline_ref,
                 branch_ref=args.branch_ref)
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
