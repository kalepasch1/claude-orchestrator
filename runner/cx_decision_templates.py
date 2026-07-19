#!/usr/bin/env python3
"""
cx_decision_templates.py - mine determinations across apps for recurring decision patterns
(similar subjects + stable recommendations) and publish them as reusable "decision templates"
(inbox kind='decision_template') so common calls resolve instantly with cited precedent.
Idempotent; read-only except the templates; does not edit committees.py.
"""
import os, sys, json, re, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MIN_PATTERN = int(os.environ.get("TEMPLATE_MIN_PATTERN", "3"))
LIMIT = int(os.environ.get("TEMPLATE_SCAN_LIMIT", "500"))
STABILITY_THRESHOLD = float(os.environ.get("TEMPLATE_STABILITY", "0.8"))


def _shape(text):
    """Normalize text into a pattern for similarity grouping."""
    t = (text or "").lower()
    t = re.sub(r"[0-9a-f]{8,}", "#", t)
    t = re.sub(r"\d+", "#", t)
    t = re.sub(r"'[^']+'", "'*'", t)
    t = re.sub(r'"[^"]+"', '"*"', t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _direction(det):
    """Extract a normalized recommendation direction."""
    rec = (det.get("recommendation") or det.get("verdict") or "").lower()
    if any(w in rec for w in ("support", "go", "approve", "proceed")):
        return "support"
    if any(w in rec for w in ("oppose", "hold", "reject", "block")):
        return "oppose"
    if any(w in rec for w in ("conditional", "experiment", "revise")):
        return "conditional"
    return "other"


def run():
    dets = db.select("determinations", {
        "select": "id,title,subject,recommendation,verdict,app,created_at",
        "order": "created_at.desc",
        "limit": str(LIMIT),
    }) or []

    if not dets:
        return {"status": "no_data", "detail": "no determinations found"}

    # Check already-published templates to avoid duplicates
    existing = db.select("inbox", {
        "select": "title",
        "kind": "eq.decision_template",
        "limit": "200",
    }) or []
    existing_patterns = {_shape(e.get("title", "")) for e in existing}

    # Group by shaped title
    groups = {}
    for d in dets:
        pattern = _shape(d.get("title") or d.get("subject") or "")
        if not pattern.strip():
            continue
        groups.setdefault(pattern, []).append(d)

    templates_created = 0

    for pattern, members in groups.items():
        if len(members) < MIN_PATTERN:
            continue

        # Skip if template already published
        if pattern in existing_patterns:
            continue

        # Check recommendation stability
        directions = [_direction(m) for m in members]
        dominant = max(set(directions), key=directions.count) if directions else "other"
        stability = directions.count(dominant) / len(directions) if directions else 0

        if stability < STABILITY_THRESHOLD:
            continue  # not stable enough for a template

        sample_ids = [m.get("id") for m in members[:5] if m.get("id")]
        sample_titles = [m.get("title") or m.get("subject") or "" for m in members[:3]]
        apps = list({m.get("app") or "unknown" for m in members})

        body = (
            f"Recurring decision pattern ({len(members)} instances, "
            f"{stability:.0%} stability).\n\n"
            f"Pattern: {pattern}\n"
            f"Stable recommendation: {dominant}\n"
            f"Apps: {', '.join(apps)}\n"
            f"Sample titles: {'; '.join(sample_titles)}\n"
            f"Precedent IDs: {', '.join(str(i) for i in sample_ids)}\n\n"
            f"Template: future determinations matching this pattern can be auto-resolved "
            f"as '{dominant}' with cited precedent from {len(members)} prior decisions."
        )

        db.insert("inbox", {
            "kind": "decision_template",
            "title": f"Decision template: {pattern[:80]}",
            "body": body[:3000],
            "created_at": datetime.datetime.utcnow().isoformat() + "Z",
        })
        templates_created += 1

    return {
        "status": "ok",
        "templates_created": templates_created,
        "patterns_scanned": len(groups),
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
