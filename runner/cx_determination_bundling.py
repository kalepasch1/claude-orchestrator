#!/usr/bin/env python3
"""
cx_determination_bundling.py - cluster recent LOW-materiality determinations by title/body
similarity; when a tight cluster repeats, propose a single blanket ruling to cover the class
(inbox kind='bundle_proposal' citing members + common recommendation) so the engine stops
re-litigating the same call. Bounded; read-only except the proposal; does not edit committees.py.
"""
import os, sys, json, re, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MIN_CLUSTER = int(os.environ.get("BUNDLE_MIN_CLUSTER", "3"))
LIMIT = int(os.environ.get("BUNDLE_SCAN_LIMIT", "500"))


def _shape(text):
    """Normalize text into a fuzzy pattern for similarity grouping."""
    t = (text or "").lower()
    t = re.sub(r"[0-9a-f]{8,}", "#", t)
    t = re.sub(r"\d+", "#", t)
    t = re.sub(r"'[^']+'", "'*'", t)
    t = re.sub(r'"[^"]+"', '"*"', t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _cluster_determinations(dets):
    """Group determinations by (shaped title, recommendation direction)."""
    groups = {}
    for d in dets:
        title_shape = _shape(d.get("title") or d.get("subject") or "")
        recommendation = (d.get("recommendation") or d.get("verdict") or "").lower()
        direction = "support" if "support" in recommendation or "go" in recommendation else \
                    "oppose" if "oppose" in recommendation or "hold" in recommendation else "other"
        key = (title_shape, direction)
        groups.setdefault(key, []).append(d)
    return groups


def run():
    dets = db.select("determinations", {
        "select": "id,title,subject,recommendation,verdict,materiality,created_at",
        "materiality": "eq.LOW",
        "order": "created_at.desc",
        "limit": str(LIMIT),
    }) or []

    if not dets:
        return {"status": "no_data", "detail": "no LOW-materiality determinations found"}

    groups = _cluster_determinations(dets)
    proposals = 0

    for (pattern, direction), members in groups.items():
        if len(members) < MIN_CLUSTER:
            continue
        if not pattern.strip():
            continue

        member_ids = [m.get("id") for m in members if m.get("id")]
        sample_titles = [m.get("title") or m.get("subject") or "" for m in members[:3]]

        body = (
            f"Recurring LOW-materiality determination cluster ({len(members)} instances).\n"
            f"Pattern: {pattern}\n"
            f"Common direction: {direction}\n"
            f"Sample titles: {'; '.join(sample_titles)}\n"
            f"Member IDs: {', '.join(str(i) for i in member_ids[:20])}\n\n"
            f"Proposed blanket ruling: auto-resolve future matches as '{direction}' "
            f"to avoid re-litigating the same call."
        )

        db.insert("inbox", {
            "kind": "bundle_proposal",
            "title": f"Bundle proposal: {pattern[:80]}",
            "body": body[:3000],
            "created_at": datetime.datetime.utcnow().isoformat() + "Z",
        })
        proposals += 1

    return {"status": "ok", "proposals": proposals, "clusters_scanned": len(groups)}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
