#!/usr/bin/env python3
"""Recover operator improvements without regenerating code that already exists.

The forensic audit deliberately moved evidence-free MERGED rows to
PHANTOM_UNVERIFIED. That made the metrics truthful, but the first recovery loop
blindly returned every manual row to QUEUED. When an artifact already existed on
staging, that caused a destructive state loop: MERGED -> PHANTOM -> QUEUED ->
regenerate, and the release manifest could no longer discover the original work.

This job now reconciles exact Git evidence first:
  * artifact reachable from integration -> restore MERGED (do not rewrite code)
  * artifact exists but is not integrated -> DONE + a fresh canonical train card
  * no artifact evidence -> QUEUED with the preservation contract below

It also repairs rows the old recovery job already moved to QUEUED/DONE while
retaining a valid artifact commit.
"""
import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import merge_truth


RECOVERY_MARK = "OPERATOR_PHANTOM_RECOVERY"
RECOVERY_CONTRACT = """## OPERATOR PHANTOM RECOVERY CONTRACT
This manual improvement was previously marked MERGED without repository evidence.
Reconcile it against the current base before editing. Preserve every newer or
overlapping improvement already present; layer in only missing optimal behavior.
If the behavior already exists, prove it with focused tests and an exact artifact
commit instead of replacing code or returning a no-op. The task is complete only
after tests, preservation/regression checks, staging integration, production
release, and deployment verification are durably recorded.
## END OPERATOR PHANTOM RECOVERY CONTRACT

"""


def _candidate_rows(limit):
    return db.select("tasks", {
        "select": ("id,slug,prompt,note,state,project_id,artifact_commit,"
                   "artifact_branch,base_branch"),
        "state": "eq.PHANTOM_UNVERIFIED",
        "slug": "like.dropbox-%",
        "order": "created_at.asc",
        "limit": str(max(1, int(limit))),
    }) or []


def _stranded_artifact_rows(limit):
    """Rows the old recovery loop already requeued despite retaining exact Git evidence."""
    return db.select("tasks", {
        "select": ("id,slug,prompt,note,state,project_id,artifact_commit,"
                   "artifact_branch,base_branch"),
        "state": "in.(QUEUED,DONE)",
        "slug": "like.dropbox-%",
        "artifact_commit": "not.is.null",
        "order": "updated_at.asc",
        "limit": str(max(1, int(limit))),
    }) or []


def _project_name(project_id):
    try:
        rows = db.select("projects", {
            "select": "name", "id": f"eq.{project_id}", "limit": "1",
        }) or []
        return str(rows[0].get("name") or "") if rows else ""
    except Exception:
        return ""


def _ensure_card(row, reason):
    """Create a canonical integration card for an existing, not-yet-integrated artifact."""
    try:
        import merge_train
        project = _project_name(row.get("project_id")) or "beethoven"
        result = merge_train.ensure_integration_card_result(
            project, row.get("slug"), kind="integrate",
            why="recover existing operator artifact without regenerating it",
            detail=reason[:1000], decided_by="canonical-train:phantom-recovery",
        )
        return result in merge_train.CARD_OK
    except Exception as exc:
        print(f"phantom_recovery: card repair failed for {row.get('slug')}: {exc}")
        return False


def _reconcile_artifact(row, now):
    """Return restored/recarded/absent/infra/concurrent for one exact artifact."""
    sha = str(row.get("artifact_commit") or "").strip()
    if not sha:
        return "absent"
    repo, target, err = merge_truth.resolve_target(row)
    if err:
        print(f"phantom_recovery: {row.get('slug')} unresolved: {err}")
        return "infra"
    verdict, reason = merge_truth.verify_merge_reachable(repo, sha, target, fetch=True)
    if verdict == merge_truth.INFRA_ERROR:
        print(f"phantom_recovery: {row.get('slug')} not changed: {reason}")
        return "infra"

    prior_state = row.get("state")
    prior_note = str(row.get("note") or "")
    if verdict == merge_truth.OK:
        patch = merge_truth.gate_merged_patch(row, {
            "state": "MERGED",
            "artifact_commit": sha,
            "note": (
                f"{RECOVERY_MARK} {now}: restored MERGED from exact integration evidence; "
                f"{reason}. Existing code preserved; no regeneration. Prior note: {prior_note}"
            )[:4000],
        }, repo=repo, prod_branch=target, fetch=False)
        if not patch or patch.get("state") != "MERGED":
            return "infra"
        result = db.update("tasks", {
            "id": row["id"], "state": prior_state,
        }, patch)
        return "restored" if result is not None else "concurrent"

    # verify_merge_reachable only returns PHANTOM here. A "not an ancestor" reason means
    # cat-file proved the exact commit exists; preserve it and send it back through the
    # serialized train. A nonexistent object is the only case that needs regeneration.
    if "not an ancestor" in reason:
        note = (
            f"{RECOVERY_MARK} {now}: exact artifact {sha[:12]} exists but is not yet in "
            f"{target}; restored DONE and re-carded for canonical integration without "
            f"regeneration. Prior note: {prior_note}"
        )[:4000]
        result = db.update("tasks", {
            "id": row["id"], "state": prior_state,
        }, {"state": "DONE", "note": note})
        if result is None:
            return "concurrent"
        if _ensure_card(row, reason):
            return "recarded"
        # No live card means DONE would strand the artifact again. Put the row back exactly
        # where this invocation found it so a later cycle can retry safely.
        db.update("tasks", {"id": row["id"], "state": "DONE"}, {
            "state": prior_state,
            "note": (f"{RECOVERY_MARK} {now}: integration card repair failed; retained "
                     f"{prior_state} for retry. Prior note: {prior_note}")[:4000],
        })
        return "infra"
    return "absent"


