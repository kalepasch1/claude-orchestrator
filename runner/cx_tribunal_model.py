#!/usr/bin/env python3
"""
cx_tribunal_model.py - forecast how real decision-makers would react to escalated
determinations and attach an audience-read note so drafted outputs are tuned to
who actually reads them.

For each recent escalated determination, inspects subject_type + domain to infer
the likely audience (owner / regulator / investor), builds a short prompt with the
determination's contributors/factions as context, calls model_gateway.complete for
a brief "audience read", and writes the result as an inbox row (kind='tribunal')
or appends to the determination's rationale note.

Bounded: processes at most MAX_PER_RUN determinations per invocation.
Does not edit committees.py or change any schema.
"""
import os, sys, json, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import model_gateway

MAX_PER_RUN = int(os.environ.get("CX_TRIBUNAL_MAX", "5"))
MODEL = os.environ.get("CX_TRIBUNAL_MODEL", "claude-haiku-4-5-20251001")
PROVIDER = os.environ.get("CX_TRIBUNAL_PROVIDER", "claude")

# Map subject_type + domain hints to likely audience
AUDIENCE_MAP = {
    "legal": "regulator",
    "compliance": "regulator",
    "regulatory": "regulator",
    "financial": "investor",
    "investment": "investor",
    "funding": "investor",
    "cap_table": "investor",
}
DEFAULT_AUDIENCE = "owner"


def _infer_audience(det):
    """Infer who the real decision-maker is from subject_type and domain."""
    subject = str(det.get("subject_type") or "").lower()
    domain = str(det.get("domain") or "").lower()
    combined = subject + " " + domain
    for keyword, audience in AUDIENCE_MAP.items():
        if keyword in combined:
            return audience
    return DEFAULT_AUDIENCE


def _build_prompt(det, audience):
    """Build a short prompt asking the model to forecast the audience's reaction."""
    title = det.get("title") or det.get("slug") or "untitled"
    rationale = det.get("rationale") or det.get("note") or ""
    contributors = det.get("contributors") or det.get("factions") or []
    if isinstance(contributors, str):
        try:
            contributors = json.loads(contributors)
        except (json.JSONDecodeError, TypeError):
            contributors = [contributors]

    context_parts = [f"Determination: {title}"]
    if rationale:
        context_parts.append(f"Rationale: {rationale[:500]}")
    if contributors:
        context_parts.append(f"Contributors/factions: {json.dumps(contributors[:10])}")
    context = "\n".join(context_parts)

    return (
        f"You are forecasting how a {audience} would react to the following determination.\n"
        f"{context}\n\n"
        f"In 2-3 sentences, predict the {audience}'s likely reaction: what questions they'd "
        f"raise, what concerns they'd flag, and what framing would resonate. Be specific and "
        f"actionable. Return JSON: {{\"audience\":\"{audience}\",\"reaction\":\"...\","
        f"\"suggested_framing\":\"...\"}}"
    )


def _write_audience_read(det, audience, read_text, project=None):
    """Write the audience read as an inbox row kind='tribunal'."""
    try:
        db.insert("inbox", {
            "project": project or det.get("project") or "beethoven",
            "kind": "tribunal",
            "title": f"Audience read ({audience}): {(det.get('title') or det.get('slug') or '')[:80]}",
            "body": read_text[:2000],
            "source": "cx_tribunal_model",
            "ref_id": str(det.get("id") or ""),
            "created_at": "now()",
        })
    except Exception:
        pass  # fail-soft


def run(project=None):
    """Main entry point: process recent escalated determinations."""
    try:
        dets = db.query(
            "determinations",
            filters={"escalated": "eq.true"},
            order="created_at.desc",
            limit=MAX_PER_RUN,
        ) or []
    except Exception:
        dets = []

    if not dets:
        return {"processed": 0, "note": "no escalated determinations found"}

    results = []
    for det in dets[:MAX_PER_RUN]:
        audience = _infer_audience(det)
        prompt = _build_prompt(det, audience)
        try:
            resp = model_gateway.complete(PROVIDER, MODEL, prompt, project=project, timeout=30)
            read_text = resp.get("text", "") if isinstance(resp, dict) else str(resp)
        except Exception as e:
            read_text = f"[tribunal model error: {e}]"

        _write_audience_read(det, audience, read_text, project=project)
        results.append({
            "det_id": str(det.get("id", "")),
            "audience": audience,
            "read_len": len(read_text),
        })

    return {"processed": len(results), "results": results}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
