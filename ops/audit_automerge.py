#!/usr/bin/env python3
"""audit_automerge.py — is any auto-resolved merge discarding branch-original work?

The standing form of the 2026-08-06 audit that found 6 of 59 auto-resolved merges on
master had dropped 28 files of branch-original work — including, pointedly, the commits
that fixed earlier instances of silent work loss ("restore stranded session work",
"dropped helpers restored", "restore corrupted _run_tests"). A one-off measurement
cannot notice a regression; this is re-runnable over any commit range.

For merge M with parents P1 (mainline) and P2 (branch), base = merge-base(P1,P2). For
every file the branch changed (base..P2), a DISCARD is recorded when the blob in M is
byte-identical to P1 while P1 and P2 disagree, AND at least one commit on base..P2 that
touched the file is not already an ancestor of P1.

That last condition is what keeps this quiet in the benign case: a branch merely carrying
mainline's own history loses nothing when mainline wins. A guard that shouted about that
would be switched off within a week.

Reachability is NOT evidence of survival: a commit stays in the log while a later merge
reverts its content. Only the blob comparison counts. That lesson generalises.

Usage
-----
    python3 ops/audit_automerge.py                      # last 30 days on HEAD
    python3 ops/audit_automerge.py --range A..B
    python3 ops/audit_automerge.py --since 2026-08-01 --until 2026-08-06
    python3 ops/audit_automerge.py --all-merges         # include hand merges
    python3 ops/audit_automerge.py --json               # machine-readable
    python3 ops/audit_automerge.py --repo /path/to/repo

Exit codes: 0 clean · 1 discards found · 2 the audit itself could not run.
An audit that cannot answer must not report "clean".
"""
import argparse
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "runner"))

try:
    import automerge_discard_guard as guard
except Exception as exc:  # pragma: no cover - import wiring
    print(f"audit_automerge: cannot import automerge_discard_guard: {exc}", file=sys.stderr)
    sys.exit(2)


def _explicit_merges(repo, since, until):
    """Merge shas in a date window, or None when no window was requested."""
    if not (since or until):
        return None
    args = ["git", "log", "--format=%H", "--merges"]
    if since:
        args.append(f"--since={since}")
    if until:
        args.append(f"--until={until}")
    r = subprocess.run(args, cwd=repo, capture_output=True, text=True, timeout=120)
    return [s.strip() for s in r.stdout.splitlines() if s.strip()]


def _audit_shas(repo, shas, auto_only):
    merges, audited, with_discards, files, errors = [], 0, 0, 0, []
    for sha in shas:
        res = guard.check_merge_commit(repo, sha)
        if res.get("skipped"):
            continue
        if auto_only and not res.get("auto_resolved"):
            continue
        audited += 1
        if not res["ok"]:
            errors.append({"merge_sha": sha, "error": res["error"]})
        if res["discards"]:
            with_discards += 1
            files += len(res["discards"])
        merges.append(res)
    return {"ok": True, "error": "", "merges": merges, "audited": audited,
            "with_discards": with_discards, "files": files, "errors": errors}


def _print_human(report):
    print(f"auto-resolved merges audited ................. {report['audited']}")
    clean = report["audited"] - report["with_discards"]
    print(f"clean (every branch edit survived) ........... {clean}")
    print(f"discarded at least one branch edit ........... {report['with_discards']}")
    print(f"files with discarded edits ................... {report['files']}")
    if report.get("errors"):
        print(f"merges the audit could NOT evaluate .......... {len(report['errors'])}")
        for e in report["errors"][:10]:
            print(f"    {e['merge_sha'][:12]}  {e['error']}")
    for m in report["merges"]:
        if not m.get("discards"):
            continue
        print(f"\n  merge {m['merge_sha'][:12]}  {str(m.get('subject', ''))[:70]}")
        for d in m["discards"]:
            print(f"    DISCARDED {d['path']}")
            for s in d.get("dropped_subjects", [])[:5]:
                print(f"        dropped: {s}")
            print(f"        recover: {d['recover']}")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Audit auto-resolved merges for silently discarded branch work.")
    ap.add_argument("--repo", default=os.getcwd(), help="repository root (default: cwd)")
    ap.add_argument("--range", dest="rev_range", default=None,
                    help="git rev-range, e.g. origin/master~200..origin/master")
    ap.add_argument("--since", default=None, help="audit merges since this date")
    ap.add_argument("--until", default=None, help="audit merges until this date")
    ap.add_argument("--all-merges", action="store_true",
                    help="audit hand merges too, not only (auto-resolved) subjects")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    args = ap.parse_args(argv)

    repo = os.path.abspath(args.repo)
    # In a linked worktree .git is a FILE pointing at the real gitdir, not a directory —
    # and worktrees are how the fleet does all of its work, so an isdir() check here
    # rejected exactly the repositories this tool most needs to audit. Ask git instead.
    probe = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=repo,
                           capture_output=True, text=True, timeout=30)
    if probe.returncode != 0:
        print(f"audit_automerge: not a git repository: {repo}", file=sys.stderr)
        return 2

    auto_only = not args.all_merges
    try:
        shas = _explicit_merges(repo, args.since, args.until)
        if shas is not None:
            report = _audit_shas(repo, shas, auto_only)
            report["range"] = f"--since={args.since} --until={args.until}"
        else:
            rev_range = args.rev_range or "HEAD"
            report = guard.audit_range(repo, rev_range, auto_only=auto_only)
    except Exception as exc:
        print(f"audit_automerge: audit failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if not report.get("ok"):
        print(f"audit_automerge: FAILED — {report.get('error')}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_human(report)

    # An audit that finds losses must not exit 0 — CI has to be able to fail on it.
    return 1 if report["with_discards"] else 0


if __name__ == "__main__":
    sys.exit(main())
