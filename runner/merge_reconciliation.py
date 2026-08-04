#!/usr/bin/env python3
"""merge_reconciliation.py — merges claimed must equal commits landed.

WHY (2026-08-04, cowork forensic audit)
---------------------------------------
The dashboard read "100% merge rate" while a project's repo tip was 24 hours old. Nothing
in the system compared those two numbers, so three independent phantom-merge mechanisms ran
for six weeks undetected and 10,584 of 13,816 MERGED tasks (76.6%) turned out to have no
code in the target repo at all:

  * a self-certifying recovery loop (a sweeper grepping git log matched its own stub),
  * quarantine_remediation marking originals MERGED whenever it requeued a copy,
  * two bulk UPDATEs that flipped 9,068 rows to MERGED in two hours.

Every one of them would have been caught on day one by a single invariant:

    tasks marked MERGED in a window  ~=  commits landed on the integration ref in that window

This job checks that invariant per project and alerts LOUDLY when it fails. It is the
detector that should have existed before any of the fixes.

Three signals, because each mechanism shows up differently:
  1. NO_EVIDENCE   — MERGED rows with no artifact_commit. Structural: a merge that cannot
                     name its own commit is not a merge.
  2. DIVERGENCE    — merges claimed far exceeding commits landed in the same window.
  3. STALE_REPO    — merges claimed against a repo whose tip has not moved. This is the
                     exact "100% merge rate, 24h-old tip" failure.

Exit code is 1 when any project alerts, so a scheduler can treat it as a failing check.

Env:
  RECON_WINDOW_HOURS      window to reconcile (default 24)
  RECON_MIN_MERGES        ignore projects with fewer claimed merges than this (default 3)
  RECON_MAX_RATIO         alert when claimed/landed exceeds this (default 2.0)
  RECON_STALE_HOURS       alert when merges are claimed against a tip older than this (default 12)
  RECON_NOTIFY            write a notifications row (default true)
"""
import os
import subprocess
import sys
import time
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402

WINDOW_HOURS = float(os.environ.get("RECON_WINDOW_HOURS", "24"))
MIN_MERGES = int(os.environ.get("RECON_MIN_MERGES", "3"))
MAX_RATIO = float(os.environ.get("RECON_MAX_RATIO", "2.0"))
STALE_HOURS = float(os.environ.get("RECON_STALE_HOURS", "12"))
NOTIFY = os.environ.get("RECON_NOTIFY", "true").lower() in ("1", "true", "yes", "on")
# Date the "never write MERGED without an evidence sha" invariant took effect.
EVIDENCE_SINCE = os.environ.get("RECON_EVIDENCE_SINCE", "2026-08-04")

SCAFFOLD = ("recovery-intent", "placeholder commit", "intent stub")


def _git(repo, *args, timeout=60):
    try:
        return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except Exception:
        return subprocess.CompletedProcess(args, 1, "", "git failed")


def _integration_refs(repo):
    """Every integration ref that exists, freshest first.

    Deliberately a UNION rather than a single ref. Projects do not agree on where code
    lands: in `smarter`, origin/orchestrator/dev was two days stale while origin/main was
    29 minutes old; in `tomorrow`, origin/master was 8 days behind origin/main. Reconciling
    against whichever name happened to be checked first manufactured false STALE_REPO
    alerts, and a detector that cries wolf is how the real signal got ignored for six weeks.
    """
    refs = []
    for name in (os.environ.get("ORCH_STAGING_BRANCH", "orchestrator/dev"),
                 os.environ.get("ORCH_CODE_MERGE_TARGET", "dev"), "main", "master"):
        for ref in (f"origin/{name}", name):
            if ref in refs:
                continue
            if _git(repo, "rev-parse", "--verify", "--quiet", ref).returncode == 0:
                refs.append(ref)
    refs.sort(key=lambda r: -(tip_epoch(repo, r) or 0))
    return refs


def tip_epoch(repo, ref):
    r = _git(repo, "log", "-1", "--format=%ct", ref)
    try:
        return int(r.stdout.strip())
    except Exception:
        return None


def commits_landed(repo, refs, since_iso):
    """Count DISTINCT commits across *refs* since *since_iso* that changed the tree.

    Scaffolding and empty commits are excluded, for the same reason they are excluded from
    integration evidence: they are bookkeeping, not delivery. Counting them here would let
    the stub loop satisfy its own reconciliation check — the detector would be fooled by
    exactly the mechanism it exists to catch.
    """
    if isinstance(refs, str):
        refs = [refs]
    real, total = set(), set()
    ok = False
    for ref in refs:
        r = _git(repo, "log", ref, f"--since={since_iso}", "--format=%H%x02%T%x02%P%x02%s")
        if r.returncode != 0:
            continue
        ok = True
        for line in (r.stdout or "").splitlines():
            parts = line.split("\x02", 3)
            if len(parts) < 4:
                continue
            sha, tree, parents, subject = parts
            total.add(sha)
            if sha in real or any(s in subject.lower() for s in SCAFFOLD):
                continue
            p = parents.split()
            if p:
                pt = _git(repo, "rev-parse", f"{p[0]}^{{tree}}").stdout.strip()
                if pt == tree:
                    continue  # empty commit / empty merge: delivered nothing
            real.add(sha)
    if not ok:
        return None, None
    return len(real), len(total)


