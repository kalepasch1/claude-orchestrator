#!/usr/bin/env python3
"""swarm_enqueue — the one-argument task filer the zero-token swarm bots actually need.

`enqueue.enqueue_task()` takes three REQUIRED keyword-only callables
(find_open_by_intent / insert / bump) so that its dedup core stays testable. The swarm
bots (conflict_marker_sentinel, canary_triage, self_deploy_watchdog) are pure and
injectable and call a ONE-ARGUMENT enqueue_fn. periodic.py wired bot #1 straight to
`enqueue.enqueue_task`, so every call raised TypeError before doing anything — and every
bot swallows enqueue failures by design (`except Exception: filed = False`).

Net effect: bot #1 has been WIRED BUT INERT since it landed. It could detect a
fleet-stopping condition every five minutes, report `filed=False`, and nobody would see a
task. This module is the missing binding: `enqueue(record)` is a complete filer that
reuses enqueue_task's dedup query and intent marker, so swarm-filed tasks coalesce
exactly like operator-filed ones.

PRIORITY, deliberately: the bots pass `priority: 1` meaning "tier-1, below user work".
That is NOT what the column means — claim_task sorts priority ASCENDING, so priority=1
would be claimed FIRST, ahead of every user-directed task, which is the exact opposite of
the owner directive. Ordering below user work is enforced by ev_scheduler's
_self_improve_tier, which tiers by PROJECT, not by this column. So swarm records are
filed at SWARM_PRIORITY (the table default) and the tier does the rest.
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import enqueue as _enqueue
import enqueue_task as _et
import pipeline_contract

DEFAULT_PROJECT = os.environ.get("ORCH_SWARM_PROJECT", "beethoven")
SWARM_SOURCE = "swarm-bot"
# The tasks.priority default. Low urgency on the claim sort; see the module docstring.
SWARM_PRIORITY = int(os.environ.get("ORCH_SWARM_PRIORITY", "1000"))


def _project(record):
    """(project_row, project_id). Falls back to the orchestrator's own project."""
    proj = _et.project_by_name(DEFAULT_PROJECT) or {}
    pid = record.get("project_id") or proj.get("id")
    return proj, pid


def enqueue(record):
    """File one swarm remediation task. Returns enqueue.EnqueueResult.

    Raises on failure ON PURPOSE. The bots already catch and surface `filed=False`; a
    filer that quietly returned success would recreate the silent-inertness defect this
    module exists to remove.
    """
    proj, pid = _project(record)
    if not pid:
        raise RuntimeError(
            f"swarm_enqueue: no project id — the record carries none and "
            f"'{DEFAULT_PROJECT}' is not registered in the projects table")
    slug = str(record.get("slug") or "").strip()
    if not slug:
        raise ValueError("swarm_enqueue: a record must carry a slug (it is the intent key)")
    kind = record.get("kind") or "remediation"
    project_name = proj.get("name") or DEFAULT_PROJECT
    row = {
        "project_id": pid,
        "slug": slug,
        "prompt": pipeline_contract.wrap_prompt(
            str(record.get("prompt") or ""), project=project_name, kind=kind,
            source=SWARM_SOURCE, slug=slug, material=False),
        "kind": kind,
        "state": record.get("state") or "QUEUED",
        "base_branch": record.get("base_branch") or proj.get("default_base") or "master",
        "note": pipeline_contract.note(str(record.get("note") or ""), source=SWARM_SOURCE),
        "priority": SWARM_PRIORITY,
    }

    def find_open(key):
        return _et._find_open_by_intent(pid, key)

    def insert(rec, key):
        persisted = dict(rec)
        persisted.pop("target_path", None)
        marker = f"[{_et._INTENT_MARKER}{key}]"
        persisted["note"] = f"{persisted.get('note', '').rstrip()} {marker}".strip()
        # The dedup core already established there is no OPEN equivalent; a terminal
        # historical row with the same slug may legitimately recur.
        persisted["_allow_dup"] = True
        task_id = _et._insert_id(db.insert("tasks", persisted))
        if not task_id:
            raise RuntimeError(f"swarm_enqueue: insert refused or returned no receipt: {slug}")
        return task_id

    def bump(existing):
        patch = {"updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
        if str(existing.get("state") or "").upper() in _et._RECOVERABLE_STATES:
            patch.update({"state": "QUEUED", "attempt": 0})
        db.update("tasks", {"id": existing["id"]}, patch)

    return _enqueue.enqueue_task(row, find_open_by_intent=find_open,
                                 insert=insert, bump=bump)
