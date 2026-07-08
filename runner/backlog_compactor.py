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
    created = parked = skipped = 0
    min_group = int(os.environ.get("ORCH_BACKLOG_COMPACT_MIN_GROUP", "8"))
    for project_id, items in groups:
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
               "parked": parked, "skipped": skipped}
    try:
        db.insert("controls", {"key": MARK, "value": json.dumps(summary, default=str),
                               "updated_at": "now()"}, upsert=True)
    except Exception:
        pass
    print(f"{MARK}: {summary}")
    return summary


if __name__ == "__main__":
    print(run())
