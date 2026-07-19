#!/usr/bin/env python3
"""Review-first editorial production for Kale Pasch and the product portfolio.

The worker converts due cadence entries into a substantive draft packet in the
shared approval queue.  It never posts, submits, emails, or changes public
content.  A human must approve a packet before its content can be published.
"""
import calendar as calendar_lib
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

PROGRAM_APPS = {
    "kale-pasch", "tomorrow", "smarter", "apparently", "vigil", "pareto-2080",
    "racefeed", "hisanta", "sustainable-barks", "madeus",
}

APP_LABELS = {
    "kale-pasch": "Kale Pasch", "smarter": "Smrter", "pareto-2080": "Pareto",
    "racefeed": "Galop",
}


def _label(app):
    return APP_LABELS.get(app, app.replace("-", " ").title())


def _next_due(now, cadence):
    if cadence == "daily":
        return now + dt.timedelta(days=1)
    if cadence == "biweekly":
        return now + dt.timedelta(days=14)
    if cadence == "monthly":
        year = now.year + (now.month == 12)
        month = 1 if now.month == 12 else now.month + 1
        return now.replace(year=year, month=month, day=min(now.day, calendar_lib.monthrange(year, month)[1]))
    if cadence == "quarterly":
        return now + dt.timedelta(days=91)
    return now + dt.timedelta(days=7)


def _first_briefing_due(now):
    """The requested first Pasch Briefing is August 1; thereafter monthly."""
    august_first = dt.datetime(now.year, 8, 1, 14, tzinfo=dt.timezone.utc)
    if now <= august_first:
        return august_first
    year = now.year + (now.month == 12)
    month = 1 if now.month == 12 else now.month + 1
    return dt.datetime(year, month, 1, 14, tzinfo=dt.timezone.utc)


def _bootstrap_calendar(now):
    """Self-heal the cadence if migration history is divergent or a row is removed."""
    seed = [
        ("kale-pasch", "medium", "article", "weekly", "Event markets, derivatives, and market integrity", now),
        ("kale-pasch", "newsletter", "newsletter", "monthly", "Pasch Briefing: field note, working framework, and build update", _first_briefing_due(now)),
        ("kale-pasch", "site", "flagship_guide", "quarterly", "Event markets, derivatives, and market integrity", now),
        ("kale-pasch", "site", "flagship_guide", "quarterly", "Digital assets and the financial-product perimeter", now + dt.timedelta(days=21)),
        ("kale-pasch", "site", "flagship_guide", "quarterly", "Gaming mechanics and the legal design review", now + dt.timedelta(days=42)),
        ("kale-pasch", "site", "flagship_guide", "quarterly", "The regulated-product launch map", now + dt.timedelta(days=63)),
        ("kale-pasch", "site", "flagship_guide", "quarterly", "AI, evidence, and accountable professional judgment", now + dt.timedelta(days=84)),
        ("tomorrow", "medium", "article", "monthly", "Event-driven risk, bespoke hedging, and market structure", now + dt.timedelta(days=7)),
        ("smarter", "linkedin", "post", "weekly", "Evidence-first AI and accountable legal operations", now + dt.timedelta(days=7)),
        ("apparently", "medium", "article", "monthly", "Compliance-native launch infrastructure", now + dt.timedelta(days=10)),
        ("vigil", "linkedin", "post", "weekly", "Governed intelligence and regulatory evidence", now + dt.timedelta(days=7)),
        ("pareto-2080", "medium", "article", "monthly", "Long-horizon decisions and personal-finance operating systems", now + dt.timedelta(days=14)),
        ("racefeed", "linkedin", "post", "weekly", "Responsible racing and interactive gaming design", now + dt.timedelta(days=10)),
        ("hisanta", "linkedin", "post", "weekly", "Family rituals, kindness, and responsible child-facing product design", now + dt.timedelta(days=10)),
        ("sustainable-barks", "medium", "article", "monthly", "Sustainability claims, hospitality, and pet products", now + dt.timedelta(days=14)),
        ("madeus", "linkedin", "post", "weekly", "Founder operations and agentic execution with human judgment", now + dt.timedelta(days=14)),
    ]
    rows = db.select("growth_content_calendar", {"select": "app,platform,kind,topic_hint"}) or []
    existing = {(r.get("app"), r.get("platform"), r.get("kind"), r.get("topic_hint")) for r in rows}
    created = 0
    for app, platform, kind, cadence, topic, due in seed:
        if (app, platform, kind, topic) in existing:
            continue
        db.insert("growth_content_calendar", {
            "app": app, "platform": platform, "kind": kind, "cadence": cadence,
            "per_period": 1, "topic_hint": topic, "next_due": due.isoformat(), "active": True,
            "meta": {"requires_human_approval": True, "draft_only": True, "program": "kale-pasch-editorial"},
        })
        created += 1
    return created


