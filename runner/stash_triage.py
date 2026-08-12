#!/usr/bin/env python3
"""stash_triage.py — reproducible, read-only classification of git stashes.

## Why this exists (audit addendum §D)

The 2026-07-30 triage of 315 stashes on Mac 1 produced:

    119 empty  ·  37 already-landed  ·  12 cleanly-recoverable  ·  120 conflicted (76 touch runner/)

Those numbers were computed by hand, once, on one machine. `recover_stashes.sh` then hardcoded
the twelve recoverable ones as POSITIONAL refs:

    RECOVERABLE=(stash@{2} stash@{37} stash@{39} ... stash@{259})

That is a latent correctness bug, not just a style issue. `stash@{N}` is an index into the
reflog, not an identity: dropping or creating ANY stash renumbers every entry after it. Re-run
the script after the stash list has shifted and it recovers a different set of stashes than the
triage vetted — silently, because each one still applies cleanly. On a machine whose stash list
differs entirely (this repo currently has 0 stashes) it either no-ops or applies arbitrary work.

So this module makes the triage reproducible and addresses stashes by COMMIT SHA, which is
stable. It is strictly read-only: it never pops, never drops, never applies. `recover_stashes.sh`
remains the thing that writes; this is the thing that decides what it should write.

## The four buckets, defined precisely

    empty                the stash's diff against its own parent is empty — nothing to recover
    already_landed       every hunk is already present in HEAD (`git apply --reverse --check`
                         succeeds), i.e. the content shipped by another route
    recoverable          applies cleanly to HEAD (`git apply --check` succeeds)
    conflicted           real content that no longer applies — needs judgment, one at a time

Order matters: already-landed is tested before recoverable, because a stash whose content is
already in HEAD often ALSO fails a forward apply, and calling that "conflicted" would send
finished work back to a human for triage.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

EMPTY = "empty"
ALREADY_LANDED = "already_landed"
RECOVERABLE = "recoverable"
CONFLICTED = "conflicted"
ERROR = "error"

BUCKETS = (EMPTY, ALREADY_LANDED, RECOVERABLE, CONFLICTED, ERROR)

_TIMEOUT_S = int(os.environ.get("ORCH_STASH_TRIAGE_TIMEOUT_S", "30") or 30)


def _git(repo, *args, stdin=None, timeout=None):
    return subprocess.run(["git", *args], cwd=repo, input=stdin,
                          capture_output=True, text=True,
                          timeout=timeout or _TIMEOUT_S)


def list_stashes(repo):
    """[{ref, sha, subject}] newest first. Empty list when there are no stashes.

    `ref` is kept only for human-readable output. Every decision downstream uses `sha`,
    because the ref is positional and shifts under any drop.
    """
    r = _git(repo, "stash", "list", "--format=%gd%x00%H%x00%gs")
    if r.returncode != 0:
        return []
    out = []
    for line in r.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\x00")
        if len(parts) < 3:
            continue
        out.append({"ref": parts[0], "sha": parts[1], "subject": parts[2]})
    return out


def stash_diff(repo, sha):
    """The stash's patch against its first parent. Returns (patch, err)."""
    r = _git(repo, "stash", "show", "-p", "--include-untracked", sha)
    if r.returncode != 0:
        # Older git, or a stash with no untracked part — retry without the flag before
        # declaring an error, so a flag-support difference is not misreported as corruption.
        r = _git(repo, "stash", "show", "-p", sha)
        if r.returncode != 0:
            return "", (r.stderr or "").strip()[-200:]
    return r.stdout, None


def stash_files(repo, sha):
    r = _git(repo, "stash", "show", "--name-only", sha)
    if r.returncode != 0:
        return []
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def _applies(repo, patch, reverse=False):
    args = ["apply", "--check"]
    if reverse:
        args.append("--reverse")
    return _git(repo, *args, "-", stdin=patch).returncode == 0


def classify_stash(repo, entry):
    """Classify one stash. Pure with respect to the repo — nothing is written."""
    sha = entry["sha"]
    patch, err = stash_diff(repo, sha)
    if err:
        return {**entry, "bucket": ERROR, "detail": err, "files": []}
    if not patch.strip():
        return {**entry, "bucket": EMPTY, "detail": "no diff against its parent", "files": []}

    files = stash_files(repo, sha)
    touches_runner = any(f.startswith("runner/") for f in files)

    # Already-landed FIRST: content already in HEAD frequently fails a forward apply too, and
    # classifying it as conflicted would route finished work back to a human.
    if _applies(repo, patch, reverse=True):
        bucket, detail = ALREADY_LANDED, "content already present in HEAD"
    elif _applies(repo, patch):
        bucket, detail = RECOVERABLE, "applies cleanly to HEAD"
    else:
        bucket, detail = CONFLICTED, "does not apply to HEAD; needs judgment"

    return {**entry, "bucket": bucket, "detail": detail,
            "files": files, "touches_runner": touches_runner}


