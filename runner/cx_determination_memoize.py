#!/usr/bin/env python3
"""
cx_determination_memoize.py - Determination Memoization / Semantic Cache.

Before a fresh determination is needed, check whether a MATERIALLY-similar prior
determination already exists (token overlap on title+body over the determinations table).
When a strong match is found on a low-materiality subject, record a reuse suggestion
(inbox kind='determination_reuse' citing the prior determination id + its proof_hash as
provenance) so the engine can skip re-litigating — never silently; always cite provenance
and re-check materiality. Cuts cost/latency at scale.

Read-only except the reuse digest; no schema change; does not edit committees.py.
"""
import os, sys, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def _tokenize(text):
    """Simple whitespace+punctuation tokenizer for overlap comparison."""
    if not text:
        return set()
    return set(re.findall(r'\w{3,}', str(text).lower()))


def _similarity(tokens_a, tokens_b):
    """Jaccard similarity between two token sets."""
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union) if union else 0.0


def _find_similar(det, prior_dets, threshold=0.55):
    """Find the best-matching prior determination above threshold."""
    det_tokens = _tokenize(det.get("title", "")) | _tokenize(det.get("recommendation", ""))
    best_match = None
    best_score = 0.0
    for prior in prior_dets:
        if str(prior.get("id")) == str(det.get("id")):
            continue
        prior_tokens = _tokenize(prior.get("title", "")) | _tokenize(prior.get("recommendation", ""))
        score = _similarity(det_tokens, prior_tokens)
        if score > best_score:
            best_score = score
            best_match = prior
    if best_score >= threshold:
        return best_match, best_score
    return None, 0.0


def run():
    """Main entry point. Scan recent determinations for reuse opportunities."""
    # Get recent determinations (last 30 days worth)
    recent = db.select("determinations", {
        "select": "id,title,recommendation,subject_type,subject_id,materiality,proof_hash,created_at",
        "order": "created_at.desc",
        "limit": "100",
    }) or []
    if len(recent) < 2:
        print("cx_determination_memoize: insufficient determinations for memoization")
        return {"checked": 0, "reuse_suggestions": 0}

    # Check which determinations already have reuse suggestions
    existing_reuse = db.select("inbox", {
        "select": "title",
        "kind": "eq.determination_reuse",
        "status": "eq.unread",
    }) or []
    existing_ids = set()
    for er in existing_reuse:
        # Extract determination ID from existing reuse suggestions
        title = er.get("title") or ""
        for det in recent:
            if str(det.get("id", ""))[:8] in title:
                existing_ids.add(str(det.get("id")))

    # For each recent determination, look for similar priors
    # Only consider low-materiality subjects for auto-reuse
    n_checked = 0
    n_suggested = 0
    max_suggestions = int(os.environ.get("ORCH_MEMOIZE_MAX_SUGGESTIONS", "3"))

    for i, det in enumerate(recent[:20]):
        if n_suggested >= max_suggestions:
            break
        det_id = str(det.get("id") or "")
        if det_id in existing_ids:
            continue

        materiality = det.get("materiality")
        # Only auto-suggest reuse for low-materiality determinations
        if materiality and str(materiality).lower() in ("high", "critical"):
            continue

        # Compare against older determinations (not including self or newer)
        priors = recent[i + 1:]
        match, score = _find_similar(det, priors)
        if not match:
            continue

        n_checked += 1
        match_id = match.get("id")
        proof_hash = match.get("proof_hash") or "none"

        db.insert("inbox", {
            "kind": "determination_reuse",
            "title": f"Reuse candidate: {det.get('title', '')[:80]} (det {det_id[:8]})",
            "body": (
                f"A materially-similar prior determination exists.\n\n"
                f"NEW: {det.get('title', '')}\n"
                f"PRIOR: {match.get('title', '')} (id: {match_id})\n"
                f"Similarity: {score:.0%}\n"
                f"Prior proof_hash: {proof_hash}\n\n"
                f"The prior determination's recommendation was: {match.get('recommendation', 'N/A')}\n"
                f"Consider reusing rather than re-litigating. Always verify materiality "
                f"has not changed before accepting."
            )[:3000],
            "status": "unread",
        })
        n_suggested += 1

    print(f"cx_determination_memoize: checked {n_checked}, suggested {n_suggested} reuses")
    return {"checked": n_checked, "reuse_suggestions": n_suggested}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
