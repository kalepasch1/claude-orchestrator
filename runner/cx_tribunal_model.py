#!/usr/bin/env python3
"""
cx_tribunal_model.py - Audience-read forecaster for escalated determinations.

For recent escalated determinations, forecasts how the ACTUAL decision-maker
(owner / regulator / investor depending on subject_type + domain) would likely
react, and attaches a short "audience read" (inbox kind='tribunal') so drafted
outputs are tuned to who reads them.

Reuses model_gateway.complete + the determination's contributors/factions as context.
Bounded to a few per run. No schema change; does not edit committees.py.
"""
import os, sys, re, json, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MAX_PER_RUN = int(os.environ.get("ORCH_TRIBUNAL_LIMIT", "5") or 5)
LOOKBACK_DAYS = int(os.environ.get("ORCH_TRIBUNAL_LOOKBACK", "14") or 14)


def _complete(prompt, need=3):
    """Complete a prompt via model_gateway."""
    try:
        import model_policy, model_gateway
        prov, model, _ = model_policy.choose("review", agentic=False, need=need)
        r = model_gateway.complete(prov, model, prompt)
        return r.get("text") or ""
    except Exception:
        return ""


def _json_parse(text):
    """Extract a JSON object from text."""
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except Exception:
        return {}


def _audience_type(det):
    """Infer the actual decision-maker type from subject_type and domain."""
    st = (det.get("subject_type") or "").lower()
    domain = (det.get("domain") or det.get("committee") or "").lower()

    if any(k in st for k in ["regulation", "compliance", "legal"]):
        return "regulator"
    if any(k in st for k in ["investment", "fund", "portfolio", "financial"]):
        return "investor"
    if any(k in domain for k in ["regulatory", "compliance", "policy"]):
        return "regulator"
    if any(k in domain for k in ["investor", "capital", "fund"]):
        return "investor"
    return "owner"


def _recent_escalated():
    """Fetch recent escalated determinations without a tribunal audience read."""
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(days=LOOKBACK_DAYS)).isoformat()
    dets = db.select("determinations", {
        "select": "id,title,position,consensus_pct,materiality,confidence,"
                  "factions,dissent,subject_type,domain,committee",
        "created_at": f"gte.{cutoff}",
        "escalated": "eq.true",
        "order": "materiality.desc",
        "limit": str(MAX_PER_RUN * 3),
    }) or []
    if not dets:
        return []

    # Filter out those that already have a tribunal inbox entry
    have = set()
    try:
        existing = db.select("inbox", {
            "select": "ref_id",
            "kind": "eq.tribunal",
        }) or []
        have = {r["ref_id"] for r in existing if r.get("ref_id")}
    except Exception:
        pass
    return [d for d in dets if d["id"] not in have][:MAX_PER_RUN]


def _forecast_reaction(det, audience_type):
    """Use LLM to forecast how the decision-maker would react."""
    factions = det.get("factions") or "none recorded"
    dissent = det.get("dissent") or "none"
    prompt = (
        f"You are modeling how a {audience_type} would react to this determination.\n\n"
        f"Title: {det.get('title','')}\n"
        f"Position: {det.get('position','')}\n"
        f"Consensus: {det.get('consensus_pct','')}%\n"
        f"Materiality: {det.get('materiality','')}\n"
        f"Factions: {json.dumps(factions)[:500]}\n"
        f"Dissent: {json.dumps(dissent)[:300]}\n\n"
        f"As a {audience_type}, what would concern you most? What framing would "
        f"you find most credible? What would make you reject this?\n\n"
        "Return JSON: {\"likely_reaction\":\"...\",\"key_concern\":\"...\","
        "\"recommended_framing\":\"...\",\"rejection_risk\":\"low|medium|high\"}"
    )
    text = _complete(prompt, need=3)
    return _json_parse(text) if text else {}


def run():
    """Main entry point. Attach audience reads to recent escalated determinations."""
    dets = _recent_escalated()
    if not dets:
        print("cx_tribunal_model: no unprocessed escalated determinations found")
        return 0

    n = 0
    for det in dets:
        audience_type = _audience_type(det)
        forecast = _forecast_reaction(det, audience_type)
        if not forecast:
            continue

        # Build the audience-read note
        audience_read = (
            f"[Audience: {audience_type}] "
            f"Likely reaction: {forecast.get('likely_reaction', 'unknown')[:200]}. "
            f"Key concern: {forecast.get('key_concern', 'unknown')[:150]}. "
            f"Recommended framing: {forecast.get('recommended_framing', '')[:150]}. "
            f"Rejection risk: {forecast.get('rejection_risk', 'unknown')}."
        )

        # Insert as inbox kind='tribunal'
        try:
            db.insert("inbox", {
                "kind": "tribunal",
                "ref_id": det["id"],
                "subject": f"Audience read: {det.get('title', '')[:120]}",
                "body": audience_read[:1000],
                "meta": json.dumps({
                    "audience_type": audience_type,
                    "rejection_risk": forecast.get("rejection_risk", "unknown"),
                    "determination_id": det["id"],
                }),
            })
            n += 1
            print(f"cx_tribunal_model: attached {audience_type} read for '{det.get('title','')[:60]}'")
        except Exception as e:
            print(f"cx_tribunal_model: failed to insert tribunal read: {e}")

    print(f"cx_tribunal_model: processed {n}/{len(dets)} determinations")
    return n


if __name__ == "__main__":
    run()
