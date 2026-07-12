#!/usr/bin/env python3
"""
cx_tribunal_model.py - Tribunal Audience Model.

For recent escalated determinations, forecast how the ACTUAL decision-maker (owner /
regulator / investor depending on subject_type + domain) would likely react, and attach
a short "audience read" (inbox kind='tribunal') so drafted outputs are tuned to who reads
them. Reuses model_gateway.complete + the determination's contributors/factions as context;
bounded to a few per run. No schema change; does not edit committees.py.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# Map subject_type/domain to the likely decision-maker audience
_AUDIENCE_MAP = {
    "legal": "regulator or outside counsel",
    "compliance": "regulator or compliance officer",
    "finance": "investor or CFO",
    "fundraise": "investor or board member",
    "investor": "investor or board member",
    "security": "CISO or security auditor",
    "product": "product owner or founder",
    "growth": "product owner or growth lead",
    "marketing": "product owner or marketing lead",
    "bizdev": "business development partner or founder",
    "risk": "risk committee or board member",
}

MAX_PER_RUN = int(os.environ.get("ORCH_TRIBUNAL_MAX_PER_RUN", "3"))


def _infer_audience(det):
    """Infer the real-world audience from subject_type, domain, and determination context."""
    subject_type = str(det.get("subject_type") or "").lower()
    title = str(det.get("title") or "").lower()
    # Check subject_type first
    for key, audience in _AUDIENCE_MAP.items():
        if key in subject_type:
            return audience
    # Fall back to title keywords
    for key, audience in _AUDIENCE_MAP.items():
        if key in title:
            return audience
    return "founder / product owner"


def _build_audience_read(det, audience):
    """Build a short audience-read note using the determination's context."""
    contributors = det.get("contributors") or "unknown panel"
    factions = det.get("factions") or ""
    recommendation = det.get("recommendation") or "N/A"
    dissent = det.get("dissent") or "none"
    title = det.get("title") or "untitled"
    consensus = det.get("consensus_pct")

    # Build the audience read without LLM call (fast path) — the prompt spec says
    # "reuse model_gateway.complete" but we degrade gracefully if it's unavailable
    try:
        import model_gateway as mg
        prompt = (
            f"You are a communications advisor. In 2-3 sentences, describe how a "
            f"{audience} would likely react to this determination and what tone/framing "
            f"adjustments would make the output more effective for that audience.\n\n"
            f"DETERMINATION: {title}\n"
            f"RECOMMENDATION: {recommendation}\n"
            f"CONSENSUS: {consensus}%\n"
            f"CONTRIBUTORS: {str(contributors)[:300]}\n"
            f"DISSENT: {str(dissent)[:200]}\n"
            f"FACTIONS: {str(factions)[:200]}"
        )
        result = mg.complete("claude", "claude-haiku-4-5-20251001", prompt,
                             timeout=30, task_class="review", record_op=False)
        audience_read = (result.get("text") or "").strip()
        if audience_read:
            return audience_read
    except Exception:
        pass

    # Fallback: static audience read
    tone = "cautious, evidence-heavy" if "legal" in audience or "regulator" in audience else "outcome-focused"
    return (
        f"Audience: {audience}. "
        f"This determination ({recommendation}) reached {consensus or '?'}% consensus. "
        f"Recommended framing: {tone}. "
        f"{'Note active dissent — address preemptively.' if dissent and dissent != 'none' else ''}"
    )


def run():
    """Main entry point. Process recent escalated determinations."""
    # Get recent escalated determinations that haven't been audience-modeled yet
    escalated = db.select("determinations", {
        "select": "id,title,subject_type,subject_id,recommendation,consensus_pct,contributors,factions,dissent,created_at",
        "recommendation": "like.*ESCALATE*",
        "order": "created_at.desc",
        "limit": "20",
    }) or []

    if not escalated:
        # Also check high-materiality determinations
        escalated = db.select("determinations", {
            "select": "id,title,subject_type,subject_id,recommendation,consensus_pct,contributors,factions,dissent,created_at",
            "materiality": "eq.high",
            "order": "created_at.desc",
            "limit": "20",
        }) or []

    if not escalated:
        print("cx_tribunal_model: no escalated/high-materiality determinations found")
        return {"processed": 0}

    # Check which determinations already have tribunal reads
    existing = db.select("inbox", {
        "select": "title",
        "kind": "eq.tribunal",
        "order": "created_at.desc",
        "limit": "50",
    }) or []
    existing_titles = {(e.get("title") or "") for e in existing}

    n = 0
    for det in escalated:
        if n >= MAX_PER_RUN:
            break
        det_id = str(det.get("id") or "")
        marker = f"(det {det_id[:8]})"
        if any(marker in t for t in existing_titles):
            continue

        audience = _infer_audience(det)
        audience_read = _build_audience_read(det, audience)

        db.insert("inbox", {
            "kind": "tribunal",
            "title": f"Audience read: {det.get('title', '')[:80]} {marker}",
            "body": (
                f"AUDIENCE: {audience}\n"
                f"DETERMINATION: {det.get('recommendation', 'N/A')}\n\n"
                f"AUDIENCE READ:\n{audience_read}"
            )[:3000],
            "status": "unread",
        })
        n += 1

    print(f"cx_tribunal_model: processed {n} escalated determinations")
    return {"processed": n}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
