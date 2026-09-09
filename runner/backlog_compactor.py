#!/usr/bin/env python3
"""Collapse stale broad queued work into project-level backlog batches."""
import collections
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import pipeline_contract
import privacy

MARK = "backlog-compactor"
DEFAULT_LIMIT = int(os.environ.get("ORCH_BACKLOG_COMPACT_LIMIT", "500"))
MAX_GROUPS = int(os.environ.get("ORCH_BACKLOG_COMPACT_GROUPS", "10"))
MAX_ITEMS_PER_GROUP = int(os.environ.get("ORCH_BACKLOG_COMPACT_ITEMS_PER_GROUP", "50"))
PROTECTED_PREFIXES = (
    "qafix-", "relfix-", "buildfix-", "deployfix-",
    "recover-missing-branch-", "rework-", "canary-", "improve-",
    "cont-", "cont-batch-", "backlog-batch-",
)


# Intents that are instructions to the PLANNER, not descriptions of product work.
#
# The compactor collapses stale queued tasks by quoting each one's original
# request as a bullet. When that request is itself "split this into sub-tasks" or
# "reply ATOMIC", the bullet is a decomposition instruction — and the batch task
# it produces is then decomposed again, into fresh tasks whose entire content is
# the instruction to decompose. The loop feeds on its own output.
#
# Observed in the queue: backlog-batch-tomorrow-9d5e4db's ONLY intent was "Split
# the initial build task into 3-4 smaller sub-tasks"; its slices are more of the
# same, and backlog-batch-tomorrow-27c692f decomposed into five children that are
# all "split the build task into..." / "verify the task cannot be split" /
# "reply ATOMIC". Nine tasks across two families, none of which can ever produce
# a diff, all consuming claims from sixteen executors.
_META_INTENT_RX = re.compile(
    r"split\s+(the|this|it|into|large|failed|initial|original|build)\b.*\bsub-?tasks?\b"
    r"|split\s+the\s+(build|original|failed|large)\s+task\b"
    r"|\breply\s+'?atomic'?\b"
    r"|\bis\s+genuinely\s+atomic\b"
    r"|verify\s+(that\s+)?the\s+task\s+cannot\s+be\s+split"
    r"|double-?check\s+that\s+the\s+task\s+cannot\s+be\s+split"
    r"|do\s+not\s+recreate\s+one\s+task\s+per\s+bullet",
    re.I | re.S,
)


def is_meta_intent(text):
    """True when an intent describes decomposing work rather than doing any.

    Kept deliberately narrow: it matches the planner's own stock phrasings, not
    anything that merely mentions a task. A real request that happens to say
    "split the payment into two rows" must still be collapsed normally.
    """
    return bool(_META_INTENT_RX.search(str(text or "")))


def _slug(text):
    return re.sub(r"[^a-z0-9-]+", "-", str(text or "").lower()).strip("-") or "backlog"


def _projects():
    try:
        return {p["id"]: p for p in (db.select("projects", {"select": "id,name"}) or [])}
    except Exception:
        return {}


def _protected(row):
    slug = str(row.get("slug") or "")
    note = str(row.get("note") or "").lower()
    return slug.startswith(PROTECTED_PREFIXES) or "release_train" in note or "vercel" in note


def _rows(limit):
    rows = db.select(
        "tasks",
        {"select": "id,slug,prompt,note,project_id,base_branch,created_at,updated_at,material,deps",
         "state": "eq.QUEUED", "order": "updated_at.asc", "limit": str(limit)},
    ) or []
    return [
        r for r in rows
        if not _protected(r)
        and not r.get("material")
        and not (r.get("deps") or [])
        and MARK not in str(r.get("note") or "")
    ]


def _existing(slug):
    return bool(db.select("tasks", {"select": "id", "slug": f"eq.{slug}", "limit": "1"}) or [])


def _coder_for(text):
    return "ollama" if privacy.sensitivity(text) != "standard" else os.environ.get("ORCH_BACKLOG_COMPACTOR_CODER", "codex")


def collapsible(rows):
    """The subset of `rows` that describes work worth consolidating.

    Two rows are dropped, both of which used to become bullets:

      * an EMPTY original request. `backlog-batch-tomorrow-9d5e4db-slice-1`
        reached the queue reading, in full, "Original intents:\\n1.\\n" — a task
        with no described change, which no agent can do anything with and which
        still consumes a claim.
      * a decomposition instruction (see `is_meta_intent`), which turns the
        planner's own bookkeeping back into a build task.
    """
    keep = []
    for row in rows:
        raw = pipeline_contract.original_request(row.get("prompt") or "").strip()
        if not raw or is_meta_intent(raw):
            continue
        keep.append(row)
    return keep


