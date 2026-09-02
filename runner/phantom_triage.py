#!/usr/bin/env python3
"""phantom_triage.py — three-way triage of PHANTOM_UNVERIFIED tasks (register R3).

WHY (2026-08-11)
----------------
The 2026-08-04 forensic audit moved 10,584 evidence-free MERGED rows to
PHANTOM_UNVERIFIED. That made the metrics truthful and left a backlog nobody has
classified. Measured today: apparently holds 1,631 PHANTOM_UNVERIFIED rows, of
which only 54 carry an `artifact_branch` and 12 an `artifact_commit`.

That last number is why the existing recovery job cannot finish this. Read the
prior art before touching this file:

  * `landed_evidence.py`  — THE sound "did this land?" predicate. Boundary-exact
    slug match, not recovery scaffolding, and actually changes the tree. This
    module CALLS it. Do not reimplement it; three earlier attempts to answer
    this question with `grep`-for-a-slug were unsound in three separate ways,
    all documented in that file's header.
  * `phantom_recovery.py` — reconciles phantom rows that already carry an
    `artifact_commit`, via `merge_truth`. It is the right tool for those 12 rows
    and the wrong tool for the other 1,619, because it starts from a column that
    is empty. This module is the step BEFORE it: it derives the evidence sha
    from git so `phantom_recovery` has something to reconcile.
  * `phantom_reclassify.py` — the job that CREATED this backlog. Its closing
    comment already specifies the exit path: "find real evidence
    (landed_evidence.find_evidence), set artifact_commit to it, and only then
    set MERGED." This module implements exactly that instruction.

THE THREE CLASSES
-----------------
  (a) LANDED     — find_evidence returned a sha. Promotable: persist the sha,
                   then let phantom_recovery reconcile it.
  (b) NO_TRACE   — no landed evidence AND no `agent/<slug>` ref anywhere in the
                   repo. Nothing was ever produced. Safely closable.
  (c) AMBIGUOUS  — a branch exists but carries no landed evidence, or the repo
                   is unavailable. Listed explicitly with the missing evidence
                   named. NEVER auto-closed.

SAFETY
------
Dry run by default. `--apply` does exactly two things, and only to rows still in
PHANTOM_UNVERIFIED at write time:

  * class (a): records `artifact_commit` from the git evidence. STATE UNCHANGED.
    Skips any row that already carries evidence, and any sha another task
    already cites — merge_truth refuses to certify two tasks with one commit, so
    recording it here would only manufacture a rejection later.
  * class (b): sets CLOSED.

Nothing is promoted by this script: promotion requires an artifact_commit AND a
merge_truth reachability check, and that belongs to phantom_recovery. "No task
promoted without landed evidence" still holds by construction.

Usage:
    python3 phantom_triage.py --project apparently
    python3 phantom_triage.py --project apparently --json /tmp/triage.json
    python3 phantom_triage.py --project apparently --limit 200
    python3 phantom_triage.py --project apparently --apply     # closes class (b) only
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import landed_evidence

LANDED = "landed"
NO_TRACE = "no_trace"
AMBIGUOUS = "ambiguous"

# `task_state` is a Postgres ENUM. Its members are QUEUED, WAITING, RUNNING,
# RETRY, DONE, BLOCKED, CONFLICT, TESTFAIL, MERGED, SHELVED, MERGING,
# DECOMPOSED, QUARANTINED, SUPERSEDED, CLOSED, DEPLOYED_AND_VERIFIED,
# PHANTOM_UNVERIFIED. A new label would need a migration, so the reason lives in
# the note, not in a bespoke state.
CLOSED_STATE = "CLOSED"


def _git(repo, *args, timeout=180):
    try:
        return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except Exception:
        return None


def all_ref_names(repo):
    """Every local and remote ref name, once. Answers 'was a branch ever made?'."""
    r = _git(repo, "for-each-ref", "--format=%(refname:short)")
    if not r or r.returncode != 0:
        return set()
    return {line.strip() for line in r.stdout.splitlines() if line.strip()}


def commit_body_index(repo, max_scan=200000):
    """One pass over every commit subject+body across all refs.

    A cheap PRE-FILTER only. `landed_evidence.find_evidence` remains the
    authority — this just avoids invoking it 1,600 times for slugs that appear
    in no commit at all, which is the overwhelming majority.
    """
    r = _git(repo, "log", "--all", "-%d" % max_scan, "--format=%s%n%b", timeout=900)
    if not r or r.returncode != 0:
        return ""
    return r.stdout


def classify(repo, slug, refs, body_blob):
    """Return (klass, evidence_sha, detail)."""
    if not repo or not os.path.isdir(repo):
        return AMBIGUOUS, None, "repo path unavailable — cannot verify either way"

    # Cheap pre-filter. If the slug appears nowhere in any commit message, the
    # sound predicate cannot possibly find evidence.
    if slug in body_blob:
        found = landed_evidence.find_evidence(repo, slug)
        if found:
            sha, ref, subject = found
            return LANDED, sha, "%s on %s: %s" % (sha[:12], ref, subject[:90])

    branch = "agent/%s" % slug
    has_branch = any(name == branch or name.endswith("/" + branch) for name in refs)
    if has_branch:
        return AMBIGUOUS, None, "branch %s exists but no commit delivers the slug" % branch

    if slug in body_blob:
        # Named in a commit, but that commit was scaffolding or changed nothing.
        return AMBIGUOUS, None, ("slug appears in a commit message but no commit changes "
                                 "the tree (scaffolding or empty)")

    return NO_TRACE, None, "no branch and no commit anywhere names this slug"


def repo_for_project(project_name):
    rows = db.select("projects", {"name": "eq.%s" % project_name, "select": "repo_path"})
    if not rows:
        return None
    return db.localize_repo_path(rows[0].get("repo_path"))


def main():
    ap = argparse.ArgumentParser(description="Three-way triage of PHANTOM_UNVERIFIED tasks.")
    ap.add_argument("--project", required=True)
    ap.add_argument("--limit", type=int, default=0, help="0 = all")
    ap.add_argument("--json", dest="json_out", default="")
    ap.add_argument("--state", default="PHANTOM_UNVERIFIED",
                    help="which state to classify (default PHANTOM_UNVERIFIED). "
                         "Any other state is DIAGNOSTIC AND EVIDENCE-RECORDING ONLY: "
                         "the class (b) close refuses to run outside "
                         "PHANTOM_UNVERIFIED, because closing a MERGED row is "
                         "reclassification and belongs to phantom_reclassify.")
    ap.add_argument("--apply", action="store_true",
                    help="close class (b) NO_TRACE rows. Never promotes anything.")
    args = ap.parse_args()

    repo = repo_for_project(args.project)
    if not repo or not os.path.isdir(repo):
        print("x repo for project %r not found locally: %r" % (args.project, repo))
        print("  Triage cannot run without the repo — every row would be AMBIGUOUS,")
        print("  which is not a triage.")
        return 1

    proj = db.select("projects", {"name": "eq.%s" % args.project, "select": "id"})
    if not proj:
        print("x no project named %r" % args.project)
        return 1
    project_id = proj[0]["id"]

    rows = db.select_all("tasks", {
        "project_id": "eq.%s" % project_id,
        "state": "eq.%s" % args.state,
        "select": "id,slug,note,artifact_commit,artifact_branch",
    }, max_rows=args.limit or None)

    print("phantom triage: %d %s row(s) in %s (repo %s)."
          % (len(rows), args.state, args.project, repo))
    print("  Indexing refs and commit messages...")
    refs = all_ref_names(repo)
    body_blob = commit_body_index(repo)
    print("  %d ref(s), %d bytes of commit message indexed." % (len(refs), len(body_blob)))

    buckets = {LANDED: [], NO_TRACE: [], AMBIGUOUS: []}
    for row in rows:
        slug = row.get("slug") or ""
        if not slug:
            buckets[AMBIGUOUS].append({"id": row.get("id"), "slug": "",
                                       "evidence": None, "detail": "row has no slug"})
            continue
        klass, sha, detail = classify(repo, slug, refs, body_blob)
        buckets[klass].append({"id": row["id"], "slug": slug, "evidence": sha, "detail": detail})

    total = len(rows)
    print()
    print("=== TRIAGE ===")
    for klass, label in ((LANDED, "(a) landed - promotable"),
                         (NO_TRACE, "(b) no trace - safely closable"),
                         (AMBIGUOUS, "(c) ambiguous - needs a human")):
        n = len(buckets[klass])
        pct = (100.0 * n / total) if total else 0.0
        print("  %-34s %6d  (%5.1f%%)" % (label, n, pct))
    print()
    print("  Not reached: rows whose repo is not cloned locally; evidence living in a repo")
    print("  other than the project's own; and whether a landed commit is actually correct -")
    print("  this proves code shipped, not that it works.")

    if args.json_out:
        with open(args.json_out, "w") as fh:
            json.dump({"project": args.project, "repo": repo, "total": total,
                       "counts": dict((k, len(v)) for k, v in buckets.items()),
                       "buckets": buckets}, fh, indent=2)
        print("\n  Full classification written to %s" % args.json_out)

    for sample_class, label in ((LANDED, "landed"), (AMBIGUOUS, "ambiguous")):
        if buckets[sample_class]:
            print("\n  sample %s:" % label)
            for item in buckets[sample_class][:5]:
                print("    %s - %s" % (item["slug"][:70], item["detail"][:100]))

    if not args.apply:
        print("\nDry run. Re-run with --apply to close the class (b) rows. Nothing was written.")
        return 0

    # ---- class (a): persist the evidence so phantom_recovery has something to
    # reconcile. This step was specified in this module's own header ("Promotable:
    # persist the sha, then let phantom_recovery reconcile it") and in
    # phantom_reclassify's closing comment ("set artifact_commit to it, and only
    # then set MERGED"), and it did not exist. --apply closed class (b) and did
    # nothing else, so every run re-derived the same shas and threw them away.
    #
    # Measured on smarter: 5 rows sat in PHANTOM_UNVERIFIED with an empty
    # artifact_commit while find_evidence named the exact commit that delivered
    # them, on every run, for as long as the backlog has existed.
    #
    # STATE IS NOT TOUCHED HERE. "Nothing is promoted by this script" still holds
    # by construction: this writes evidence, and promotion remains
    # phantom_recovery's job through merge_truth.
    recorded = 0
    for item in buckets[LANDED]:
        sha = (item.get("evidence") or "").strip()
        if not sha:
            continue
        current = db.select("tasks", {"id": "eq.%s" % item["id"],
                                      "select": "id,state,artifact_commit"})
        # The re-check asks "has this row moved since the scan?", so it compares
        # against the state that was SCANNED. Hardcoding PHANTOM_UNVERIFIED here
        # made --state MERGED skip every row and report nothing recorded, which
        # reads as "no evidence found" rather than "the guard ate it".
        if not current or current[0].get("state") != args.state:
            continue
        if (current[0].get("artifact_commit") or "").strip():
            continue                      # never clobber evidence already recorded
        # merge_truth refuses to certify two tasks with one commit, so recording a
        # sha another task already cites would only manufacture a rejection later.
        cited = db.select("tasks", {"artifact_commit": "eq.%s" % sha,
                                    "select": "id,slug", "limit": "1"}) or []
        if cited and cited[0].get("id") != item["id"]:
            print("  skipped %s: %s is already the artifact_commit of %s"
                  % (item["slug"][:48], sha[:12], cited[0].get("slug")))
            continue
        db.update("tasks", {"id": item["id"]}, {
            "artifact_commit": sha,
            "note": ("phantom_triage: landed evidence recorded from git - %s. "
                     "State deliberately unchanged; promotion belongs to "
                     "phantom_recovery via merge_truth." % item.get("detail", "")[:400]),
        })
        recorded += 1
    if recorded:
        print("\nRecorded artifact_commit on %d landed row(s). None promoted - "
              "run phantom_recovery.py to reconcile them." % recorded)

    if args.state != "PHANTOM_UNVERIFIED":
        print("\nEvidence recording only: --state %s. The class (b) close is refused "
              "outside PHANTOM_UNVERIFIED." % args.state)
        print("Closing a %s row is RECLASSIFICATION, not triage -- it changes what the "
              "fleet claims it shipped, and belongs to phantom_reclassify.py, which is "
              "the job that created this backlog in the first place and knows how to "
              "record that it did." % args.state)
        return 0

    closable = buckets[NO_TRACE]
    if not closable:
        print("\nNothing safely closable.")
        return 0

    closed = 0
    for item in closable:
        # Re-check at write time: this cannot clobber a row that has progressed
        # since the scan, the same guard phantom_reclassify uses.
        # Pinned to PHANTOM_UNVERIFIED rather than args.state, and deliberately:
        # the guard above already refused any other state before reaching here, so
        # this is the second lock on the only write that ends a task.
        current = db.select("tasks", {"id": "eq.%s" % item["id"], "select": "id,state"})
        if not current or current[0].get("state") != "PHANTOM_UNVERIFIED":
            continue
        # NOTE: db.update() builds the PostgREST operator itself (`eq.{v}`), unlike
        # db.select() which takes params verbatim. Passing "eq.<uuid>" here yields
        # `id=eq.eq.<uuid>` and a bare HTTP 400. Pass the raw id.
        db.update("tasks", {"id": item["id"]}, {
            "state": CLOSED_STATE,
            "note": ("phantom_triage 2026-08-11 (R3): no agent branch and no commit anywhere "
                     "names this slug - nothing was ever produced. Reversible: state and note "
                     "are the only fields touched."),
        })
        closed += 1

    print("\nClosed %d row(s) as %s. No row was promoted - promotion requires an" % (closed, CLOSED_STATE))
    print("artifact_commit and belongs to phantom_recovery.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
