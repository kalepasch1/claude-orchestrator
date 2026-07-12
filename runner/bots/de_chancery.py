#!/usr/bin/env python3
"""
de_chancery.py - Delaware Court of Chancery reviewer bot.

Role: 'reviewer', target_app: 'apparently'
Corpus filter: Delaware Court of Chancery opinions
Priors tag: 'de_chancery'
Golden eval (>=5) scored on RFI-anticipation recall — does it raise the questions
the Court would?

This is the LEARNED version of the seeded recipient persona; the persona-learner
cron (queued in apparently) feeds it.

Usage:
    from runner.bots.de_chancery import build, admit, review, stats
"""
import os, sys, json, time, re

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import db
import model_gateway

ROLE = "reviewer"
TARGET_APP = "apparently"
PRIORS_TAG = "de_chancery"
MIN_GOLDEN_EVALS = 5
CORPUS_FILTER_RX = re.compile(
    r"delaware|chancery|court\s+of\s+chancery|del\.?\s*ch\.|c\.a\.\s+no\.",
    re.IGNORECASE,
)

MODEL = os.environ.get("DE_CHANCERY_MODEL", "claude-haiku-4-5-20251001")
PROVIDER = os.environ.get("DE_CHANCERY_PROVIDER", "claude")
MAX_PER_RUN = int(os.environ.get("DE_CHANCERY_MAX", "5"))

# RFI categories the Court typically raises
RFI_CATEGORIES = [
    "fiduciary_duty",
    "entire_fairness",
    "business_judgment",
    "disclosure_adequacy",
    "deal_process",
    "conflict_of_interest",
    "material_omission",
    "standing",
    "damages_remedy",
]

REVIEW_PROMPT = """You are a reviewer modeled on the Delaware Court of Chancery.
Your task: read the following document and anticipate what questions, concerns, or
Requests for Information (RFIs) a Chancery Court judge would raise.

Focus on: fiduciary duties, entire fairness, business judgment rule, disclosure
adequacy, deal process, conflicts of interest, material omissions, standing, and
remedies/damages.

Document:
{document}

Return JSON: {{"rfis": [{{"category": "...", "question": "...", "severity": "high|medium|low"}}], "overall_risk": "high|medium|low", "summary": "..."}}
"""


def corpus_filter(text):
    """Return True if text relates to Delaware Court of Chancery opinions."""
    return bool(CORPUS_FILTER_RX.search(text or ""))


def build(project=None):
    """Build/refresh the de_chancery persona from stored priors."""
    try:
        priors = db.query(
            "recipient_priors",
            filters={"tag": f"eq.{PRIORS_TAG}"},
            order="created_at.desc",
            limit=100,
        ) or []
    except Exception:
        priors = []
    return {
        "role": ROLE,
        "target_app": TARGET_APP,
        "priors_tag": PRIORS_TAG,
        "priors_count": len(priors),
        "built": True,
    }


def admit(document_text, project=None):
    """Check if a document should be admitted for de_chancery review."""
    if not document_text:
        return {"admitted": False, "reason": "empty document"}
    if not corpus_filter(document_text):
        return {"admitted": False, "reason": "not Delaware Chancery corpus"}
    return {"admitted": True, "reason": "matches Delaware Chancery corpus filter"}


def review(document_text, project=None):
    """Run the de_chancery reviewer on a document. Returns RFIs and risk assessment."""
    admission = admit(document_text, project=project)
    if not admission.get("admitted"):
        return {"reviewed": False, **admission}

    prompt = REVIEW_PROMPT.format(document=document_text[:3000])
    try:
        resp = model_gateway.complete(PROVIDER, MODEL, prompt, project=project, timeout=30)
        text = resp.get("text", "") if isinstance(resp, dict) else str(resp)
    except Exception as e:
        text = json.dumps({"rfis": [], "overall_risk": "unknown", "summary": f"error: {e}"})

    return {"reviewed": True, "response": text}


def score_rfi_recall(predicted_rfis, golden_rfis):
    """Score RFI-anticipation recall against golden eval set.
    Both args are lists of dicts with 'category' keys.
    Returns recall ratio 0.0-1.0."""
    if not golden_rfis:
        return 1.0
    golden_cats = {r.get("category", "").lower() for r in golden_rfis}
    pred_cats = {r.get("category", "").lower() for r in predicted_rfis}
    if not golden_cats:
        return 1.0
    return len(golden_cats & pred_cats) / len(golden_cats)


def stats():
    """Return stats about the de_chancery bot."""
    try:
        priors = db.query(
            "recipient_priors",
            filters={"tag": f"eq.{PRIORS_TAG}"},
            limit=1000,
        ) or []
    except Exception:
        priors = []
    return {
        "role": ROLE,
        "target_app": TARGET_APP,
        "priors_tag": PRIORS_TAG,
        "priors_count": len(priors),
        "min_golden_evals": MIN_GOLDEN_EVALS,
        "rfi_categories": RFI_CATEGORIES,
    }


if __name__ == "__main__":
    print(json.dumps(stats(), indent=2))