def recover(limit=100):
    rows = _candidate_rows(limit)
    recovered = []
    consolidated = []
    restored = []
    recarded = []
    infrastructure_holds = []
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # First repair work already moved by the old loop. Dedupe by task id because a DONE row
    # can change state between the two snapshots below.
    seen = set()
    artifact_outcomes = {}
    for row in (_stranded_artifact_rows(limit) + rows):
        if row.get("id") in seen:
            continue
        seen.add(row.get("id"))
        outcome = _reconcile_artifact(row, now)
        artifact_outcomes[row.get("id")] = outcome
        if outcome == "restored":
            restored.append(row.get("slug"))
        elif outcome == "recarded":
            recarded.append(row.get("slug"))
        elif outcome == "infra":
            infrastructure_holds.append(row.get("slug"))

    for row in rows:
        if row.get("state") != "PHANTOM_UNVERIFIED":
            continue
        if artifact_outcomes.get(row.get("id")) in ("restored", "recarded", "infra"):
            continue
        prompt = str(row.get("prompt") or "")
        if RECOVERY_MARK not in prompt:
            prompt = f"{RECOVERY_CONTRACT}{RECOVERY_MARK}\n\n{prompt}"
        prior_note = str(row.get("note") or "")
        note = (
            f"{RECOVERY_MARK} {now}: requeued operator-originated work after false-merge audit; "
            "reconcile current code, preserve overlaps, and require exact ship evidence. "
            f"Prior note: {prior_note}"
        )[:4000]
        # Match by id and prior state so concurrent recovery can never double-claim
        # or move a row that progressed after this scan.
        result = db.update("tasks", {
            "id": row["id"], "state": "PHANTOM_UNVERIFIED",
        }, {
            "state": "QUEUED",
            "prompt": prompt,
            "note": note,
            "submitted_by_label": "Kale Pasch (legacy dropbox)",
            "priority": 10,
        })
        if result is not None:
            recovered.append(row.get("slug"))
            continue
        # The queue has a uniqueness guard for active slugs. A rejected update
        # therefore usually means this exact improvement already has a live
        # recovery row. Consolidate the audited duplicate instead of spawning a
        # second writer or retrying it forever.
        keepers = db.select("tasks", {
            "select": "id,slug,state",
            "slug": f"eq.{row.get('slug')}",
            "state": "in.(QUEUED,RUNNING,RETRY,DONE)",
            "order": "created_at.asc", "limit": "1",
        }) or []
        if keepers:
            keeper = keepers[0]
            duplicate_note = (
                f"{RECOVERY_MARK} {now}: duplicate audit row consolidated into active "
                f"task {keeper.get('id')} ({keeper.get('state')}); no second writer created. "
                f"Prior note: {prior_note}"
            )[:4000]
            moved = db.update("tasks", {
                "id": row["id"], "state": "PHANTOM_UNVERIFIED",
            }, {
                "state": "DECOMPOSED", "note": duplicate_note,
                "deps": [keeper.get("slug")],
                "submitted_by_label": "Kale Pasch (legacy dropbox)",
            })
            if moved is not None:
                consolidated.append(row.get("slug"))
    try:
        import steering
        if recovered or consolidated or restored or recarded:
            steering.record(
                "operator_phantom_recovery", project="beethoven",
                actor_label="Kale Pasch",
                rationale="Restore manual improvements stranded by evidence-free MERGED certification",
                payload={"recovered": len(recovered), "consolidated": len(consolidated),
                         "restored": len(restored), "recarded": len(recarded),
                         "first": (restored + recarded + recovered)[:20]},
            )
    except Exception:
        pass
    print(f"phantom_recovery: restored {len(restored)} staged artifact(s), re-carded "
          f"{len(recarded)} existing artifact(s), recovered {len(recovered)}/{len(rows)} "
          f"evidence-free operator task(s), consolidated {len(consolidated)} duplicate(s), "
          f"held {len(infrastructure_holds)} on infrastructure uncertainty")
    return {"scanned": len(rows), "recovered": len(recovered),
            "consolidated": len(consolidated), "restored": len(restored),
            "recarded": len(recarded), "infrastructure_holds": len(infrastructure_holds),
            "slugs": recovered, "restored_slugs": restored, "recarded_slugs": recarded}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=int(os.environ.get("PHANTOM_RECOVERY_LIMIT", "100")))
    args = parser.parse_args()
    recover(limit=args.limit)


if __name__ == "__main__":
    main()
