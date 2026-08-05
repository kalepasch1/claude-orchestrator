#!/usr/bin/env python3
"""stash_triage.py — the §D triage, encoded so nobody recomputes it (audit addendum, 2026-07-30).

The addendum is explicit: **the triage result already exists — start from it, do not recompute.**
A read-only pass over Mac 1's 315 stashes on 2026-07-30 produced

    119 empty · 37 already-landed · 12 cleanly-recoverable · 120 conflicted (76 touch runner/)

and a vetted recovery script for the 12 sits at repo root (`recover_stashes.sh`). Every session
that rediscovers this spends an hour of read-only git archaeology to arrive at a number that was
already written down — which is exactly what the two-session reconciliation found happening.

So the result is recorded as a BASELINE here, and the classifier that produced it is written
down too, because a baseline nobody can reproduce is folklore. `classify()` is the rule; the
baseline is what the rule returned on a known input; `compare_to_baseline()` tells you whether
the pile has moved since. Recompute only when it has.

**Permanently lost, stated once so it stops being searched for:** 282 batches of queued work
destroyed 2026-07-08→07-16 by the old destructive `stash push -u` in `checkout_guard`. They are
not in any stash, not in the reflog, and not recoverable. Root-cause-fixed; the loss is not.

Read-only. This module never pops, applies, or drops a stash. Fail-soft per CLAUDE.md.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REPO_DEFAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── the four buckets ────────────────────────────────────────────────────────────────────────

EMPTY = "empty"                   # no diff at all — nothing to recover
ALREADY_LANDED = "already-landed"  # content is in HEAD; the stash is a historical duplicate
RECOVERABLE = "recoverable"        # real content that applies cleanly to HEAD
CONFLICTED = "conflicted"          # real content that no longer applies — needs judgement

BUCKETS = (EMPTY, ALREADY_LANDED, RECOVERABLE, CONFLICTED)

#: The §D result. Recorded so it is not recomputed; dated so it can be invalidated.
#:
#: ARITHMETIC NOTE (found while encoding this, 2026-08-05). The four buckets sum to **288**,
#: not the stated 315 — 27 stashes are in the pile and in no bucket. The addendum says "start
#: from this, don't recompute", and that instruction is still right for the 288 that WERE
#: classified; it is the 27 that need a pass. Recording the gap rather than quietly rescaling
#: a bucket to make the numbers close is the whole point: a triage that silently balances is a
#: triage nobody can audit, and the 27 would have been lost in the rounding. `unaccounted` is
#: derived, never hand-entered, so it cannot go stale against the counts above.
BASELINE = {
    "host": "mac1",
    "measured_at": "2026-07-30",
    "total": 315,
    "counts": {EMPTY: 119, ALREADY_LANDED: 37, RECOVERABLE: 12, CONFLICTED: 120},
    "conflicted_touching_runner": 76,
    "recovery_script": "recover_stashes.sh",
    "recoverable_refs": [
        "stash@{2}", "stash@{37}", "stash@{39}", "stash@{64}", "stash@{65}", "stash@{69}",
        "stash@{70}", "stash@{97}", "stash@{161}", "stash@{220}", "stash@{221}", "stash@{259}",
    ],
}

#: Not recoverable. Stated so it stops being looked for.
PERMANENT_LOSS = {
    "batches": 282,
    "window": "2026-07-08..2026-07-16",
    "cause": "the old destructive `git stash push -u` in sentinel.checkout_guard",
    "status": "not in any stash, not in the reflog, not recoverable",
    "root_cause_fixed": True,
}


def _git(repo, *args, timeout=60, want_bytes=False):
    """Read-only git. Returns stdout ("" / b"" on failure). Never raises."""
    try:
        result = subprocess.run(
            ("git",) + args, cwd=repo, capture_output=True, timeout=timeout,
            text=not want_bytes, errors=None if want_bytes else "replace")
        if result.returncode != 0:
            return b"" if want_bytes else ""
        return result.stdout or (b"" if want_bytes else "")
    except Exception:
        return b"" if want_bytes else ""


# ── the classifier that produced the baseline ───────────────────────────────────────────────

def classify(ref, repo=None, runner=_git):
    """Put one stash into one bucket. Read-only, never raises.

    The order matters and is the same order the 2026-07-30 pass used:
      1. no diff at all            -> empty
      2. diff applies in reverse   -> already-landed (the content is in HEAD)
      3. diff applies forward      -> recoverable
      4. otherwise                 -> conflicted
    Checking already-landed BEFORE recoverable matters: a stash whose content is already in HEAD
    often also applies cleanly (as a no-op), and recovering it manufactures an empty commit.
    """
    result = {"ref": str(ref), "bucket": CONFLICTED, "files": [], "touches_runner": False}
    try:
        repo = repo or REPO_DEFAULT
        patch = runner(repo, "stash", "show", "-p", str(ref))
        files = [f for f in (runner(repo, "stash", "show", "--name-only",
                                    str(ref)) or "").splitlines() if f.strip()]
        result["files"] = files
        result["touches_runner"] = any(f.startswith("runner/") for f in files)

        if not (patch or "").strip():
            result["bucket"] = EMPTY
            return result

        if _applies(repo, patch, reverse=True, runner=runner):
            result["bucket"] = ALREADY_LANDED
            return result

        if _applies(repo, patch, reverse=False, runner=runner):
            result["bucket"] = RECOVERABLE
            return result

        result["bucket"] = CONFLICTED
        return result
    except Exception:
        return result


def _applies(repo, patch, reverse=False, runner=_git):
    """Would this patch apply (in reverse when asked)? Never mutates the tree."""
    try:
        args = ["apply", "--check"]
        if reverse:
            args.append("--reverse")
        proc = subprocess.run(["git"] + args, cwd=repo, input=patch, text=True,
                              capture_output=True, timeout=60)
        return proc.returncode == 0
    except Exception:
        return False


def triage(repo=None, refs=None, runner=_git):
    """Classify every stash. Returns {"total", "counts", "by_bucket", "conflicted_touching_runner"}.

    EXPENSIVE — it shells out twice per stash. `compare_to_baseline()` exists so callers can
    check whether it is worth running at all. Never raises.
    """
    report = {"total": 0, "counts": {b: 0 for b in BUCKETS}, "by_bucket": {b: [] for b in BUCKETS},
              "conflicted_touching_runner": 0}
    try:
        repo = repo or REPO_DEFAULT
        if refs is None:
            listing = runner(repo, "stash", "list") or ""
            refs = [line.split(":", 1)[0].strip()
                    for line in listing.splitlines() if line.strip()]
        for ref in refs:
            entry = classify(ref, repo=repo, runner=runner)
            report["total"] += 1
            report["counts"][entry["bucket"]] += 1
            report["by_bucket"][entry["bucket"]].append(entry["ref"])
            if entry["bucket"] == CONFLICTED and entry["touches_runner"]:
                report["conflicted_touching_runner"] += 1
    except Exception:
        pass
    return report


# ── baseline comparison ─────────────────────────────────────────────────────────────────────

def compare_to_baseline(observed_total, baseline=None):
    """Has the pile moved since §D was measured? Never raises.

    Returns {"changed", "baseline_total", "observed_total", "delta", "recommendation"}.
    The recommendation is the point: an unchanged pile means the §D numbers still hold and a
    full re-triage is an hour spent to reproduce a result already written down.
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
                f"them; explain that before triaging (see stash_census fleet reconciliation)")
        return result
    except Exception:
        result["recommendation"] = "observed total unreadable — recompute nothing on a guess"
        return result


