#!/usr/bin/env python3
"""
decision_engine.py - auto-draft artifacts when founders choose directives.

When a founder/operator picks "negotiate" or "file" (or other document-generating
directives), the decision_engine immediately generates a draft (counter-email,
term sheet, filing memo, etc.) at the cheapest capable model (Haiku) and attaches
it to the decision_processes row for one-tap review + send.

    python3 decision_engine.py                        # poll and process pending directives
    python3 decision_engine.py --test                 # run local unit tests
"""
import os, sys, json, time, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, claude_cli


DRAFT_MODEL = "claude-haiku-4-5-20251001"  # cheapest model for draft generation

DIRECTIVE_PROMPTS = {
    "negotiate": """Generate a professional counter-offer email based on this decision context:

{context}

Constraints:
- Keep it concise (2-3 paragraphs)
- Propose specific counter-terms (bold key numbers)
- Maintain a collaborative tone
- Address the other party by name if provided
- Sign off professionally

Output ONLY the email body (no "Subject:" line, no greeting placeholder).""",

    "file": """Generate a filing memo or submission document based on this decision context:

{context}

Constraints:
- Use formal business memo format (TO:, FROM:, DATE:, RE:)
- Include a brief executive summary
- List all required sections/fields for the filing
- Use clear section headers
- Keep technical terms defined inline

Output the complete memo ready for filing.""",

    "draft": """Generate a professional draft document based on this decision context:

{context}

Constraints:
- Structure with clear headers and sections
- Use professional business tone
- Include a brief executive summary at the top
- Make it ready for immediate review/send

Output ONLY the document body.""",

    "review": """Summarize the key decision points and next steps based on this context:

{context}

Constraints:
- Bullet-point summary of the decision
- Clear next steps (who does what by when)
- Open items / pending clarifications
- Risk flags if any

Output a concise review memo.""",

    "escalate": """Generate an escalation notice based on this decision context:

{context}

Constraints:
- Clear problem statement
- Timeline and severity
- Requested escalation path
- Key stakeholders who need notification
- Recommended next steps

Output a formal escalation notice.""",
}


def _infer_artifact_type(directive, context):
    """Guess the artifact type from directive and context."""
    if directive == "negotiate":
        return "counter-email"
    elif directive == "file":
        if "legal" in (context or "").lower() or "permit" in (context or "").lower():
            return "legal-filing"
        return "filing-memo"
    elif directive == "escalate":
        return "escalation-notice"
    elif directive == "review":
        return "review-memo"
    else:
        return "document"


def generate_draft(directive, context, approval_id=None):
    """
    Generate a draft artifact for the given directive.

    Args:
        directive (str): One of negotiate|file|draft|review|escalate
        context (str or dict): Full decision context (parties, terms, etc.)
        approval_id (str): Optional reference to the originating approval

    Returns:
        {
            "draft": "<generated text>",
            "model": "claude-haiku-4-5-20251001",
            "input_tokens": N,
            "output_tokens": N,
            "cost_usd": X.XXXX,
            "artifact_type": "counter-email|filing-memo|..."
        }
    """
    directive = (directive or "").lower().strip()
    if directive not in DIRECTIVE_PROMPTS:
        raise ValueError(f"Unknown directive: {directive}. Must be one of {list(DIRECTIVE_PROMPTS.keys())}")

    if isinstance(context, dict):
        context = json.dumps(context, indent=2)

    prompt = DIRECTIVE_PROMPTS[directive].replace("{context}", context or "(no context provided)")
    artifact_type = _infer_artifact_type(directive, context)

    r = claude_cli.run(prompt, DRAFT_MODEL, permission=None, max_turns=1, timeout=120)

    return {
        "draft": r.get("text", ""),
        "model": DRAFT_MODEL,
        "input_tokens": r.get("input_tokens", 0),
        "output_tokens": r.get("output_tokens", 0),
        "cost_usd": r.get("cost_usd", 0),
        "artifact_type": artifact_type,
        "raw": r.get("raw")
    }


def store_decision(project, directive, context, approval_id=None, draft_data=None):
    """
    Create or update a decision_processes row and optionally generate + attach a draft.

    Args:
        project (str): Project name
        directive (str): One of negotiate|file|draft|review|escalate
        context (dict or str): Decision context
        approval_id (str): Optional reference to originating approval
        draft_data (dict): Pre-generated draft data (optional; auto-generate if None)

    Returns:
        decision_processes row dict
    """
    if isinstance(context, str):
        ctx_dict = {"_raw": context}
    else:
        ctx_dict = context or {}

    title = f"{directive.capitalize()} decision"
    if "title" in ctx_dict:
        title = ctx_dict["title"]
    elif "parties" in ctx_dict:
        title = f"{directive.capitalize()} - {ctx_dict['parties']}"

    row = {
        "project": project,
        "approval_id": approval_id,
        "title": title,
        "directive": directive,
        "context": json.dumps(ctx_dict) if not isinstance(ctx_dict, str) else ctx_dict,
        "status": "draft"
    }

    if draft_data is None:
        draft_data = generate_draft(directive, context, approval_id)

    row["draft"] = draft_data.get("draft", "")
    row["draft_model"] = draft_data.get("model")
    row["draft_tokens_in"] = draft_data.get("input_tokens", 0)
    row["draft_tokens_out"] = draft_data.get("output_tokens", 0)
    row["draft_cost_usd"] = draft_data.get("cost_usd", 0)

    result = db.insert("decision_processes", row)
    return result[0] if result else None


def poll_pending():
    """
    Poll for approvals with pending directives and auto-generate drafts.
    Called periodically by the runner to process new decisions.

    Returns:
        list of created decision_processes rows
    """
    # Query approvals with directive in the command or detail field
    approvals = db.select("approvals", {"select": "*", "status": "eq.approved"}) or []
    created = []

    for a in approvals:
        # Skip if already processed
        existing = db.select("decision_processes", {"approval_id": f"eq.{a['id']}"}) or []
        if existing:
            continue

        cmd = a.get("command", "").strip().lower()
        detail = a.get("detail", "").strip()

        directive = None
        for d in list(DIRECTIVE_PROMPTS.keys()):
            if cmd.startswith(d) or f"--{d}" in cmd:
                directive = d
                break

        if not directive:
            continue

        try:
            ctx = {"approval_id": a["id"], "title": a.get("title", ""), "detail": detail}
            row = store_decision(a["project"], directive, ctx, approval_id=a["id"])
            if row:
                created.append(row)
        except Exception as e:
            print(f"[decision_engine] failed to create decision for approval {a['id']}: {e}")

    return created


if __name__ == "__main__":
    import sys
    if "--test" in sys.argv:
        # Run local tests (don't need DB)
        print("Testing directive prompts...")
        for d, prompt in DIRECTIVE_PROMPTS.items():
            assert "{context}" in prompt, f"{d} prompt missing {{context}}"
            print(f"  ✓ {d}")

        print("Testing artifact type inference...")
        assert _infer_artifact_type("negotiate", "") == "counter-email"
        assert _infer_artifact_type("file", "") == "filing-memo"
        print("  ✓ all types")

        print("\nLocal tests passed. Use 'python3 runner.py' to run the orchestrator.")
    else:
        # Poll for pending directives
        print("[decision_engine] polling pending directives...")
        try:
            created = poll_pending()
            print(f"[decision_engine] created {len(created)} decision(s)")
        except Exception as e:
            print(f"[decision_engine] poll failed: {e}")
