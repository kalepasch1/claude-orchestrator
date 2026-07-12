#!/usr/bin/env python3
"""
cx_auto_adr.py - Auto-generate ADR markdown files from recent material determinations.

For recent material determinations, writes a short ADR markdown file under
docs/decisions/ADR-<date>-<slug>.md capturing the decision, the contributors/factions,
the counter-arguments, and the proof_hash. Idempotent (skips if the ADR already exists).
Reuses the determination's stored fields; does not edit committees.py.
"""
import os, sys, re, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

HERE = os.path.dirname(os.path.abspath(__file__))
ADR_DIR = os.path.abspath(os.path.join(HERE, "..", "docs", "decisions"))
LIMIT = int(os.environ.get("AUTO_ADR_LIMIT", "20"))


def _slugify(text):
    """Convert title to a filesystem-safe slug."""
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:60] or "untitled"


def _write_adr(det):
    """Write one ADR file for a determination. Returns path if created, None if skipped."""
    created_at = det.get("created_at") or datetime.datetime.utcnow().isoformat()
    date_str = created_at[:10]
    slug = _slugify(det.get("title") or det.get("id", "unknown"))
    filename = f"ADR-{date_str}-{slug}.md"
    filepath = os.path.join(ADR_DIR, filename)

    if os.path.exists(filepath):
        return None  # idempotent

    title = det.get("title") or "Untitled determination"
    recommendation = det.get("recommendation") or "No recommendation recorded."
    contributors = det.get("contributors") or []
    factions = det.get("factions") or {}
    dissent = det.get("dissent") or "None"
    proof_hash = det.get("proof_hash") or "n/a"

    if isinstance(contributors, list):
        contrib_str = ", ".join(str(c) for c in contributors) or "n/a"
    else:
        contrib_str = str(contributors)

    if isinstance(factions, dict):
        faction_lines = []
        for faction, members in factions.items():
            if isinstance(members, list):
                faction_lines.append(f"- **{faction}**: {', '.join(str(m) for m in members)}")
            else:
                faction_lines.append(f"- **{faction}**: {members}")
        factions_str = "\n".join(faction_lines) if faction_lines else "n/a"
    else:
        factions_str = str(factions) if factions else "n/a"

    content = f"""# {title}

**Date:** {date_str}
**Status:** Accepted
**Proof hash:** `{proof_hash}`

## Decision

{recommendation}

## Contributors

{contrib_str}

## Factions

{factions_str}

## Counter-arguments (dissent)

{dissent}
"""

    os.makedirs(ADR_DIR, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath


def run():
    """Generate ADR files for recent material determinations."""
    dets = db.select("determinations", {
        "select": "id,title,recommendation,contributors,factions,dissent,proof_hash,created_at",
        "order": "created_at.desc",
        "limit": str(LIMIT),
    }) or []

    created = []
    skipped = 0
    for det in dets:
        path = _write_adr(det)
        if path:
            created.append(os.path.basename(path))
        else:
            skipped += 1

    return {"created": len(created), "skipped": skipped, "files": created}


if __name__ == "__main__":
    print(run())
