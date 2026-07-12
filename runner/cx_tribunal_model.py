#!/usr/bin/env python3
"""
cx_tribunal_model.py - Audience-read forecaster for escalated determinations.

For recent escalated determinations, forecasts how the ACTUAL decision-maker
(owner / regulator / investor depending on subject_type + domain) would likely
react, and attaches a short "audience read" so drafted outputs are tuned to
who reads them. Reuses model_gateway.complete and the determination's
contributors/factions as context. Bounded to a few per run.

Does NOT edit committees.py or change the schema.
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import model_gateway

MAX_PER_RUN = int(os.environ.get("CX_TRIBUNAL_MAX_PER_RUN", "5"))


AUDIENCE_MAP = {
    "owner": "the business owner / founder who prioritizes ROI, speed, and competitive advantage",
    "regulator": "a regulatory body focused on compliance, consumer protection, and legal risk",
    "investor": "an investor focused on growth metrics, unit economics, and market positioning",
}

TRIBUNAL_PROMPT = """You are modeling how a specific decision-maker would react to this determination.

Decision-maker type: {audience_type}
Audience profile: {audience_profile}

The determination was made by these contributors/factions:
{factions}

Determination summary:
{determination}

Predict the decision-maker's likely reaction in ONE JSON object:
{{"reaction":"supportive|cautious|resistant|hostile",
  "concerns":["top concern 1","top concern 2"],
  "language_cues":"tone/framing adjustments to land well with this reader (1 sentence)",
  "risk_of_rejection":0.0-1.0,
  "suggested_framing":"how to present this determination to maximize acceptance (1-2 sentences)"}}"""


def _detect_audience(subject_type, domain):
    """Map subject_type + domain to the likely actual decision-maker."""
    st = (subject_type or "").lower()
    dom = (domain or "").lower()
    if any(k in st or k in dom for k in ("regulat", "compliance", "legal", "license")):
        return "regulator"
    if any(k in st or k in dom for k in ("invest", "fund", "capital", "financ")):
        return "investor"
    return "owner"


def _get_factions_text(det):
    """Extract contributors/factions context from a determination row."""
    parts = []
    for key in ("contributors", "factions", "rationale"):
        val = det.get(key)
        if val:
            parts.append(f"{key}: {json.dumps(val) if isinstance(val, (dict, list)) else str(val)}")
    return "\n".join(parts) or "(no faction data)"


def _build_audience_read(det, provider="local", model=None):
    """Generate an audience-read forecast for a single determination."""
    subject_type = det.get("subject_type", "")
    domain = det.get("domain", "")
    audience_key = _detect_audience(subject_type, domain)
    audience_profile = AUDIENCE_MAP.get(audience_key, AUDIENCE_MAP["owner"])

    prompt = TRIBUNAL_PROMPT.format(
        audience_type=audience_key,
        audience_profile=audience_profile,
        factions=_get_factions_text(det),
        determination=det.get("summary") or det.get("title") or str(det.get("id", "")),
    )

    model = model or os.environ.get("CX_TRIBUNAL_MODEL", "llama3.2:3b")
    try:
        result = model_gateway.complete(provider, model, prompt)
        text = result.get("text", "")
        # Try to parse JSON from the response
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            parsed = {"raw": text[:500]}
        parsed["audience_type"] = audience_key
        return parsed
    except Exception as e:
        return {"audience_type": audience_key, "error": str(e)[:200]}


def run():
    """Main entry point: fetch recent escalated determinations, attach audience reads."""
    try:
        rows = db.query("committee_opinions", params={
            "select": "id,subject_type,domain,summary,title,contributors,factions,rationale",
            "verdict": "eq.escalate",
            "order": "created_at.desc",
            "limit": str(MAX_PER_RUN),
        })
    except Exception:
        # Table may not exist yet or query may fail; fail soft
        rows = []

    if not rows:
        return {"processed": 0, "note": "no escalated determinations found"}

    processed = 0
    for det in rows[:MAX_PER_RUN]:
        audience_read = _build_audience_read(det)
        # Attach as advisory metadata via note update (no schema change)
        note_payload = json.dumps({"tribunal_audience_read": audience_read})
        try:
            db.update("committee_opinions", det["id"], {
                "note": note_payload,
            })
            processed += 1
        except Exception:
            pass  # fail soft per item

    return {"processed": processed, "total_candidates": len(rows)}


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2))
