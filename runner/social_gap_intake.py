#!/usr/bin/env python3
"""
social_gap_intake.py - close the self-writing loop WITHOUT autonomous unreviewed work.

Reads high-severity rows from growth_intake_suggestion (Supabase) and drafts intake
markdown in the EXACT format intake_watcher.py consumes (PROJECT, id, title, material,
model, depends, proof, prompt). Writes to intake/proposed/ — never directly to intake/.
A human moves approved files into intake/.

Idempotent: skips a gap that already has a proposed/queued/processed task (dedupe by stable slug).
Does NOT modify intake_watcher.py's live-intake behavior.
"""
import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

HERE = os.path.dirname(os.path.abspath(__file__))
PROPOSED = os.path.abspath(os.path.join(HERE, "..", "intake", "proposed"))

# Gap kind -> (title template, prompt template, proof)
GAP_TEMPLATES = {
    "zero_posts": (
        "apply starter content scheme for {app}",
        "Account {account} in {app} has 0 posts in 7 days. Apply the starter content scheme "
        "to generate initial drafts and schedule them. Keep nuxt build green.",
        "`nuxt build` exits 0",
    ),
    "drafts_stuck": (
        "trigger fillDrafts for stuck drafts in {app}",
        "Drafts in {app} are stuck in needs_generation state for account {account}. "
        "Trigger the fillDrafts pipeline to unblock them. Keep nuxt build green.",
        "`nuxt build` exits 0",
    ),
    "engagement_drop": (
        "diagnose engagement drop for {app}",
        "Account {account} in {app} has experienced a significant engagement drop. "
        "Analyze recent posts and suggest adjustments. Keep nuxt build green.",
        "`nuxt build` exits 0",
    ),
}

DEFAULT_TEMPLATE = (
    "address growth gap: {kind} for {app}",
    "Growth gap detected: {kind} for account {account} in {app}. {detail} "
    "Implement the smallest fix to address this. Keep nuxt build green.",
    "`nuxt build` exits 0",
)


def _slug_for_gap(gap):
    """Generate a stable slug from a gap row."""
    kind = (gap.get("kind") or "gap").replace(" ", "-").lower()
    app = (gap.get("app") or "unknown").replace(" ", "-").lower()
    account = str(gap.get("account_id") or gap.get("account") or "0")[:8]
    return f"gap-{kind}-{app}-{account}"


def _existing_slugs(project):
    """Collect slugs already proposed, queued, or processed to avoid duplicates."""
    slugs = set()
    # Check tasks table
    rows = db.select("tasks", {
        "select": "slug",
        "project_id": f"eq.{project}",
        "state": "in.(QUEUED,RUNNING,DONE,MERGED,BLOCKED,DECOMPOSED)",
    }) or []
    slugs.update(r["slug"] for r in rows if r.get("slug"))
    # Check proposed directory
    if os.path.isdir(PROPOSED):
        for fname in os.listdir(PROPOSED):
            if fname.endswith(".md"):
                slugs.add(fname.replace(".md", ""))
    return slugs


def format_intake(project, slug, title, material, model, depends, proof, prompt):
    """Format a single task in the canonical intake format."""
    deps_str = f"[{', '.join(depends)}]" if depends else "[]"
    return f"""PROJECT: {project}

- id: {slug}
  title: {title}
  material: {material}
  model: {model}
  depends: {deps_str}
  proof: {proof}
  prompt: |
    {prompt}
"""


def draft_intake(gaps, project="smarter"):
    """Draft intake markdown files for each gap. Returns list of written file paths."""
    os.makedirs(PROPOSED, exist_ok=True)
    existing = _existing_slugs(project)
    written = []

    for gap in gaps:
        slug = _slug_for_gap(gap)
        if slug in existing:
            continue

        kind = gap.get("kind", "")
        app = gap.get("app", "unknown")
        account = str(gap.get("account_id") or gap.get("account") or "unknown")
        detail = gap.get("detail") or gap.get("description") or ""
        fmt = {"kind": kind, "app": app, "account": account, "detail": detail}

        title_tpl, prompt_tpl, proof = GAP_TEMPLATES.get(kind, DEFAULT_TEMPLATE)
        title = title_tpl.format(**fmt)
        prompt = prompt_tpl.format(**fmt)

        content = format_intake(project, slug, title, "no", "haiku", [], proof, prompt)
        path = os.path.join(PROPOSED, f"{slug}.md")
        try:
            with open(path, "w") as f:
                f.write(content)
            written.append(path)
            existing.add(slug)
        except OSError:
            pass

    return written


def run():
    """Entry point for periodic scheduling."""
    gaps = db.select("growth_intake_suggestion", {
        "select": "*",
        "severity": "eq.high",
        "order": "created_at.desc",
        "limit": "20",
    }) or []
    if not gaps:
        return

    # Determine project from first gap or default
    project_id = gaps[0].get("project_id")
    if project_id:
        projects = db.select("projects", {"select": "name", "id": f"eq.{project_id}"}) or []
        project = projects[0]["name"] if projects else "smarter"
    else:
        project = "smarter"

    written = draft_intake(gaps, project)
    if written:
        try:
            db.insert("inbox", {
                "kind": "social_gap_intake",
                "title": f"Proposed {len(written)} intake tasks from growth gaps",
                "body": f"Files written to intake/proposed/. Review and move approved files to intake/.\n"
                        + "\n".join(os.path.basename(w) for w in written[:10]),
            })
        except Exception:
            pass