def triage(repo=".", limit=None):
    """Classify every stash. Read-only: never pops, drops, or applies.

    Returns counts plus the per-stash detail, with the conflicted set enumerated — that set is
    the actual remaining work, and it has to be addressable one at a time.
    """
    entries = list_stashes(repo)
    if limit:
        entries = entries[:int(limit)]
    results = [classify_stash(repo, e) for e in entries]

    counts = {b: 0 for b in BUCKETS}
    for r in results:
        counts[r["bucket"]] += 1

    conflicted = [r for r in results if r["bucket"] == CONFLICTED]
    return {
        "repo": os.path.abspath(repo),
        "total": len(results),
        "counts": counts,
        "runner_conflicted": sum(1 for r in conflicted if r.get("touches_runner")),
        # SHAs, never stash@{N} — the whole point. Feed these to a recovery step.
        "recoverable_shas": [r["sha"] for r in results if r["bucket"] == RECOVERABLE],
        "conflicted": [{"sha": r["sha"], "ref": r["ref"], "subject": r["subject"],
                        "files": r["files"], "touches_runner": r.get("touches_runner", False)}
                       for r in conflicted],
        "stashes": results,
    }


# ── recorded baseline (audit addendum §D) ───────────────────────────────────
#
# The classifier above is the rule. This is what the rule returned on a known
# input, recorded so nobody spends another hour of read-only git archaeology
# rediscovering a number that was already written down — which is exactly what
# the two-session reconciliation found happening. Dated, so it can be
# invalidated rather than trusted forever.
#
# ARITHMETIC NOTE: the four buckets sum to 288, not the stated 315 — 27
# stashes are in the pile and in no bucket. "Start from this, don't recompute"
# is still right for the 288 that WERE classified; it is the 27 that need a
# pass. The gap is recorded rather than quietly rescaling a bucket to make the
# numbers close: a triage that silently balances is a triage nobody can audit.
# `unaccounted()` is derived, never hand-entered, so it cannot go stale.
BASELINE = {
    "host": "mac1",
    "measured_at": "2026-07-30",
    "total": 315,
    "counts": {EMPTY: 119, ALREADY_LANDED: 37, RECOVERABLE: 12, CONFLICTED: 120},
    "conflicted_touching_runner": 76,
    "recovery_script": "recover_stashes.sh",
    # Positional refs as originally vetted. Retained ONLY as provenance for
    # what the 2026-07-30 pass looked at — `stash@{N}` is a reflog index, not
    # an identity, so never resolve these on a live repo. triage() addresses
    # stashes by SHA for exactly this reason.
    "recoverable_refs_historical": [
        "stash@{2}", "stash@{37}", "stash@{39}", "stash@{64}", "stash@{65}", "stash@{69}",
        "stash@{70}", "stash@{97}", "stash@{161}", "stash@{220}", "stash@{221}", "stash@{259}",
    ],
}

#: Not recoverable. Stated once so it stops being searched for.
PERMANENT_LOSS = {
    "batches": 282,
    "window": "2026-07-08..2026-07-16",
    "cause": "the old destructive `git stash push -u` in sentinel.checkout_guard",
    "status": "not in any stash, not in the reflog, not recoverable",
    "root_cause_fixed": True,
}


def unaccounted(baseline=None):
    """Baseline stashes that landed in no bucket. Derived, so it cannot go stale.

    `is None`, not falsiness: an explicitly-empty baseline means "nothing was
    recorded", and substituting the module default there would report a
    27-stash gap for a pile that was never measured.
    """
    baseline = BASELINE if baseline is None else baseline
    try:
        return int(baseline.get("total") or 0) - sum(baseline.get("counts", {}).values())
    except Exception:
        return 0


def summary_line(baseline=None):
    """The recorded result as one line. Never raises."""
    baseline = baseline or BASELINE
    try:
        counts = baseline.get("counts", {})
        return (f"{counts.get(EMPTY, 0)} empty · {counts.get(ALREADY_LANDED, 0)} already-landed · "
                f"{counts.get(RECOVERABLE, 0)} recoverable · {counts.get(CONFLICTED, 0)} conflicted")
    except Exception:
        return ""