def tip_age_hours(repo, ref):
    r = _git(repo, "log", "-1", "--format=%ct", ref)
    try:
        return (time.time() - int(r.stdout.strip())) / 3600.0
    except Exception:
        return None


def reconcile(window_hours=None):
    window_hours = window_hours or WINDOW_HOURS
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=window_hours)
    since_iso = since.isoformat()

    projects = db.select("projects", {"select": "id,name,repo_path"}) or []
    rows = db.select("tasks", {
        "select": "id,slug,project_id,artifact_commit,updated_at",
        "state": "eq.MERGED",
        "updated_at": f"gte.{since_iso}",
        "limit": "5000",
    }) or []

    by_proj = {}
    for t in rows:
        by_proj.setdefault(t.get("project_id"), []).append(t)

    report, alerts = [], []
    for p in projects:
        claimed = by_proj.get(p["id"], [])
        if len(claimed) < MIN_MERGES:
            continue
        repo = p.get("repo_path") or ""
        if not os.path.isdir(repo):
            report.append({"project": p["name"], "claimed": len(claimed),
                           "landed": None, "status": "REPO_UNAVAILABLE"})
            continue
        refs = _integration_refs(repo)
        if not refs:
            report.append({"project": p["name"], "claimed": len(claimed),
                           "landed": None, "status": "NO_INTEGRATION_REF"})
            continue
        ref = refs[0]  # freshest; used for reporting and the staleness test

        landed, total = commits_landed(repo, refs, since_iso)
        # NO_EVIDENCE measures the GO-FORWARD invariant ("never write MERGED without the sha
        # that proves it"), which took effect on EVIDENCE_SINCE. Rows merged before that date
        # predate the invariant and never recorded a sha; counting them would make this
        # detector fire forever on history it cannot change, and a detector that always fires
        # is one nobody reads — which is how the original 100%-merge-rate lie survived six
        # weeks. Backfilling historical shas is tracked separately.
        scored = [t for t in claimed if (t.get("updated_at") or "") >= EVIDENCE_SINCE]
        no_evidence = sum(1 for t in scored if not t.get("artifact_commit"))
        age = tip_age_hours(repo, ref)
        ratio = (len(claimed) / landed) if landed else float("inf")

        problems = []
        if no_evidence:
            problems.append(f"NO_EVIDENCE {no_evidence}/{len(claimed)} merged rows carry no commit sha")
        if landed == 0:
            problems.append(f"DIVERGENCE {len(claimed)} merges claimed, 0 commits landed on {ref}")
        elif ratio > MAX_RATIO:
            problems.append(f"DIVERGENCE {len(claimed)} merges claimed vs {landed} commits "
                            f"landed on {ref} (ratio {ratio:.1f}x > {MAX_RATIO})")
        if age is not None and age > STALE_HOURS:
            problems.append(f"STALE_REPO {len(claimed)} merges claimed against {ref} whose "
                            f"tip is {age:.1f}h old")

        entry = {"project": p["name"], "claimed": len(claimed), "landed": landed,
                 "commits_total": total, "no_evidence": no_evidence,
                 "tip_age_hours": round(age, 1) if age is not None else None,
                 "ref": ref, "status": "ALERT" if problems else "OK",
                 "problems": problems}
        report.append(entry)
        if problems:
            alerts.append(entry)

    return report, alerts


def run():
    report, alerts = reconcile()
    print(f"=== merge reconciliation (last {WINDOW_HOURS:.0f}h) ===")
    print(f"{'project':26s} {'claimed':>8s} {'landed':>7s} {'no_sha':>7s} {'tip_age_h':>10s}  status")
    for e in sorted(report, key=lambda x: -(x.get("claimed") or 0)):
        print(f"{e['project']:26s} {str(e.get('claimed')):>8s} {str(e.get('landed')):>7s} "
              f"{str(e.get('no_evidence')):>7s} {str(e.get('tip_age_hours')):>10s}  {e['status']}")
    if not alerts:
        print("\nreconciled: merges claimed agree with commits landed.")
        return 0

    lines = []
    for e in alerts:
        for p in e["problems"]:
            lines.append(f"  [{e['project']}] {p}")
    body = ("Tasks marked MERGED do not agree with commits landed.\n\n"
            + "\n".join(lines)
            + "\n\nA task marked MERGED that cannot name the commit it shipped did not ship. "
              "This check exists because three phantom-merge mechanisms ran undetected for six "
              "weeks while the dashboard reported a 100% merge rate.")
    print("\n*** MERGE RECONCILIATION FAILED ***")
    print(body)
    if NOTIFY:
        try:
            db.insert("notifications", {
                "kind": "merge_reconciliation_failed",
                "title": f"Merge reconciliation FAILED for {len(alerts)} project(s)",
                "body": body,
            })
        except Exception as exc:
            print(f"(could not write notification: {type(exc).__name__}: {exc})")
    return 1


if __name__ == "__main__":
    sys.exit(run())
