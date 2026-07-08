#!/usr/bin/env python3
"""Collapse session continuation shards into a few executable backlog tasks."""
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

MARK = "continuation-compactor"
DEFAULT_LIMIT = int(os.environ.get("ORCH_CONT_COMPACT_LIMIT", "600"))
MAX_GROUPS = int(os.environ.get("ORCH_CONT_COMPACT_GROUPS", "12"))
MAX_ITEMS_PER_GROUP = int(os.environ.get("ORCH_CONT_COMPACT_ITEMS_PER_GROUP", "40"))


def _slug(text):
    return re.sub(r"[^a-z0-9-]+", "-", str(text or "").lower()).strip("-") or "continuation"


def _projects():
    try:
        return {p["id"]: p for p in (db.select("projects", {"select": "id,name"}) or [])}
    except Exception:
        return {}


def _existing(slug):
    return bool(db.select("tasks", {"select": "id", "slug": f"eq.{slug}", "limit": "1"}) or [])


def _coder_for(text):
    if privacy.sensitivity(text) != "standard":
        return "ollama"
    return os.environ.get("ORCH_CONTINUATION_COMPACTOR_CODER", "codex")


def _prompt(project_name, rows):
    bullets = []
    for i, row in enumerate(rows[:MAX_ITEMS_PER_GROUP], 1):
        raw = pipeline_contract.original_request(row.get("prompt") or "").strip()
        raw = re.sub(r"\s+", " ", raw)[:650]
        bullets.append(f"{i}. {row.get('slug')}: {raw}")
    text = (
        "Consolidated continuation backlog recovery.\n\n"
        f"Project: {project_name or 'unknown'}\n"
        f"Collapsed continuation shards: {len(rows)}\n\n"
        "Original continuation intents:\n" + "\n".join(bullets) + "\n\n"
        "Implement the smallest coherent, high-value subset that advances the project without creating "
        "more continuation shards. Prefer already queued release/recovery/quarantine tasks if they cover "
        "the same intent. Reuse existing helpers and merged-diff patterns, run relevant checks, and commit. "
        "Do not recreate one task per bullet; this task exists to collapse queue churn."
    )
    try:
        return pipeline_contract.wrap_prompt(
            text, project=project_name or "", kind="build", source=MARK,
            slug=f"cont-batch-{_slug(project_name)}", material=False,
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


def _cont_rows(limit):
    rows = db.select(
        "tasks",
        {"select": "id,slug,prompt,note,project_id,base_branch,created_at,updated_at",
         "state": "eq.QUEUED", "slug": "like.cont-%",
         "order": "updated_at.asc", "limit": str(limit)},
    ) or []
    return [r for r in rows if MARK not in str(r.get("note") or "")]


def run(limit=DEFAULT_LIMIT):
    if os.environ.get("ORCH_CONTINUATION_COMPACTOR", "true").lower() not in ("1", "true", "yes", "on"):
        return {"skipped": "disabled"}
    rows = _cont_rows(limit)
    projects = _projects()
    grouped = collections.defaultdict(list)
    for row in rows:
        grouped[row.get("project_id")].append(row)
    groups = sorted(grouped.items(), key=lambda kv: len(kv[1]), reverse=True)[:MAX_GROUPS]
    created = parked = skipped = 0
    for project_id, items in groups:
        if len(items) < int(os.environ.get("ORCH_CONT_COMPACT_MIN_GROUP", "5")):
            continue
        p = projects.get(project_id, {})
        pname = p.get("name") or str(project_id or "unknown")[:8]
        digest = hashlib.sha1(
            "|".join(str(r.get("id") or r.get("slug")) for r in items[:MAX_ITEMS_PER_GROUP]).encode("utf-8")
        ).hexdigest()[:7]
        batch_slug = f"cont-batch-{_slug(pname)[:42]}-{digest}"[:80]
        combined = "\n".join(str(r.get("prompt") or "") for r in items[:MAX_ITEMS_PER_GROUP])
        if not _existing(batch_slug):
            coder = _coder_for(combined)
            inserted = _insert_task({
                "project_id": project_id,
                "slug": batch_slug,
                "state": "QUEUED",
                "kind": "build",
                "prompt": _prompt(pname, items),
                "note": f"{MARK}: collapsed {len(items)} continuation shards",
                "base_branch": items[0].get("base_branch") or "main",
                "deps": [],
                "material": False,
                "force_coder": coder,
                "model": coder,
                "sensitivity": privacy.sensitivity(combined),
            })
            if inserted:
                created += 1
            else:
                skipped += 1
                continue
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