def real_work(baseline=None):
    """The count needing a human or agent: the conflicted set. Never raises."""
    baseline = baseline or BASELINE
    try:
        return int(baseline.get("counts", {}).get(CONFLICTED, 0))
    except Exception:
        return 0


def compare_to_baseline(observed_total, baseline=None):
    """Has the pile moved since the baseline was measured? Never raises.

    The recommendation is the point: an unchanged pile means the recorded
    numbers still hold and a full re-triage reproduces a known result.
    """
    baseline = baseline or BASELINE
    result = {"changed": True, "baseline_total": baseline.get("total"),
              "observed_total": None, "delta": None, "recommendation": ""}
    try:
        observed = int(observed_total)
        result["observed_total"] = observed
        result["delta"] = observed - int(baseline.get("total") or 0)
        result["changed"] = result["delta"] != 0
        if not result["changed"]:
            result["recommendation"] = (
                f"pile unchanged since {baseline.get('measured_at')} — use the recorded triage "
                f"({summary_line(baseline)}); do NOT recompute")
        elif result["delta"] > 0:
            result["recommendation"] = (
                f"{result['delta']} new stash(es) since {baseline.get('measured_at')} — triage "
                f"ONLY the new ones; the rest of the baseline still holds")
        else:
            result["recommendation"] = (
                f"{abs(result['delta'])} stash(es) fewer than the baseline — something dropped "
                f"them; explain that before triaging")
        return result
    except Exception:
        result["recommendation"] = "observed total unreadable — recompute nothing on a guess"
        return result


def format_baseline(baseline=None):
    """Operator summary of the recorded triage. Never raises."""
    baseline = baseline or BASELINE
    try:
        gap = unaccounted(baseline)
        lines = [
            f"recorded triage — {baseline.get('measured_at')} on {baseline.get('host')}",
            f"  total ............... {baseline.get('total')}",
            f"  {summary_line(baseline)}",
            f"  needs judgment ...... {real_work(baseline)}",
        ]
        if gap:
            lines.append(f"  UNACCOUNTED ......... {gap}  (in the pile, in no bucket)")
        lines.append(f"  permanently lost .... {PERMANENT_LOSS['batches']} batches "
                     f"({PERMANENT_LOSS['window']}) — not recoverable")
        return "\n".join(lines)
    except Exception:
        return ""


def format_report(report):
    c = report["counts"]
    lines = [
        f"stash triage — {report['repo']}",
        f"  total ............... {report['total']}",
        f"  empty ............... {c[EMPTY]}",
        f"  already landed ...... {c[ALREADY_LANDED]}",
        f"  recoverable ......... {c[RECOVERABLE]}",
        f"  conflicted .......... {c[CONFLICTED]}  ({report['runner_conflicted']} touch runner/)",
    ]
    if c[ERROR]:
        lines.append(f"  unreadable .......... {c[ERROR]}")
    if report["recoverable_shas"]:
        lines.append("")
        lines.append("  recoverable (by SHA — stable, unlike stash@{N}):")
        lines.extend(f"    {s}" for s in report["recoverable_shas"])
    if report["conflicted"]:
        lines.append("")
        lines.append("  conflicted — the real work, triage one at a time:")
        for item in report["conflicted"][:40]:
            flag = " [runner]" if item["touches_runner"] else ""
            lines.append(f"    {item['sha'][:12]}{flag}  {item['subject'][:70]}")
        if len(report["conflicted"]) > 40:
            lines.append(f"    ... and {len(report['conflicted']) - 40} more")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Read-only triage of git stashes into empty / already-landed / "
                    "recoverable / conflicted. Never pops, drops, or applies.")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--baseline", action="store_true",
                    help="Print the recorded 2026-07-30 triage without scanning. "
                         "Start here: the result already exists.")
    ap.add_argument("--compare", action="store_true",
                    help="Scan, then report whether the pile moved since the baseline.")
    args = ap.parse_args(argv)

    if args.baseline:
        payload = {"baseline": BASELINE, "unaccounted": unaccounted(),
                   "permanent_loss": PERMANENT_LOSS}
        print(json.dumps(payload, indent=2, sort_keys=True) if args.json
              else format_baseline())
        return 0

    report = triage(args.repo, limit=args.limit)
    if args.compare:
        report["baseline_comparison"] = compare_to_baseline(report.get("total"))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_report(report))
        if args.compare:
            print("")
            print(f"  vs baseline: {report['baseline_comparison']['recommendation']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
