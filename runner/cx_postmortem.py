#!/usr/bin/env python3
"""
cx_postmortem.py — Post-mortem workflow support for vindicated dissents.

For each determination where dissent_vindicated became True, drafts a structured
review checklist (what the majority missed, which domain raised the concern) and
stores it as an inbox item (kind='postmortem') for human review.

Also appends a one-line red-team heuristic to the cx_redteam_patterns controls
key so the pre-mortem step can surface the same class of miss in future panels.

WORKFLOW SUPPORT ONLY — this module does not make recommendations, eligibility
decisions, or take regulated action. All output is flagged for licensed-professional
or owner review before any action is taken.
"""
import os, sys, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

PATTERNS_KEY = "cx_redteam_patterns"
DONE_KEY = "cx_postmortem_done"
MAX_BATCH = 50


def _load_store(key, default):
    try:
        rows = db.select("controls", {"select": "value", "key": f"eq.{key}"})
        if rows and rows[0].get("value"):
            v = rows[0]["value"]
            return json.loads(v) if isinstance(v, str) else v
    except Exception:
        pass
    return default


def _save_store(key, value):
    try:
        db.upsert("controls", {"key": key, "value": json.dumps(value, default=str)})
    except Exception:
        pass


def _complete(prompt):
    try:
        import model_policy, model_gateway
        prov, model, _ = model_policy.choose("review", agentic=False, need=5)
        r = model_gateway.complete(prov, model, prompt)
        return (r.get("text") or "").strip()
    except Exception:
        return ""


def _heuristic(title, recommendation, dissent):
    """Generate a one-line red-team observation heuristic from a vindicated dissent."""
    txt = _complete(
        "You are a red-team heuristic writer. A committee majority approved a proposal that later failed; "
        "the minority dissent turned out to be correct. Write ONE short observation heuristic (≤15 words) "
        "capturing what pattern a future red-team should watch for. Phrased as a neutral observation rule, "
        "not a decision or recommendation. Return only the heuristic text, no quotes, no explanation.\n"
        f"PROPOSAL: {(title or '')[:150]}\n"
        f"MAJORITY VIEW: {(recommendation or '')[:150]}\n"
        f"DISSENT (vindicated): {(dissent or '')[:300]}"
    )
    if txt and len(txt) < 200:
        return txt
    words = re.findall(r"[A-Za-z]{4,}", dissent or "")[:8]
    return ("When " + " ".join(words[:4]) + ", apply extra scrutiny") if words else \
        "Flag minority dissent when outcome stakes are high"


def _dissent_domain(d, opinions):
    """Identify which committee's dissent most closely matches the determination's minority view."""
    dissent = (d.get("dissent") or "").lower()
    if not dissent:
        return "minority view"
    key_words = set(re.findall(r"[a-z]{4,}", dissent))
    best, best_score = "minority view", 0
    for op in opinions:
        op_words = set(re.findall(r"[a-z]{4,}", (op.get("dissent") or "").lower()))
        score = len(key_words & op_words)
        if score > best_score:
            best, best_score = (op.get("committee") or "minority view"), score
    return best


def _postmortem_body(d, opinions):
    """Build a structured review checklist. Workflow support only — not a recommendation."""
    title = d.get("title") or ""
    recommendation = d.get("recommendation") or ""
    dissent = d.get("dissent") or "not recorded"
    domain = _dissent_domain(d, opinions)

    lines = [
        "POST-MORTEM REVIEW CHECKLIST",
        "For human review only. This draft is not a recommendation or decision.",
        "",
        f"MATTER: {title}",
        f"MAJORITY CONCLUSION: {recommendation}",
        f"DISSENTING VIEW ({domain}): {dissent}",
        "",
        "REVIEW QUESTIONS (complete with team or licensed advisor before closing):",
        "1. Which specific signals in the dissent were most predictive of the outcome?",
        "2. Was the dissenting domain's concern adequately addressed before approval?",
        "3. What process change would ensure this class of concern is escalated earlier?",
        "4. Does this pattern match existing red-team heuristics in the patterns library?",
        "",
        "RISK LABEL: dissent-vindicated — outcome contradicted the majority view.",
        "ACTION REQUIRED: owner or licensed professional review before marking resolved.",
    ]
    return "\n".join(lines)


def run():
    """For each determination where dissent_vindicated=True, file a postmortem inbox item
    and record a red-team heuristic in the patterns store. Idempotent: skips already-processed IDs."""
    patterns = _load_store(PATTERNS_KEY, [])
    done = set(_load_store(DONE_KEY, []))

    dets = db.select("determinations", {
        "select": "id,subject_type,subject_id,title,recommendation,dissent",
        "dissent_vindicated": "eq.true",
        "limit": str(MAX_BATCH),
    }) or []

    n = 0
    for d in dets:
        det_id = d.get("id")
        if not det_id or str(det_id) in done:
            continue

        opinions = []
        subject_id = d.get("subject_id")
        if subject_id:
            opinions = db.select("committee_opinions", {
                "select": "committee,dissent",
                "subject_id": f"eq.{subject_id}",
                "limit": "20",
            }) or []

        body = _postmortem_body(d, opinions)
        heuristic = _heuristic(d.get("title"), d.get("recommendation"), d.get("dissent"))

        try:
            db.insert("inbox", {
                "kind": "postmortem",
                "title": f"Post-mortem: {(d.get('title') or 'determination')[:150]}",
                "body": body,
                "status": "unread",
            })
        except Exception:
            pass

        if heuristic and heuristic not in patterns:
            patterns.append(heuristic)
            patterns = patterns[-100:]

        done.add(str(det_id))
        n += 1

    if n:
        _save_store(PATTERNS_KEY, patterns)
        _save_store(DONE_KEY, list(done))

    print(f"cx_postmortem.run: {n} post-mortems filed")
    return n
