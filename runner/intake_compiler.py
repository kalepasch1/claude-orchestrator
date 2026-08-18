#!/usr/bin/env python3
"""
intake_compiler.py - reads QUEUED rows from the coordination_tasks queue (the
code_improvement_request rows) and EMITS intake/*.md files in the exact format
intake_watcher.py already consumes.

Reuses the existing parser/field names from intake_watcher.py so output is
round-trippable; dedupes by slug (skips ids already present in intake/ or
intake/processed/). Pure transform with the Supabase read behind an injected
client so the unit test uses a fixture (NO live DB in tests).
"""
import os, sys, glob, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.dirname(os.path.abspath(__file__))
INTAKE = os.path.abspath(os.path.join(HERE, "..", "intake"))
PROCESSED = os.path.join(INTAKE, "processed")


def _existing_slugs(intake_dir=None):
    """Scan intake/ and intake/processed/ for slugs already present."""
    d = intake_dir or INTAKE
    slugs = set()
    proc = os.path.join(d, "processed")
    for folder in [d, proc]:
        if not os.path.isdir(folder):
            continue
        for f in os.listdir(folder):
            if not f.endswith(".md"):
                continue
            path = os.path.join(folder, f)
            try:
                with open(path, "r", errors="replace") as fh:
                    for line in fh:
                        m = re.match(r"^\s*-\s*id:\s*(.+)$", line.strip())
                        if m:
                            slugs.add(m.group(1).strip())
            except OSError:
                pass
    return slugs


def _format_task(row, project_name="beethoven"):
    """Convert a coordination_tasks row dict into canonical intake format block."""
    slug = row.get("slug") or row.get("id", "unknown")
    title = row.get("title") or row.get("slug") or "untitled"
    material = "yes" if row.get("material") else "no"
    model = row.get("model") or "haiku"
    depends = row.get("depends") or row.get("deps") or []
    if isinstance(depends, str):
        depends = [d.strip() for d in depends.split(",") if d.strip()]
    proof = row.get("proof") or ""
    prompt = row.get("prompt") or row.get("description") or ""

    deps_str = f"[{', '.join(depends)}]" if depends else "[]"

    lines = [
        f"- id: {slug}",
        f"  title: {title}",
        f"  material: {material}",
        f"  model: {model}",
        f"  depends: {deps_str}",
        f"  proof: {proof}",
        f"  prompt: |",
    ]
    for pline in prompt.splitlines():
        lines.append(f"    {pline}")
    return "\n".join(lines)


def compile_tasks(rows, project_name="beethoven", intake_dir=None):
    """Given a list of coordination_task row dicts, return (content, skipped_slugs).
    content is a canonical intake .md string; skipped_slugs lists slugs already present."""
    existing = _existing_slugs(intake_dir)
    skipped = []
    task_blocks = []

    for row in (rows or []):
        slug = row.get("slug") or row.get("id", "")
        if slug in existing:
            skipped.append(slug)
            continue
        task_blocks.append(_format_task(row, project_name))

    if not task_blocks:
        return "", skipped

    header = f"PROJECT: {project_name}\n\n"
    content = header + "\n\n".join(task_blocks) + "\n"
    return content, skipped


def emit_file(content, intake_dir=None, filename=None):
    """Write content to intake_dir as a .md file. Returns the path written."""
    d = intake_dir or INTAKE
    os.makedirs(d, exist_ok=True)
    if not filename:
        import datetime
        filename = f"compiled-{datetime.datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.md"
    path = os.path.join(d, filename)
    with open(path, "w") as f:
        f.write(content)
    return path


def fetch_queued_rows(client=None):
    """Fetch QUEUED coordination_tasks rows. Uses injected client or falls back to db module.
    Degrades gracefully when Supabase is unavailable — returns [] instead of raising."""
    if client is not None:
        try:
            return client.fetch_queued()
        except Exception:
            return []
    try:
        import db as _db
        rows = _db.select("coordination_tasks", {
            "select": "id,slug,title,material,model,depends,proof,prompt,description",
            "state": "eq.QUEUED",
        }) or []
        return rows
    except Exception:
        # fail-soft: no Supabase creds or connection error — skip live-read enrichment
        return _fetch_cached_rows()


def _fetch_cached_rows(cache_dir=None):
    """Fallback: read cached/mock rows from a local JSON file when Supabase is unavailable."""
    import json
    d = cache_dir or os.path.join(HERE, "..", ".runtime")
    cache_path = os.path.join(d, "intake_compiler_cache.json")
    try:
        if os.path.isfile(cache_path):
            with open(cache_path, "r", errors="replace") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        pass
    return []


def cache_rows(rows, cache_dir=None):
    """Persist fetched rows to local cache for offline fallback."""
    import json
    d = cache_dir or os.path.join(HERE, "..", ".runtime")
    os.makedirs(d, exist_ok=True)
    cache_path = os.path.join(d, "intake_compiler_cache.json")
    try:
        with open(cache_path, "w") as f:
            json.dump(rows, f, default=str)
    except OSError:
        pass


def run(client=None, project_name="beethoven", intake_dir=None):
    """Main entry: fetch queued rows, compile, emit file. Returns (path, skipped) or (None, [])."""
    rows = fetch_queued_rows(client)
    if rows:
        cache_rows(rows)  # persist for offline fallback
    if not rows:
        return None, []
    content, skipped = compile_tasks(rows, project_name, intake_dir)
    if not content:
        return None, skipped
    path = emit_file(content, intake_dir)
    return path, skipped


if __name__ == "__main__":
    path, skipped = run()
    if path:
        print(f"[intake-compiler] emitted {path}")
    if skipped:
        print(f"[intake-compiler] skipped (already present): {skipped}")
    if not path and not skipped:
        print("[intake-compiler] no queued coordination_tasks found")