def _prompt(project_name, rows):
    bullets = []
    for i, row in enumerate(rows[:MAX_ITEMS_PER_GROUP], 1):
        raw = pipeline_contract.original_request(row.get("prompt") or "").strip()
        raw = re.sub(r"\s+", " ", raw)[:600]
        bullets.append(f"{i}. {row.get('slug')}: {raw}")
    text = (
        "Consolidated stale backlog recovery.\n\n"
        f"Project: {project_name or 'unknown'}\n"
        f"Collapsed queued tasks: {len(rows)}\n\n"
        "Original intents:\n" + "\n".join(bullets) + "\n\n"
        "Select the smallest coherent high-value implementation that covers the most repeated intent. "
        "Do not recreate one task per bullet. Reuse existing code, merged-diff patterns, and current "
        "project conventions. Run relevant checks and commit. If some bullets are obsolete or already "
        "covered by release/recovery work, leave them collapsed."
    )
    try:
        return pipeline_contract.wrap_prompt(
            text, project=project_name or "", kind="build", source=MARK,
            slug=f"backlog-batch-{_slug(project_name)}", material=False,
        )
    except Exception:
        return text


def _insert_task(row):
    variants = [
        row,
        {k: v for k, v in row.items() if k != "sensitivity"},
        {k: v for k, v in row.items() if k not in ("sensitivity", "material")},
        {k: v for k, v in row.items() if k not in ("sensitivity", "material", "force_coder")},
        {k: v for k, v in row.items() if k not in ("sensitivity", "material", "force_coder", "deps")},
    ]
    for candidate in variants:
        try:
            db.insert("tasks", candidate)
            return True
        except Exception:
            continue
    return False


def run(limit=DEFAULT_LIMIT):
    if os.environ.get("ORCH_BACKLOG_COMPACTOR", "true").lower() not in ("1", "true", "yes", "on"):
        return {"skipped": "disabled"}
    rows = _rows(limit)
    projects = _projects()
    grouped = collections.defaultdict(list)
    for row in rows:
        grouped[row.get("project_id")].append(row)
    groups = sorted(grouped.items(), key=lambda kv: len(kv[1]), reverse=True)[:MAX_GROUPS]
    created = parked = skipped = meta_dropped = 0
    min_group = int(os.environ.get("ORCH_BACKLOG_COMPACT_MIN_GROUP", "8"))
    for project_id, all_items in groups:
        # Drop empty and decomposition-only intents BEFORE the size check, so a
        # group made entirely of planner bookkeeping cannot reach the threshold
        # and mint a batch task with nothing in it to do.
        items = collapsible(all_items)
        meta_dropped += len(all_items) - len(items)
        if len(items) < min_group:
            continue
        p = projects.get(project_id, {})
        pname = p.get("name") or str(project_id or "unknown")[:8]
        digest = hashlib.sha1(
            "|".join(str(r.get("id") or r.get("slug")) for r in items[:MAX_ITEMS_PER_GROUP]).encode("utf-8")
        ).hexdigest()[:7]
        batch_slug = f"backlog-batch-{_slug(pname)[:40]}-{digest}"[:80]
        combined = "\n".join(str(r.get("prompt") or "") for r in items[:MAX_ITEMS_PER_GROUP])
        if not _existing(batch_slug):
            coder = _coder_for(combined)
            if not _insert_task({
                "project_id": project_id,
                "slug": batch_slug,
                "state": "QUEUED",
                "kind": "build",
                "prompt": _prompt(pname, items),
                "note": f"{MARK}: collapsed {len(items)} stale queued tasks",
                "base_branch": items[0].get("base_branch") or "main",
                "deps": [],
                "material": False,
                "force_coder": coder,
                "model": coder,
                "sensitivity": privacy.sensitivity(combined),
            }):
                skipped += 1
                continue
            created += 1
        for row in items:
            try:
                db.update("tasks", {"id": row["id"]},
                          {"state": "DECOMPOSED", "account": None, "updated_at": "now()",
                           "note": f"{MARK}: collapsed into {batch_slug}"})
                parked += 1
            except Exception:
                skipped += 1
    summary = {"scanned": len(rows), "groups": len(groups), "created": created,
               "parked": parked, "skipped": skipped,
               # Counted so the drop is visible. A filter that silently removes
               # work is indistinguishable from one that is broken.
               "meta_dropped": meta_dropped}
    try:
        db.insert("controls", {"key": MARK, "value": json.dumps(summary, default=str),
                               "updated_at": "now()"}, upsert=True)
    except Exception:
        pass
    print(f"{MARK}: {summary}")
    return summary


if __name__ == "__main__":
    print(run())
