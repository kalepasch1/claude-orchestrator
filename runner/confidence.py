#!/usr/bin/env python3
"""
confidence.py - CONFIDENCE-GATED AUTONOMY. A cheap model scores how safe a diff is to
auto-merge (0-1). High confidence -> auto-integrate; low -> route to a human approval.
Also flags HIGH-RISK diffs (auth/payment/migration/secret paths) that should require
two-key approval. Autonomy that flexes with risk instead of fixed rules.
"""
import os, sys, subprocess, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
MODEL = os.environ.get("CONFIDENCE_MODEL", "claude-haiku-4-5-20251001")
THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.8"))
HIGH_RISK = re.compile(r"(auth|payment|billing|allowlist|migration|secret|rls|admin|"
                       r"settlement|crypto|password|token)", re.I)

PROMPT = """Score this git diff for how SAFE it is to auto-merge to main, 0.0-1.0.
Consider: correctness, test coverage of the change, security, blast radius. Reply with ONE
JSON object: {"confidence":0.0-1.0,"reason":"<=1 sentence"}. Diff:
"""


def assess(worktree, base="main", max_chars=50000):
    try:
        diff = subprocess.check_output(["git", "diff", f"{base}...HEAD"], cwd=worktree,
                                       text=True, errors="replace")[:max_chars]
    except Exception:
        diff = ""
    high_risk = bool(HIGH_RISK.search(diff))
    if not diff.strip():
        return {"confidence": 0.5, "reason": "empty diff", "high_risk": high_risk}
    try:
        out = subprocess.check_output([CLAUDE_BIN, "-p", PROMPT + diff, "--model", MODEL,
                                       "--output-format", "text"], text=True, timeout=150)
        d = json.loads(re.search(r"\{.*\}", out, re.S).group(0))
        c = float(d.get("confidence", 0.5))
    except Exception as e:
        c, d = 0.5, {"reason": f"score failed ({e})"}
    return {"confidence": round(c, 3), "reason": d.get("reason", ""), "high_risk": high_risk}


def gate(worktree, base="main"):
    """Return ('auto'|'review'|'two_key', confidence_dict)."""
    a = assess(worktree, base)
    if a["high_risk"]:
        return "two_key", a
    return ("auto" if a["confidence"] >= THRESHOLD else "review"), a
