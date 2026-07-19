"""
cx_provider_divergence.py — cade-extras module that re-asks recent high-materiality
determinations across two different providers to surface model-specific blind spots.

When two providers disagree on the same question, it inserts an inbox note
(kind='provider_divergence') so the team can investigate before shipping.
"""
import os, sys, logging, json, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger(__name__)

# Max determinations to re-check per run (cost-safe on subscription models)
MAX_CHECKS_PER_RUN = int(os.environ.get("CX_DIVERGENCE_MAX_CHECKS", "2"))


def _get_recent_determinations(limit=5):
    """Fetch recent high-materiality determinations from the DB."""
    import db
    rows = db.select("determinations", {
        "select": "id,question,answer,model,materiality,project_id,created_at",
        "materiality": "eq.high",
        "order": "created_at.desc",
        "limit": str(limit),
    }) or []
    return rows


def _pick_alternate_provider(original_model):
    """Pick a different provider for cross-checking."""
    m = str(original_model or "").lower()
    # Map provider families to alternatives
    if "claude" in m or "anthropic" in m:
        return "deepseek:deepseek-chat"
    if "deepseek" in m:
        return "openai:gpt-4o-mini"
    if "openai" in m or "gpt" in m:
        return "deepseek:deepseek-chat"
    if "gemini" in m or "google" in m:
        return "deepseek:deepseek-chat"
    # Default fallback
    return "deepseek:deepseek-chat"


def _ask_provider(question, model):
    """Ask a model the same question via model_gateway."""
    try:
        import model_gateway
        result = model_gateway.complete(
            prompt=question,
            model=model,
            max_tokens=500,
            temperature=0.0,
        )
        return str(result or "").strip()
    except Exception as e:
        log.warning("cx_provider_divergence: model_gateway.complete failed for %s: %s", model, e)
        return None


def _verdicts_diverge(answer_a, answer_b):
    """Check if two answers meaningfully diverge.

    Simple heuristic: if the first substantive word (yes/no/approve/deny/pass/fail)
    differs, they diverge. Also diverges if one is empty.
    """
    if not answer_a or not answer_b:
        return True

    def _extract_verdict(text):
        text = text.lower().strip()
        for keyword in ("yes", "no", "approve", "deny", "pass", "fail",
                        "accept", "reject", "compliant", "non-compliant",
                        "material", "immaterial", "high", "low", "medium"):
            if keyword in text[:100]:
                return keyword
        return text[:50]

    return _extract_verdict(answer_a) != _extract_verdict(answer_b)


def _insert_divergence_note(determination, original_answer, alt_model, alt_answer):
    """Insert an inbox note flagging the divergence."""
    import db
    note_body = json.dumps({
        "determination_id": determination.get("id"),
        "question_preview": str(determination.get("question") or "")[:200],
        "original_model": determination.get("model"),
        "original_verdict": str(original_answer)[:200],
        "alternate_model": alt_model,
        "alternate_verdict": str(alt_answer)[:200],
    }, indent=2)
    try:
        db.insert("inbox", {
            "kind": "provider_divergence",
            "project_id": determination.get("project_id"),
            "subject": f"Provider divergence on determination {determination.get('id', '?')[:8]}",
            "body": note_body,
        })
        log.info("cx_provider_divergence: flagged divergence for determination %s", determination.get("id"))
    except Exception as e:
        log.warning("cx_provider_divergence: failed to insert inbox note: %s", e)


def run():
    """Main entry point for cade_extras runner integration."""
    try:
        determinations = _get_recent_determinations(limit=MAX_CHECKS_PER_RUN * 2)
    except Exception as e:
        log.info("cx_provider_divergence: could not fetch determinations (table may not exist): %s", e)
        return

    checked = 0
    divergences = 0

    for det in determinations:
        if checked >= MAX_CHECKS_PER_RUN:
            break

        original_model = det.get("model")
        original_answer = det.get("answer")
        question = det.get("question")

        if not question or not original_model:
            continue

        alt_model = _pick_alternate_provider(original_model)
        alt_answer = _ask_provider(question, alt_model)
        checked += 1

        if alt_answer and _verdicts_diverge(original_answer, alt_answer):
            _insert_divergence_note(det, original_answer, alt_model, alt_answer)
            divergences += 1

    log.info("cx_provider_divergence: checked %d, divergences %d", checked, divergences)
    return checked, divergences
