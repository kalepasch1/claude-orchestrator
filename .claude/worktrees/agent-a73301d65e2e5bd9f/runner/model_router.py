#!/usr/bin/env python3
"""
model_router.py - pick the cheapest model that can do the job.
Keeps Opus off trivial work (the big cost lever) and downgrades on retry.

CLI:
    model_router.py "convert remaining light styles to dark palette"
    model_router.py --attempt 2 "design a new settlement engine"   # escalates with retries

Heuristic, transparent, and overridable per-task via tasks.yaml `model:`.
Tiers (newest model strings):
    haiku  = claude-haiku-4-5-20251001     mechanical / formatting / rename / lint fixups
    sonnet = claude-sonnet-4-6             standard feature work, tests, refactors
    opus   = claude-opus-4-8               architecture, novel design, security-sensitive
"""
import re, sys, argparse, json

HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-4-6"
OPUS = "claude-opus-4-8"

MECHANICAL = re.compile(r"\b(rename|format|prettier|lint|typo|comment|import order|"
                        r"dark mode|theme|palette|css|tailwind|copy edit|bump version|"
                        r"changelog|docstring|whitespace|remove duplicate)\b", re.I)
HEAVY = re.compile(r"\b(architect|design|novel|security|auth|crypto|settlement|migration|"
                   r"schema|distributed|concurrency|algorithm|refactor the|rewrite|"
                   r"non-custodial|allowlist|threat model|protocol)\b", re.I)


def route(prompt: str, attempt: int = 1) -> dict:
    p = prompt or ""
    score = len(HEAVY.findall(p)) * 2 - len(MECHANICAL.findall(p))
    long = len(p) > 1200
    if score >= 2 or (long and score >= 1):
        tier = OPUS
        why = "reasoning-heavy / novel / security-sensitive signals"
    elif score <= -1 and not long:
        tier = HAIKU
        why = "mechanical/formatting work"
    else:
        tier = SONNET
        why = "standard feature work"
    # escalate one tier per failed attempt (a stuck task usually needs more model)
    order = [HAIKU, SONNET, OPUS]
    idx = min(order.index(tier) + max(0, attempt - 1), len(order) - 1)
    chosen = order[idx]
    return {"model": chosen, "base": tier, "attempt": attempt, "reason": why}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt")
    ap.add_argument("--attempt", type=int, default=1)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = route(a.prompt, a.attempt)
    print(json.dumps(r) if a.json else r["model"])
