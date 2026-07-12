#!/usr/bin/env python3
"""
cx_tribunal_model.py - Tribunal Audience-Read Model.

For recent escalated determinations, forecast how the ACTUAL decision-maker
(owner / regulator / investor depending on subject_type + domain) would likely
react, and attach a short "audience read" (inbox kind='tribunal') so drafted
outputs are tuned to who reads them.

Reuses model_gateway.complete + the determination's contributors/factions as
context; bounded to a few per run. No schema change; does not edit committees.py.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import model_gateway

MAX_PER_RUN = int(os.environ.get("TRIBUNAL_BATCH", "5"))

# Map subject_type + domain to the likely actual decision-maker persona
AUDIENCE_MAP = {
    ("legal", None): "regulator or external counsel",
    ("legal", "ip"): "patent/trademark examiner or IP counsel",
    ("legal", "compliance"): "compliance officer or regulator",
    ("strategic", None): "owner / founder",
    ("strategic", "growth"): "owner focused on revenue and market share",
    ("strategic", "product"): "owner focused on product-market fit",
    ("financial", None): "investor or financial advisor",
    ("financial", "fundraising"): "potential investor doing due diligence",
    ("technical", None): "owner wearing the technical lead hat",
}


def _resolve_audience(subject_type, domain):
    """Determine who the actual decision-maker is for this determination."""
    st = (subject_type or "").lower().strip()
    dom = (domain or "").lower().strip() or None
    return (AUDIENCE_MAP.get((st, dom))
            or AUDIENCE_MAP.get((st, None))
            or "owner / founder")


def _recent_escalated():
    """Fetch recent committee opinions that lack a tribunal audience-read."""
    already = {r.get("title", "").replace("Tribunal: ", "")
               for r in (db.select("inbox", {
                   "select": "title",
                   "kind": "eq.tribunal",
                   "order": "created_at.desc",
                   "limit": "200",
               }) or [])}

    opinions = db.select("committee_opinions", {
        "select": "subject_id,subject_title,subject_type,opinion,"
                  "consensus_verdict,conviction,app,contributors",
        "order": "created_at.desc",
        "limit": str(MAX_PER_RUN * 3),
    }) or []

    fresh = []
    for op in opinions:
        title = op.get("subject_title") or ""
        if title and title not in already:
            fresh.append(op)
            already.add(title)
        if len(fresh) >= MAX_PER_RUN:
            break
    return fresh


def _build_audience_read(opinion, audience):
    """Use model_gateway to forecast how the audience would react."""
    subject = opinion.get("subject_title", "unknown")
    verdict = opinion.get("consensus_verdict", "")
    conviction = opinion.get("conviction", "")
    opinion_text = (opinion.get("opinion") or "")[:1500]
    contributors = opinion.get("contributors") or ""
    if isinstance(contributors, list):
        contributors = ", ".join(str(c) for c in contributors)
    elif isinstance(contributors, dict):
        contributors = json.dumps(contributors)

    prompt = (
        f"You are modeling the reaction of: {audience}.\n\n"
        f"A committee just made this determination:\n"
        f"Subject: {subject}\nVerdict: {verdict} (conviction {conviction}/10)\n"
        f"Contributors/factions: {str(contributors)[:500]}\n"
        f"Opinion:\n{opinion_text}\n\n"
        f"Forecast how this specific audience ({audience}) would likely react. "
        f"Consider: what they care about, what they'd push back on, what would "
        f"reassure them, and what framing/language would land best.\n\n"
        f"Respond in 2-3 short paragraphs. No preamble."
    )
    try:
        result = model_gateway.complete("local", "llama3.1", prompt)
        return (result or {}).get("text", "")
    except Exception:
        # Fail-soft: return a minimal static read
        try:
            conv = int(conviction or 0)
        except (ValueError, TypeError):
            conv = 0
        return (f"Audience ({audience}): likely focused on {verdict} verdict. "
                f"Conviction {conviction}/10 may {'reassure' if conv >= 7 else 'concern'} them.")


def run():
    """Entry point for periodic scheduling."""
    escalations = _recent_escalated()
    if not escalations:
        return

    for esc in escalations:
        subject_type = esc.get("subject_type") or ""
        domain = esc.get("app") or ""
        audience = _resolve_audience(subject_type, domain)

        audience_read = _build_audience_read(esc, audience)
        if not audience_read:
            continue

        title = esc.get("subject_title", "")[:80]
        try:
            db.insert("inbox", {
                "kind": "tribunal",
                "title": f"Tribunal: {title}",
                "body": audience_read[:2000],
                "app": esc.get("app"),
            })
        except Exception:
            pass
