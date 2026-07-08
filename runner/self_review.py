#!/usr/bin/env python3
"""
self_review.py - the orchestrator improving ITSELF (not just the apps it manages).

Runs nightly. Reads its own telemetry (outcomes), computes where it's losing time/
money/quality, and asks a model to propose concrete changes to the orchestrator's OWN
config/code (router rules, concurrency, prompt templates, guard patterns, conventions).
Each idea becomes an APPROVAL card (kind='self') with why/value/risk - turned inward.

Meta-safety (the lesson from the 24-conflict self-loop incident):
  * it NEVER edits the orchestrator directly - it only proposes;
  * material self-changes are applied via a normal task on a branch -> CI -> your
    approval, so a bad self-edit can't ship silently and is always revertible;
  * the eval gate (eval_harness) A/B-tests a proposed prompt/template change against
    held-out tasks before adoption.

Run: python3 self_review.py        (wire to the 02:00 launchd agent / a Supabase cron)
"""
import os, sys, json, subprocess, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

REVIEW_MODEL = os.environ.get("SELF_REVIEW_MODEL", "claude-opus-4-8")


def stats():
    rows = db.select("outcomes", {"select": "*", "order": "created_at.desc", "limit": "2000"}) or []
    if not rows:
        return None, "no telemetry yet"
    n = len(rows)
    by_model = collections.Counter(r["model"] for r in rows)
    spend = collections.defaultdict(float)
    fails = sum(1 for r in rows if not r.get("tests_passed"))
    rl = sum(1 for r in rows if r.get("rate_limited"))
    not_integrated = sum(1 for r in rows if r.get("tests_passed") and not r.get("integrated"))
    retries = sum((r.get("attempts") or 1) - 1 for r in rows)
    for r in rows:
        spend[r["model"]] += float(r.get("usd") or 0)
    try:
        tasks = db.select("tasks", {"select": "state,slug,note", "limit": "1000"}) or []
    except Exception:
        tasks = []
    queue_states = collections.Counter(t.get("state") for t in tasks)
    recovery = collections.Counter(t.get("state") for t in tasks
                                   if str(t.get("slug") or "").startswith("recover-missing-branch-"))
    pressure = ""
    try:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            ".runtime", "merge_train_pressure.json")
        if os.path.isfile(path):
            pressure = open(path).read()[:2000]
    except Exception:
        pass
    summary = {
        "tasks": n, "fail_rate": round(fails / n, 3), "rate_limit_rate": round(rl / n, 3),
        "verify_or_integrate_block_rate": round(not_integrated / n, 3),
        "total_retries": retries, "spend_by_model": {k: round(v, 2) for k, v in spend.items()},
        "model_mix": dict(by_model),
        "queue_states": dict(queue_states),
        "recovery_backlog": dict(recovery),
        "merge_train_pressure": pressure}
    return summary, json.dumps(summary, indent=2)


PROMPT = """You are the orchestrator's self-improvement reviewer. Below is telemetry from
the autonomous build system you are part of. Propose the TOP 3 concrete, low-risk
changes to the ORCHESTRATOR ITSELF that would most improve throughput-per-dollar or
reliability. Candidates: model-routing rules, concurrency ceiling, retry/backoff,
prompt/context templates, guard deny/ask patterns, conventions prefix.
For EACH, output one JSON object on its own line:
{"title":"...","why":"<what the data shows>","value":"<expected win, quantified>",
 "risk":"<risk + how to test>","change":"<the precise config/code edit to make>"}
TELEMETRY:
"""


def run():
    summary, text = stats()
    if not summary:
        print(text); return
    try:
        import model_policy, model_gateway
        prov, model, _ = model_policy.choose("plan", agentic=False, need=8)
        r = model_gateway.complete(prov, model, PROMPT + text,
                                   timeout=int(os.environ.get("SELF_REVIEW_TIMEOUT", "300")),
                                   operation="self_review", task_class="plan",
                                   project="orchestrator")
        out = r["text"]
    except Exception as e:
        print("self-review model call failed:", e); return
    made = 0
    for line in out.splitlines():
        line = line.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            p = json.loads(line)
        except Exception:
            continue
        db.insert("approvals", {
            "project": "ORCHESTRATOR", "kind": "self", "title": p.get("title", "self-improvement"),
            "why": p.get("why"), "value": p.get("value"), "risk": p.get("risk"),
            "detail": p.get("change"), "command": ""})
        made += 1
    print(f"self-review filed {made} improvement proposals (approve them in the dashboard).")


if __name__ == "__main__":
    run()
