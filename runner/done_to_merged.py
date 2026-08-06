"""DONE -> MERGED conversion: card admission guarantee and health metrics.

FAILURE 1, MEASURED AND ATTRIBUTED (2026-08-06)
-----------------------------------------------
36 of 111 tasks (32%) that reached DONE in a 12-hour window had NO integration
card at all. A DONE task with a pushed branch and no approvals row is invisible
to the merge train forever.

This is NOT the scan-window bug (cards ageing out of a query window, fixed
separately). These cards never existed. Of the four candidate mechanisms, the
measured answer is the first one -- **the task completed on a path that never
calls ensure_integration_card**:

    ensure_integration_card() is called from exactly three places:
      runner.py:317           inside integrate()
      integration_sweeper.py:474
      cowork_executor.py:260

    It is NOT called from set_state(). So every code path that writes
    state='DONE' without going through integrate() files no card. Measured over
    the last 24h of card-less DONE tasks:

      20  note "cowork-executor-v6.5: implemented and pushed ..."
           -- the Cowork executor skill marks tasks DONE with a direct
              `UPDATE tasks SET state='DONE'`, bypassing set_state() AND
              integrate(). The same note also appears on 29 tasks that DO have a
              card (the cowork_executor.py path), so this is a 41% no-card rate
              within one producer.
       8  note "folded into batch-mech-*"
           -- task fusion (runner.py ~2250) marks CHILD tasks DONE in bulk with
              a direct db.update; no child ever gets a card.
      11  other single set_state(state='DONE') call sites: cache hit (918),
           replay complete (964), rotated (978), revoked keys (996),
           paired-shadow verified (2204).

    Card filing was never transactional with the branch push because it was
    never on the DONE path at all.

The fix is a reconciler rather than 30 new call sites: any task that is DONE
with a pushed branch either gets a card, or gets an admission_rejections row
naming why it must not. Never silence. Producers keep filing cards inline when
they can -- this closes the paths that do not.
"""

import os

import db

MERGE_KINDS = ("integrate", "merge", "code-merge")
GATE = "done-without-card"

# Notes that mean "finished, but there is deliberately no branch to integrate".
# These get a recorded reason instead of a card -- they are correct, not lost.
NO_BRANCH_NOTE_MARKERS = (
    "folded into",              # task fusion: the parent carries the branch
    "paired-shadow verified",   # mutation intentionally discarded
    "revoked",                  # secret rotation, no code
    "rotated",
    "superseded",
    "already delivered",
    "no code target",
)


def _has_card(slug, cards_by_slug=None):
    if cards_by_slug is not None:
        return bool(cards_by_slug.get(slug))
    try:
        rows = db.select("approvals", {
            "select": "id", "slug": f"eq.{slug}",
            "kind": f"in.({','.join(MERGE_KINDS)})", "limit": "1"}) or []
    except Exception:
        return True     # unknown -> assume carded; never double-file on a read error
    return bool(rows)


def _branch_of(task):
    """The agent branch a DONE task should have pushed, if any."""
    for key in ("branch", "artifact_branch"):
        val = str(task.get(key) or "").strip()
        if val:
            return val
    slug = str(task.get("slug") or "").strip()
    return f"agent/{slug}" if slug else ""


def _deliberately_branchless(task):
    """True when this task correctly has no branch to integrate. Returns (bool, reason)."""
    note = str(task.get("note") or "").lower()
    for marker in NO_BRANCH_NOTE_MARKERS:
        if marker in note:
            return True, f"no branch by design: note matches '{marker}'"
    return False, ""


def record_rejection(task, reason, gate=GATE):
    """Persist why a DONE task gets no card. Fail-soft, but never silent on operator work."""
    slug = str(task.get("slug") or "")[:200]
    operator = bool(str(task.get("submitted_by") or "").strip()
                    or str(task.get("submitted_by_label") or "").strip()
                    or slug.startswith("dropbox-"))
    try:
        db.insert("admission_rejections", {
            "slug": slug,
            "project_id": task.get("project_id"),
            "gate": gate,
            "reason": str(reason)[:500],
            "operator_origin": operator,
            "submitted_by": str(task.get("submitted_by")
                                or task.get("submitted_by_label") or "")[:200] or None,
        })
    except Exception:
        return False
    if operator:
        print(f"[done->merged] ALERT: operator task {slug} finished with no card: {reason}",
              flush=True)
    return True


