#!/usr/bin/env python3
"""
model_router.py - pick the cheapest model that can do the job.
Keeps Opus off ordinary work (the big cost lever). Goal: Opus < 10 % of tasks.

Env knobs (set in runner/.env, also in orchestrator.env.example):
    ORCH_DEFAULT_MODEL     default tier; Haiku if unset  (mechanical / first-attempt cheapest)
    ORCH_ESCALATION_MODEL  mid tier; Sonnet if unset     (standard feature work)
    ORCH_HARD_MODEL        hard tier; Opus if unset      (ONLY multi-signal heavy or retry >= 3)

Routing for attempt == 1:
    mechanical (score <= -1, short)  -> ORCH_DEFAULT_MODEL  (Haiku)
    standard   (everything else)     -> ORCH_ESCALATION_MODEL (Sonnet)
    heavy      (score >= 4 OR long + score >= 3)  -> ORCH_HARD_MODEL (Opus)

A single HEAVY keyword (score = 2) is NOT enough for Opus; two+ are required.
Retry escalation: +1 tier per failed attempt. Opus is reachable at attempt 3 from Sonnet.

CLI:
    model_router.py "convert remaining light styles to dark palette"
    model_router.py --attempt 2 "design a new settlement engine"
"""
import re, sys, os, argparse, json

# Tier defaults — overridable via env (set in runner/.env)
HAIKU  = os.environ.get("ORCH_DEFAULT_MODEL",    "claude-haiku-4-5-20251001")
SONNET = os.environ.get("ORCH_ESCALATION_MODEL", "claude-sonnet-4-6")
OPUS   = os.environ.get("ORCH_HARD_MODEL",       "claude-opus-4-8")

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
    # HAIKU-FIRST (matches model_policy + ORCH_DEFAULT_MODEL=haiku): ordinary work starts on the
    # cheapest tier and escalates ONLY on a failed attempt. Opus is never an attempt-1 choice; it
    # is reachable solely via retry escalation, and even genuinely heavy work starts at Sonnet.
    # This is the Opus-retune: measured Opus share was ~34% because standard work defaulted to
    # Sonnet and retries pushed it to Opus. Target: Opus < 10% of tasks.
    if score >= 4 or (long and score >= 3):
        tier = SONNET
        why = "multi-signal heavy -> start at Sonnet (Opus only on retry)"
    else:
        # both mechanical and standard first-attempt work -> Haiku
        tier = HAIKU
        why = "Haiku-first (mechanical/standard); escalate on retry"
    # Deduplicated tier order (handles the case where two env vars point to the same model)
    seen: set = set()
    order = [x for x in [HAIKU, SONNET, OPUS] if not (x in seen or seen.add(x))]
    base_idx = order.index(tier) if tier in order else min(1, len(order) - 1)
    idx = min(base_idx + max(0, attempt - 1), len(order) - 1)
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