def unaccounted(baseline=None):
    """Stashes in the pile that are in no bucket. Derived, so it cannot go stale.

    `is None`, not falsiness: an explicitly-empty baseline means "nothing was recorded", and
    silently substituting the module default there would report a 27-stash gap for a pile that
    was never measured.
    """
    baseline = BASELINE if baseline is None else baseline
    try:
        return int(baseline.get("total") or 0) - sum(baseline.get("counts", {}).values())
    except Exception:
        return 0


def summary_line(baseline=None):
    """The §D result as one line. Never raises."""
    baseline = baseline or BASELINE
    try:
        counts = baseline.get("counts", {})
        return (f"{counts.get(EMPTY, 0)} empty · {counts.get(ALREADY_LANDED, 0)} already-landed · "
                f"{counts.get(RECOVERABLE, 0)} recoverable · {counts.get(CONFLICTED, 0)} conflicted")
    except Exception:
        return ""


def real_work(baseline=None):
    """The count that actually needs a human or agent: the conflicted set. Never raises."""
    baseline = baseline or BASELINE
    try:
        return int(baseline.get("counts", {}).get(CONFLICTED, 0))
    except Exception:
        return 0


def render(comparison=None, baseline=None):
    """Operator summary. Never raises."""
    baseline = baseline or BASELINE
    try:
        lines = [
            f"STASH TRIAGE — recorded {baseline.get('measured_at')} on {baseline.get('host')}",
            "=" * 58,
            f"  total {baseline.get('total')}: {summary_line(baseline)}",
            f"  {baseline.get('conflicted_touching_runner')} of the conflicted touch runner/ — "
            f"that is the real work",
            f"  the {baseline['counts'][RECOVERABLE]} clean ones have a vetted script: "
            f"{baseline.get('recovery_script')}",
        ]
        gap = unaccounted(baseline)
        if gap:
            lines += [
                f"  UNACCOUNTED: {gap} stash(es) are in the pile and in NO bucket — the recorded "
                f"buckets sum to {baseline['total'] - gap}, not {baseline['total']}.",
                f"    Triage those {gap}; the other {baseline['total'] - gap} are already done.",
            ]
        lines += [
            "",
            f"  PERMANENTLY LOST: {PERMANENT_LOSS['batches']} batches, "
            f"{PERMANENT_LOSS['window']} — {PERMANENT_LOSS['status']}.",
            f"    cause: {PERMANENT_LOSS['cause']} (root-cause-fixed). Stop looking for them.",
        ]
        if comparison:
            lines.append("")
            lines.append(f"  {comparison.get('recommendation', '')}")
        return "\n".join(lines)
    except Exception:
        return "stash triage baseline unavailable"


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    repo = next((a for a in argv if not a.startswith("-")), REPO_DEFAULT)
    listing = _git(repo, "stash", "list") or ""
    observed = len([l for l in listing.splitlines() if l.strip()])
    comparison = compare_to_baseline(observed)
    print(render(comparison))
    if "--recompute" in argv and comparison["changed"]:
        report = triage(repo=repo)
        print("")
        print(f"  recomputed: {report['total']} total, {report['counts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
