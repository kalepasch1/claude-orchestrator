#!/usr/bin/env python3
"""
confidence.py - CONFIDENCE-GATED AUTONOMY. A cheap model scores how safe a diff is to
auto-merge (0-1). High confidence -> auto-integrate; low -> route to a human approval.
Also flags HIGH-RISK diffs (auth/payment/migration/secret paths) that should require
two-key approval. Autonomy that flexes with risk instead of fixed rules.
"""
import os, sys, subprocess, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claude_cli

MODEL = os.environ.get("CONFIDENCE_MODEL", "claude-haiku-4-5-20251001")
THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.8"))
# The money/auth/schema backstop: any diff matching this ALWAYS routes to two-key approval,
# independent of the confidence threshold. Widened so lowering thresholds for low-risk work
# can't let a sensitive change merge automatically.
HIGH_RISK = re.compile(
    r"(auth|oauth|sso|login|session|password|secret|token|credential|api[_-]?key|"
    r"private[_-]?key|allowlist|admin|rbac|permission|"                       # auth / access
    r"payment|billing|payout|refund|charge|invoice|stripe|plaid|wallet|"
    r"transfer|withdraw|deposit|ach|sepa|settlement|crypto|"                  # money movement
    r"migration|schema|prisma|drizzle|\.sql|alter table|drop table|rls|grant|policy|"  # schema/db
    r"\.env|dotenv)", re.I)

PROMPT = """Score this git diff for how SAFE it is to auto-merge to main, 0.0-1.0.
Consider: correctness, test coverage of the change, security, blast radius. Reply with ONE
JSON object: {"confidence":0.0-1.0,"reason":"<=1 sentence"}. Diff:
"""


def assess(worktree, base="main", max_chars=50000, project=None):
    try:
        diff = subprocess.check_output(["git", "diff", f"{base}...HEAD"], cwd=worktree,
                                       text=True, errors="replace")[:max_chars]
    except Exception:
        diff = ""
    high_risk = bool(HIGH_RISK.search(diff))
    if not diff.strip():
        return {"confidence": 0.5, "reason": "empty diff", "high_risk": high_risk}
    try:
        out = claude_cli.run(PROMPT + diff, MODEL, project=project,
                             permission=None, max_turns=1, timeout=150)["text"]
        d = json.loads(re.search(r"\{.*\}", out, re.S).group(0))
        c = float(d.get("confidence", 0.5))
    except Exception as e:
        c, d = 0.5, {"reason": f"score failed ({e})"}
    return {"confidence": round(c, 3), "reason": d.get("reason", ""), "high_risk": high_risk}


def gate(worktree, base="main", threshold=None, project=None):
    """Return ('auto'|'review'|'two_key', confidence_dict). threshold overrides env."""
    a = assess(worktree, base, project=project)
    t = threshold if threshold is not None else THRESHOLD
    if a["high_risk"]:
        return "two_key", a
    return ("auto" if a["confidence"] >= t else "review"), a