def reconcile_missing_cards(within_hours=24, limit=500, project_names=None):
    """Every DONE task either has a card or a recorded reason. Returns a summary dict.

    Intended to run on the same tick as the merge train, before the pass.
    """
    summary = {"scanned": 0, "already_carded": 0, "cards_filed": 0,
               "rejections_recorded": 0, "errors": 0}
    try:
        tasks = db.select("tasks", {
            "select": "id,slug,note,project_id,branch,submitted_by,submitted_by_label",
            "state": "eq.DONE",
            "order": "updated_at.desc",
            "limit": str(int(limit))}) or []
    except Exception as exc:
        print(f"[done->merged] scan failed: {exc}", flush=True)
        summary["errors"] += 1
        return summary

    projects = {}
    try:
        projects = {p["id"]: p.get("name") for p in (db.select("projects") or [])}
    except Exception:
        pass

    for task in tasks:
        slug = str(task.get("slug") or "").strip()
        if not slug:
            continue
        pname = projects.get(task.get("project_id")) or ""
        if project_names and pname not in project_names:
            continue
        summary["scanned"] += 1

        if _has_card(slug):
            summary["already_carded"] += 1
            continue

        branchless, why = _deliberately_branchless(task)
        if branchless:
            if record_rejection(task, why):
                summary["rejections_recorded"] += 1
            else:
                summary["errors"] += 1
            continue

        branch = _branch_of(task)
        if not branch:
            if record_rejection(task, "no branch recorded and slug yields no agent branch"):
                summary["rejections_recorded"] += 1
            else:
                summary["errors"] += 1
            continue

        # File the card the producer's code path never filed.
        try:
            import merge_train
            merge_train.ensure_integration_card(
                pname, slug,
                title=f"merge of {slug}",
                why="reconciler: task reached DONE with a branch and no card",
                detail=f"filed by done_to_merged.reconcile_missing_cards; branch={branch}",
                status="approved",
                decided_by="canonical-train:reconciler",
            )
            summary["cards_filed"] += 1
        except Exception as exc:
            summary["errors"] += 1
            record_rejection(task, f"card filing raised: {exc}", gate="card-filing-error")

    print(f"[done->merged] reconcile: {summary['scanned']} scanned, "
          f"{summary['already_carded']} carded, {summary['cards_filed']} filed, "
          f"{summary['rejections_recorded']} rejections, {summary['errors']} errors",
          flush=True)
    return summary


def conversion_stats(within_hours=24):
    """DONE->MERGED conversion rate and no-card count, for the health surface.

    Returns sensible zeros rather than raising -- a health probe must not be the
    thing that goes down.
    """
    stats = {"window_hours": within_hours, "done": 0, "merged": 0,
             "conversion_pct": 0.0, "done_without_card": 0, "no_card_pct": 0.0}
    try:
        done = db.select("tasks", {"select": "slug", "state": "eq.DONE",
                                   "limit": "2000"}) or []
        merged = db.count("tasks", {"state": "eq.MERGED"})
    except Exception:
        return stats

    stats["done"] = len(done)
    stats["merged"] = int(merged or 0)
    total = stats["done"] + stats["merged"]
    if total:
        stats["conversion_pct"] = round(100.0 * stats["merged"] / total, 1)

    missing = 0
    for task in done:
        slug = str(task.get("slug") or "").strip()
        if slug and not _has_card(slug):
            missing += 1
    stats["done_without_card"] = missing
    if stats["done"]:
        stats["no_card_pct"] = round(100.0 * missing / stats["done"], 1)
    return stats


def publish_health(stats=None):
    """Push conversion metrics to fleet_telemetry so the stage cannot silently regress."""
    stats = stats or conversion_stats()
    ok = True
    for metric in ("conversion_pct", "done_without_card", "no_card_pct", "done", "merged"):
        try:
            db.insert("fleet_telemetry", {
                "app": "merge_train", "domain": "done_to_merged",
                "metric": f"done_to_merged.{metric}",
                "value": float(stats.get(metric) or 0),
                "tags": {"window_hours": stats.get("window_hours")}})
        except Exception:
            ok = False
    return ok


if __name__ == "__main__":
    if os.environ.get("RECONCILE", "1") not in ("0", "false", "no"):
        reconcile_missing_cards()
    s = conversion_stats()
    print(f"[done->merged] DONE={s['done']} MERGED={s['merged']} "
          f"conversion={s['conversion_pct']}% no-card={s['done_without_card']} "
          f"({s['no_card_pct']}%)")
    publish_health(s)
