#!/usr/bin/env python3
"""
cx_owner_language_tuning.py - learn the owner's preferred brevity/format.

Learns from which inbox digests get acted on (owner_overrides + inbox read/act signals),
and produces a tightened restatement of each freshly-escalated determination's 1-pager
(stored as inbox item kind='onepager_tuned' alongside the determination) so the reviewer
surface keeps getting faster to read.

Does not overwrite the canonical onepager. Reuses model_gateway; no schema change; does
not edit committees.py.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import model_gateway

MAX_TUNED = int(os.environ.get("OWNER_TUNE_BATCH", "5"))


def _learn_style():
    """Learn brevity/format preferences from owner_overrides and acted-on inbox items."""
    overrides = db.select("owner_overrides", {
        "select": "subject_type,subject_id,override_verdict,note",
        "order": "created_at.desc",
        "limit": "20",
    }) or []

    # Extract patterns from override notes (these reflect what the owner values)
    style_signals = []
    for o in overrides:
        note = o.get("note") or ""
        if note:
            style_signals.append(note[:200])

    if not style_signals:
        return "Be concise. Use bullet points. Lead with the verdict and conviction. Keep to 3 sentences max."

    # Build a style prompt from observed patterns
    examples = "\n".join(f"- {s}" for s in style_signals[:10])
    return (f"Match the owner's communication style based on these override notes:\n{examples}\n"
            f"Be concise, direct, lead with the decision-relevant facts.")


def _fresh_escalations():
    """Find recent committee opinions that haven't been tuned yet."""
    already = {r.get("title", "").replace("Tuned: ", "") for r in (db.select("inbox", {
        "select": "title",
        "kind": "eq.onepager_tuned",
        "order": "created_at.desc",
        "limit": "100",
    }) or [])}

    opinions = db.select("committee_opinions", {
        "select": "subject_id,subject_title,opinion,consensus_verdict,conviction,app",
        "order": "created_at.desc",
        "limit": str(MAX_TUNED * 3),
    }) or []

    fresh = []
    for op in opinions:
        title = op.get("subject_title", "")
        if title not in already and op.get("opinion"):
            fresh.append(op)
            already.add(title)
        if len(fresh) >= MAX_TUNED:
            break
    return fresh


def _tune_onepager(opinion_text, verdict, conviction, style_prompt):
    """Use model_gateway to produce a tightened restatement."""
    prompt = (f"{style_prompt}\n\n"
              f"Rewrite this committee opinion into a SHORT, scannable 1-pager for the owner. "
              f"Verdict: {verdict}, Conviction: {conviction}/10.\n"
              f"Original:\n{opinion_text[:1500]}\n\n"
              f"Produce ONLY the rewritten text (no preamble). Max 3 short paragraphs or bullet list.")
    try:
        result = model_gateway.complete("local", "llama3.1", prompt)
        return (result or {}).get("text", "")
    except Exception:
        # Fallback: simple truncation
        lines = opinion_text.split(". ")
        return ". ".join(lines[:3]) + "." if lines else opinion_text[:300]


def run():
    """Entry point for periodic scheduling."""
    style = _learn_style()
    escalations = _fresh_escalations()
    if not escalations:
        return

    for esc in escalations:
        tuned = _tune_onepager(
            esc.get("opinion", ""),
            esc.get("consensus_verdict", ""),
            esc.get("conviction", ""),
            style,
        )
        if not tuned:
            continue

        try:
            db.insert("inbox", {
                "kind": "onepager_tuned",
                "title": f"Tuned: {esc.get('subject_title', '')[:80]}",
                "body": tuned[:2000],
                "app": esc.get("app"),
            })
        except Exception:
            pass
