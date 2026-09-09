#!/usr/bin/env python3
"""Run the whole reconciler family and merge the result into one ledger.

Local ChatGPT/Codex evidence arrives in several shapes at once — rescue refs,
local-only branch tips, unmerged agent branches, dirty worktrees, broken
worktrees, bridge patch artifacts. Each has its own reconciler; a recovery task
usually spans several of them and needs a SINGLE ledger under ONE audit
fingerprint, with zero UNKNOWN items across the whole set.

This driver runs each reconciler as a subprocess (so each stays independently
testable and is used exactly as written), then merges their ledgers, dedupes by
source, and reports combined counts. Every sub-reconciler is read-only, so this
driver is too: nothing is deleted, reset, cleaned, popped or moved.

A reconciler that is absent or fails is recorded as a `driver_error` item rather
than being silently skipped — a missing input must never masquerade as clean
evidence.

Usage:
    python3 tools/reconcile_all_evidence.py --base origin/master \
        --fingerprint <audit-sha> --repo . --out .orch/recovery-ledger-<short>.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

# (script, evidence_kind, extra argv builder)
STAGES = (
    ("reconcile_rescue_refs.py", "orchestrator_rescue_refs"),
    ("reconcile_local_branches.py", "local_only_branch_tips"),
    ("reconcile_worktree_evidence.py", "worktrees_and_bridge_artifacts"),
)


def supports_flag(script: str, tools: str, flag: str) -> bool:
    """Does this stage script accept `flag`?

    The stages are separate programs that gain options at different times, and
    the driver must keep working against a stage that has not caught up yet:
    passing an unknown flag makes argparse exit 2, which the driver would record
    as a `driver_error` — a whole evidence class going unclassified because of a
    command line, which is precisely the failure this driver is written to make
    impossible. So the flag is offered, never assumed.
    """
    try:
        with open(os.path.join(tools, script), "r", errors="replace") as fh:
            return flag in fh.read()
    except OSError:
        return False


def stage_argv(script: str, tools: str, base: str, fingerprint: str, repo: str,
               out: str, args, budget: int = 0) -> "list[str]":
    argv = [sys.executable, os.path.join(tools, script),
            "--base", base, "--fingerprint", fingerprint, "--out", out]
    if budget and supports_flag(script, tools, "--max-seconds"):
        argv += ["--max-seconds", str(budget)]
    if args.progress_every is not None and supports_flag(
            script, tools, "--progress-every"):
        argv += ["--progress-every", str(args.progress_every)]
    if script == "reconcile_worktree_evidence.py":
        argv += ["--repo", repo]
        if args.dropbox:
            argv += ["--dropbox", args.dropbox]
        if args.exclude_path:
            argv += ["--exclude-path", args.exclude_path]
    if script == "reconcile_local_branches.py" and args.exclude_branch:
        argv += ["--exclude-self", args.exclude_branch]
    return argv


def run_stage(script: str, kind: str, tools: str, base: str, fingerprint: str,
              repo: str, args, budget: int = 0) -> "tuple[list, str]":
    path = os.path.join(tools, script)
    if not os.path.isfile(path):
        return [{
            "ref": "tools/" + script,
            "sha": "",
            "classification": "CONFLICTED_NEEDS_FOCUSED_TASK",
            "disposition": "reconciler missing; this evidence class was NOT "
                           "classified and must not be reported as clean",
            "evidence": "driver_error: script not found",
            "kind": kind,
            "files": [],
        }], "missing"

    fd, tmp = tempfile.mkstemp(suffix=".json", prefix="reconcile-")
    os.close(fd)
    try:
        proc = subprocess.run(
            stage_argv(script, tools, base, fingerprint, repo, tmp, args, budget),
            cwd=repo, capture_output=True, text=True, errors="replace",
        )
        if not os.path.getsize(tmp):
            return [{
                "ref": "tools/" + script,
                "sha": "",
                "classification": "CONFLICTED_NEEDS_FOCUSED_TASK",
                "disposition": "reconciler produced no ledger; this evidence "
                               "class was NOT classified",
                "evidence": "driver_error: rc=%d %s" % (
                    proc.returncode, (proc.stderr or "").strip()[:200]),
                "kind": kind,
                "files": [],
            }], "empty"
        with open(tmp) as fh:
            ledger = json.load(fh)
        items = ledger.get("items", [])
        for it in items:
            it.setdefault("kind", kind)
        # "truncated" is louder than "ok": a stage that ran out of budget
        # classified only part of its evidence class, and the merged ledger must
        # say so rather than average it away into an overall pass.
        return items, ("truncated" if ledger.get("truncated") else "ok")
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/master")
    ap.add_argument("--fingerprint", required=True)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--tools", default="", help="defaults to <repo-of-this-script>")
    ap.add_argument("--out", default=".orch/recovery-ledger-all.json")
    ap.add_argument("--dropbox", default="")
    ap.add_argument("--exclude-path", default="")
    ap.add_argument("--exclude-branch", default="")
    ap.add_argument("--only", default="", help="comma-separated stage scripts")
    ap.add_argument("--max-seconds", type=int, default=0,
                    help="total scan budget across all stages; 0 = unlimited. "
                         "Split evenly, because a stage that overruns must not "
                         "silently consume the budget of the stages after it — "
                         "that would leave a whole evidence class unscanned "
                         "while the earlier stage looked thorough.")
    ap.add_argument("--progress-every", type=int, default=None,
                    help="forwarded to any stage that supports it; "
                         "omit to leave each stage on its own default")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    tools = os.path.abspath(args.tools) if args.tools else os.path.dirname(
        os.path.abspath(__file__))
    only = {s.strip() for s in args.only.split(",") if s.strip()}

    merged: list = []
    seen: set = set()
    stage_status: dict = {}

    planned = [s_ for s_, _ in STAGES if not only or s_ in only]
    per_stage_budget = (args.max_seconds // len(planned)) if (
        args.max_seconds and planned) else 0

    for script, kind in STAGES:
        if only and script not in only:
            continue
        items, status = run_stage(script, kind, tools, args.base,
                                  args.fingerprint, repo, args,
                                  per_stage_budget)
        stage_status[script] = status
        for it in items:
            key = (it.get("kind", kind), it.get("ref", ""))
            if key in seen:
                continue
            seen.add(key)
            merged.append(it)

    counts: dict = {}
    by_kind: dict = {}
    for it in merged:
        cls = it.get("classification", "UNKNOWN")
        counts[cls] = counts.get(cls, 0) + 1
        k = it.get("kind", "unspecified")
        by_kind.setdefault(k, {})
        by_kind[k][cls] = by_kind[k].get(cls, 0) + 1

    ledger = {
        "audit_fingerprint": args.fingerprint,
        "base": args.base,
        "evidence_kind": "combined_local_chatgpt_codex_evidence",
        "stages": stage_status,
        "total": len(merged),
        "counts": counts,
        "counts_by_kind": by_kind,
        "unknown": counts.get("UNKNOWN", 0),
        # One stage running out of budget makes the WHOLE merged ledger
        # partial: the classes are disjoint, so an unscanned stage is an entire
        # evidence class nobody looked at. Marking the merge truncated is what
        # stops restamp_recovery_ledger reusing it as a complete audit.
        "truncated": any(v == "truncated" for v in stage_status.values()),
        "items": merged,
    }

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(ledger, fh, indent=2, sort_keys=True)

    print(json.dumps({"total": len(merged), "counts": counts,
                      "stages": stage_status}, indent=2))
    return 1 if counts.get("UNKNOWN") else 0


if __name__ == "__main__":
    raise SystemExit(main())
