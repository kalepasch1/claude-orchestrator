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
import time

import db

MERGE_KINDS = ("integrate", "merge", "code-merge")
GATE = "done-without-card"

#: Minutes between FULL sweeps (no time window). The per-tick call looks at the last
#: `within_hours` only, which is what keeps it to single-digit rows on a query that
#: runs every 60 seconds -- but a task that goes DONE without a card and then ages out
#: of that window would become invisible again, which is the exact bug the window was
#: introduced to fix, only slower. So one call an hour ignores the window entirely.
FULL_SWEEP_MIN = float(os.environ.get("ORCH_DONE_CARD_FULL_SWEEP_MIN", "60"))
FULL_SWEEP_LIMIT = int(os.environ.get("ORCH_DONE_CARD_FULL_SWEEP_LIMIT", "2000"))

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


def _rejection_already_recorded(slug, gate, reason):
    """True when this exact refusal is already on file.

    THE REASON IS RECORDED ONCE, NOT ONCE PER PASS. This function runs on every
    merge-train tick -- every 60 seconds -- and a task that legitimately has no branch
    never stops qualifying, so each one re-wrote its own row forever. Measured
    2026-09-02:

        admission_rejections rows          5,616
        distinct slugs                       872   (6.4 duplicates each)

    A row per pass is not a record, it is a metronome. Fails OPEN: an unreadable table
    means write the row, because a missing refusal is a silent DONE task and that is the
    failure this module exists to stop.
    """
    try:
        rows = db.select("admission_rejections", {
            "select": "id,gate,reason", "slug": f"eq.{slug}",
            "gate": f"eq.{gate}", "limit": "20"}) or []
    except Exception:
        return False
    return any(str(r.get("reason") or "") == str(reason)[:500] for r in rows)


def record_rejection(task, reason, gate=GATE):
    """Persist why a DONE task gets no card. Fail-soft, but never silent on operator work."""
    slug = str(task.get("slug") or "")[:200]
    operator = bool(str(task.get("submitted_by") or "").strip()
                    or str(task.get("submitted_by_label") or "").strip()
                    or slug.startswith("dropbox-"))
    if slug and _rejection_already_recorded(slug, gate, reason):
        return True      # already on file: the contract is satisfied, not re-satisfied
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


def _full_sweep_stamp_path():
    home = os.environ.get("CLAUDE_ORCH_HOME") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), ".runtime")
    return os.path.join(home, "done_to_merged_full_sweep.stamp")


def _full_sweep_due(now=None):
    """True when the hourly window-free sweep is owed. Never raises."""
    if FULL_SWEEP_MIN <= 0:
        return False
    now = time.time() if now is None else now
    try:
        with open(_full_sweep_stamp_path()) as fh:
            last = float((fh.read() or "0").strip() or 0)
    except (OSError, ValueError):
        last = 0.0
    return (now - last) >= FULL_SWEEP_MIN * 60.0


def _mark_full_sweep(now=None):
    now = time.time() if now is None else now
    path = _full_sweep_stamp_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        scratch = path + ".tmp"
        with open(scratch, "w") as fh:
            fh.write("%f" % now)
        os.replace(scratch, path)
    except OSError:
        pass      # a stamp we cannot write means one extra full sweep, not a failure


def reconcile_missing_cards(within_hours=24, limit=500, project_names=None):
    """Every DONE task either has a card or a recorded reason. Returns a summary dict.

    Intended to run on the same tick as the merge train, before the pass.
    """
    summary = {"scanned": 0, "already_carded": 0, "cards_filed": 0,
               "rejections_recorded": 0, "errors": 0}
    # `within_hours` WAS A DEAD PARAMETER. It has been in this signature and this
    # docstring since the function was written and never reached the query, so every
    # tick asked for the newest 500 DONE tasks out of 1,017 and the fleet's own
    # truncation detector said so 154 times in one log:
    #
    #   [db] TRUNCATED SCAN done_to_merged.py:128 -> tasks returned exactly its limit
    #        (500) ordered by updated_at.desc. Anything past the cap is invisible
    #
    # Measured 2026-09-02: 517 DONE tasks sat past that cap, 6 of them with no card at
    # all -- so the promise in the docstring above ("every DONE task either has a card
    # or a recorded reason") was false for a third of the table, permanently, because
    # nothing ages back into the newest 500.
    #
    # Using the window the signature already declares fixes both halves at once. Only 8
    # DONE tasks were updated in the last 24h, so the per-tick scan goes from 500 rows
    # to single digits AND stops truncating -- this runs on every merge-train pass, and
    # the pass runs every 60 seconds. Pass within_hours=0 for a full sweep, which is
    # what the periodic backfill wants.
    params = {
        # `tasks` has artifact_branch / artifact_ref / base_branch — never a
        # bare `branch`. Selecting it returned HTTP 400 on every pass, so this
        # reconcile scanned nothing and no DONE task was ever checked for a
        # missing card. _branch_of() below already reads both names, which is
        # why the mismatch survived review: the consumer was tolerant and the
        # query was not.
        "select": "id,slug,note,project_id,artifact_branch,"
                  "submitted_by,submitted_by_label",
        "state": "eq.DONE",
        "order": "updated_at.desc",
        "limit": str(int(limit)),
    }
    # ONE SWEEP AN HOUR IGNORES THE WINDOW. Narrowing the per-tick scan to 24h is what
    # keeps it to single-digit rows, but on its own it would let a task that goes DONE
    # without a card simply age out of view -- the same invisibility, arriving more
    # slowly. The hourly sweep is the backstop, and it is inside this function rather
    # than in the scheduler so it cannot be forgotten by a caller.
    full_sweep = bool(within_hours) and _full_sweep_due()
    if full_sweep:
        within_hours = 0
        limit = max(int(limit), FULL_SWEEP_LIMIT)
        params["limit"] = str(limit)      # params was built above; keep them in step
        print(f"[done->merged] hourly full sweep: ignoring the {FULL_SWEEP_MIN:.0f}-minute "
              f"window, scanning up to {limit} DONE task(s)", flush=True)
    if within_hours:
        cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                               time.gmtime(time.time() - float(within_hours) * 3600.0))
        params["updated_at"] = f"gte.{cutoff}"
    try:
        tasks = db.select("tasks", params) or []
    except Exception as exc:
        print(f"[done->merged] scan failed: {exc}", flush=True)
        summary["errors"] += 1
        return summary
    if full_sweep:
        _mark_full_sweep()
    if len(tasks) >= int(limit):
        # Still truncated: say so HERE, where the window is known, rather than leaving
        # it to a generic db-layer warning nobody attributes to this scan.
        print(f"[done->merged] scan hit its {limit}-row cap over the last "
              f"{within_hours or 'all'} hour(s); older DONE tasks were not examined "
              f"this pass", flush=True)

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