def _packet(entry):
    app = entry["app"]
    topic = entry.get("topic_hint") or "A current issue in regulated markets and technology"
    kind = entry.get("kind") or "article"
    platform = entry.get("platform") or "medium"
    headline = f"{_label(app)}: {topic}"
    source_plan = (
        "Use only primary and authoritative materials: applicable statutes and regulations; "
        "agency releases, rulebooks, filings, and court opinions; then clearly identify any "
        "assumptions or open questions. Do not use client, employer, or non-public information."
    )
    return {
        "program": "Kale Pasch Editorial Program",
        "app": app,
        "platform": platform,
        "kind": kind,
        "working_title": headline,
        "reader": "Founders, market participants, legal peers, journalists, and prospective clients",
        "objective": "Build durable authority through clear, source-led analysis; educate rather than promote.",
        "outline": [
            "The real decision or operating problem.",
            "The governing market and legal context, supported by primary sources.",
            "A practical framework for evaluating the issue.",
            "What remains uncertain and what a disciplined next step looks like.",
        ],
        "source_policy": source_plan,
        "publication_rule": "Human approval is required before any publication, outreach, application, or external send.",
    }


def _generated_draft(packet):
    """Use the existing routed model gateway when it is available; otherwise stage a
    complete editorial packet.  The fallback is deliberate: no missing credential
    can stop the review queue or trigger an external action."""
    prompt = f"""You are preparing a review-only editorial draft for {packet['working_title']}.
Audience: {packet['reader']}.
Objective: {packet['objective']}
Write a rigorous, restrained draft for {packet['platform']} ({packet['kind']}).
No legal advice, no client facts, no claims about outcomes, no hype, and no invented sources.
Make explicit where primary-source verification is still required.
Return: a 120-word executive summary, 5-section outline, 5 primary-source research targets,
and a 700-900 word first draft. This is for human review only, never for direct publication."""
    # The deterministic packet is always available.  Model expansion is opt-in
    # so a provider outage can never stall the cadence or suppress a review item.
    if os.environ.get("EDITORIAL_MODEL_ENABLED", "false").lower() not in ("1", "true", "yes", "on"):
        return _fallback_draft(packet), "outline_ready"
    try:
        import model_policy, model_gateway
        provider, model, _ = model_policy.choose("plan", agentic=False, need=7)
        result = model_gateway.complete(provider, model, prompt)
        text = (result or {}).get("text") or ""
        if text.strip():
            return text[:12000], "generated"
    except Exception:
        pass
    return _fallback_draft(packet), "outline_ready"


def _fallback_draft(packet):
    fallback = [
        f"# {packet['working_title']}",
        "", "## Executive summary", packet["objective"],
        "", "## Working outline", *[f"{i + 1}. {part}" for i, part in enumerate(packet["outline"])],
        "", "## Research targets", "- Governing statute or regulation", "- Relevant agency or regulator release",
        "- Market rulebook, filing, or official data", "- Leading decision or adjudicatory material",
        "- Current source confirming the factual predicate", "", "## Review note", packet["source_policy"],
    ]
    return "\n".join(fallback)


def run(limit=20):
    now = dt.datetime.now(dt.timezone.utc)
    bootstrapped = _bootstrap_calendar(now)
    entries = db.select("growth_content_calendar", {
        "select": "id,app,platform,kind,cadence,per_period,topic_hint,next_due,meta",
        "active": "eq.true", "next_due": f"lte.{now.isoformat()}",
        "order": "next_due.asc", "limit": str(limit),
    }) or []
    made = 0
    for entry in entries:
        app = entry.get("app")
        if app not in PROGRAM_APPS:
            continue
        packet = _packet(entry)
        due_key = f"editorial:{entry['id']}:{str(entry.get('next_due') or '')[:10]}"
        existing = db.select("approvals", {"select": "id", "slug": f"eq.{due_key}", "limit": "1"}) or []
        if existing:
            continue
        draft, state = _generated_draft(packet)
        db.insert("approvals", {
            # This existing project mapping lets an approved guide turn into a
            # traceable Kalepasch site-update task through the normal decision flow.
            "project": "kalepasch-com",
            "slug": due_key,
            "kind": "material",
            "title": f"Review editorial draft — {_label(app)} — {entry.get('kind') or 'article'}",
            "why": f"Scheduled {entry.get('cadence') or 'weekly'} {entry.get('platform') or 'publication'} item: {packet['working_title']}",
            "value": "Creates a source-led, human-reviewed authority asset and a reusable research record.",
            "risk": "Draft only. Verify all sources and professional-responsibility constraints before publication.",
            "detail": json.dumps({"packet": packet, "draft_state": state, "draft": draft}),
            "alternatives": [
                {"label": "Review and refine", "recommended": True, "description": "Edit the draft and approve only the publication-ready version."},
                {"label": "Change angle", "description": "Keep the research packet and redirect the thesis."},
                {"label": "Defer", "description": "Keep the cadence but move this item to a later window."},
            ],
        })
        next_due = _next_due(now, entry.get("cadence") or "weekly")
        db.update("growth_content_calendar", {"id": entry["id"]}, {"next_due": next_due.isoformat()})
        made += 1
    print(f"editorial_program: bootstrapped {bootstrapped} cadence row(s); staged {made} review-only draft packet(s)")
    return made


if __name__ == "__main__":
    run()
