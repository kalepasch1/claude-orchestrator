#!/usr/bin/env python3
"""
cx_determination_bundling.py - cluster recent LOW-materiality determinations by
title/body similarity. When a tight cluster repeats, propose a single blanket
ruling to cover the class (inbox kind='bundle_proposal' citing members + common
recommendation) so the engine stops re-litigating the same call.

Bounded; read-only except the proposal; does not edit committees.py.
"""
import os, sys, json, re, time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MAX_PER_RUN = int(os.environ.get("CX_BUNDLE_MAX", "50"))
MIN_CLUSTER_SIZE = int(os.environ.get("CX_BUNDLE_MIN_CLUSTER", "3"))
SIMILARITY_THRESHOLD = float(os.environ.get("CX_BUNDLE_SIM_THRESH", "0.6"))


def _tokenize(text):
    """Simple word-level tokenizer for similarity comparison."""
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _jaccard(a, b):
    """Jaccard similarity between two token sets."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _text_of(det):
    """Extract comparable text from a determination."""
    parts = []
    for k in ("title", "body", "recommendation", "rationale"):
        v = det.get(k)
        if v:
            parts.append(str(v)[:200])
    return " ".join(parts)


def _cluster(dets):
    """Cluster determinations by pairwise Jaccard similarity on title/body tokens."""
    items = [(d, _tokenize(_text_of(d))) for d in dets]
    clusters = []
    used = set()

    for i, (det_i, tok_i) in enumerate(items):
        if i in used:
            continue
        cluster = [det_i]
        used.add(i)
        for j, (det_j, tok_j) in enumerate(items):
            if j in used:
                continue
            if _jaccard(tok_i, tok_j) >= SIMILARITY_THRESHOLD:
                cluster.append(det_j)
                used.add(j)
        if len(cluster) >= MIN_CLUSTER_SIZE:
            clusters.append(cluster)
    return clusters


def _common_recommendation(cluster):
    """Find the most common recommendation in a cluster."""
    recs = defaultdict(int)
    for d in cluster:
        rec = str(d.get("recommendation") or d.get("verdict") or "").strip()
        if rec:
            recs[rec] += 1
    if not recs:
        return "no common recommendation"
    return max(recs, key=recs.get)


def _propose_bundle(cluster, project=None):
    """Write a bundle_proposal inbox row for a cluster."""
    member_ids = [str(d.get("id", "")) for d in cluster]
    common_rec = _common_recommendation(cluster)
    sample_title = cluster[0].get("title") or cluster[0].get("slug") or "untitled"

    try:
        db.insert("inbox", {
            "project": project or "beethoven",
            "kind": "bundle_proposal",
            "title": f"Blanket ruling proposal: {sample_title[:60]} (+{len(cluster)-1} similar)",
            "body": json.dumps({
                "member_count": len(cluster),
                "member_ids": member_ids[:20],
                "common_recommendation": common_rec,
                "sample_titles": [str(d.get("title") or "")[:80] for d in cluster[:5]],
            }),
            "source": "cx_determination_bundling",
            "created_at": "now()",
        })
        return True
    except Exception:
        return False


def run(project=None):
    """Main entry point: cluster LOW-materiality determinations and propose bundles."""
    try:
        dets = db.query(
            "determinations",
            filters={"materiality": "eq.LOW"},
            order="created_at.desc",
            limit=MAX_PER_RUN,
        ) or []
    except Exception:
        dets = []

    if not dets:
        return {"processed": 0, "bundles": 0, "note": "no LOW-materiality determinations"}

    clusters = _cluster(dets)
    proposed = 0
    for cluster in clusters:
        if _propose_bundle(cluster, project=project):
            proposed += 1

    return {
        "processed": len(dets),
        "clusters_found": len(clusters),
        "bundles_proposed": proposed,
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
