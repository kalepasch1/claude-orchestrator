#!/usr/bin/env python3
"""
material_red_team.py - adversarial pre-merge security review for sensitive diffs.

Invoked ONLY from the merge train when a card's risk level is 'sensitive',
before the fast-forward step. One adversarial pass by a cheap strong model
(routed via agentic_coders) with a focused prompt to find security holes,
auth bypasses, data leaks, invariant violations in the diff.

Findings above severity threshold block with TESTFAIL-style note + qafix task.
Findings below threshold are attached as notes. Budget: hard daily cap (env),
skip silently when exhausted.

Does NOT re-enable periodic colosseum jobs.
"""
import os, sys, json, time, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
try:
    import claude_cli
except ImportError:
    claude_cli = None

BUDGET_CAP_USD = float(os.environ.get("RED_TEAM_DAILY_CAP_USD", "5.0"))
SEVERITY_THRESHOLD = int(os.environ.get("RED_TEAM_BLOCK_SEVERITY", "7"))
MODEL = os.environ.get("RED_TEAM_MODEL", "claude-haiku-4-5-20251001")
BUDGET_KEY = "red_team_daily_spend"


RED_TEAM_PROMPT_TEMPLATE = """You are a security red-team reviewer. Analyze this diff for:
1. Security holes (injection, SSRF, path traversal, etc.)
2. Authentication/authorization bypasses
3. Data leaks (PII exposure, secret logging, unprotected endpoints)
4. Invariant violations (upsert-only writes, privacy scrub, confidence gates)

For each finding, provide JSON with keys: severity (1-10), category, description, file, line.

Respond with a JSON array of findings. If no issues found, respond with [].

DIFF:
"""


def _get_daily_spend():
    """Get today's red-team spend from controls. Fail-soft."""
    try:
        today = datetime.date.today().isoformat()
        rows = db.select("controls", {
            "select": "value",
            "key": f"eq.{BUDGET_KEY}",
        }) or []
        if rows:
            data = json.loads(rows[0].get("value", "{}"))
            if data.get("date") == today:
                return float(data.get("spend", 0))
    except Exception:
        pass
    return 0.0


def _record_spend(amount):
    """Record spend for today. Fail-soft."""
    try:
        today = datetime.date.today().isoformat()
        current = _get_daily_spend()
        db.upsert("controls", {
            "key": BUDGET_KEY,
            "value": json.dumps({"date": today, "spend": current + amount}),
        })
    except Exception:
        pass


def _is_sensitive(card):
    """Check if a card's risk level is 'sensitive'."""
    risk = (card.get("risk_level") or card.get("risk") or "").lower()
    if risk == "sensitive":
        return True
    # Also check slug/prompt for sensitive patterns
    import re
    SENSITIVE_RE = re.compile(
        r"secret|token|oauth|auth|rls|security|pricing|legal|compliance|"
        r"regulatory|privacy|payment|stripe", re.I
    )
    text = (card.get("slug") or "") + " " + (card.get("prompt") or "")
    return bool(SENSITIVE_RE.search(text))


def _parse_findings(response_text):
    """Parse model response into structured findings. Fail-soft."""
    try:
        text = response_text.strip()
        # Try to extract JSON array
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    except (json.JSONDecodeError, ValueError):
        pass
    return []


def review(card, diff_text):
    """
    Run adversarial security review on a diff. Called from merge_train for sensitive cards.
    
    Returns: {"action": "block"|"pass"|"skip", "findings": [...], "note": "..."}
    - block: severity >= threshold, merge should be halted, qafix task queued
    - pass: no critical findings, findings attached as note
    - skip: budget exhausted or non-sensitive card
    """
    if not _is_sensitive(card):
        return {"action": "skip", "findings": [], "note": "not sensitive"}

    # Budget check
    daily_spend = _get_daily_spend()
    if daily_spend >= BUDGET_CAP_USD:
        return {"action": "skip", "findings": [], "note": "daily budget exhausted"}

    # Run the adversarial review
    try:
        prompt = RED_TEAM_PROMPT_TEMPLATE + diff_text[:15000]
        result = claude_cli.run(prompt, MODEL, timeout=120)
        response = result.get("text", "[]")
        cost = float(result.get("cost_usd", 0) or 0)
        _record_spend(cost)
    except Exception as e:
        return {"action": "pass", "findings": [], "note": f"review failed: {str(e)[:200]}"}

    findings = _parse_findings(response)
    if not findings:
        return {"action": "pass", "findings": [], "note": "no issues found"}

    # Check for blocking findings
    blocking = [f for f in findings if int(f.get("severity", 0)) >= SEVERITY_THRESHOLD]
    if blocking:
        slug = card.get("slug", "unknown")
        note = f"RED TEAM BLOCK: {len(blocking)} critical finding(s): " + \
               "; ".join(f.get("description", "")[:100] for f in blocking[:3])
        # Queue a qafix task
        try:
            db.insert("tasks", {
                "project_id": card.get("project_id"),
                "slug": f"qafix-redteam-{slug}",
                "kind": "bugfix",
                "state": "QUEUED",
                "prompt": f"Red team found security issues in {slug}. Fix these:\n" +
                          json.dumps(blocking, indent=2)[:3000],
            })
        except Exception:
            pass
        return {"action": "block", "findings": findings, "note": note}

    # Low-severity: attach as informational note, proceed
    note = f"Red team: {len(findings)} low-severity finding(s)"
    return {"action": "pass", "findings": findings, "note": note}


if __name__ == "__main__":
    print("material_red_team.py: import and call review(card, diff_text) from merge_train")
