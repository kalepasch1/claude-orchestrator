#!/usr/bin/env python3
from __future__ import annotations
"""
feedback.py - the AGENT -> ORCHESTRATOR channel (makes learning bidirectional). Worker
sessions report how the orchestration itself could be better (context too narrow, wrong
model, weak prompt template, a guardrail that over-blocked, a smarter strategy, an avoidable
rate-limit pattern). Two intake paths:

  1) Auto-extract from a run log: agents are asked to end with
       <orchestrator_feedback>[{"category":"context","severity":"med",
         "observation":"...","suggestion":"..."}]</orchestrator_feedback>
     The runner calls extract_and_store() after every headless run.
  2) CLI for interactive (VS Code) sessions / terminal:
       python3 feedback.py --category model --severity high \
         --observation "Haiku kept failing this refactor" --suggestion "route refactors to Sonnet+"

Feedback is scrubbed (privacy) and stored in `orchestrator_feedback`, then clustered by
feedback_review.py into orchestrator self-improvement proposals (your meta-loop + eval gate).
"""
import os, sys, re, json, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, privacy

CATEGORIES = ("context", "model", "prompt", "tooling", "guardrail", "strategy", "rate_limit", "other")
TAG = re.compile(r"<orchestrator_feedback>(.*?)</orchestrator_feedback>", re.S | re.I)

# Appended to every task prompt so agents know how to report back.
INSTRUCTION = (
    "\n\n# Orchestrator feedback (optional, encouraged): if anything about HOW this task was "
    "set up could be improved — context/files provided, model chosen, prompt clarity, available "
    "tooling, an over-strict guardrail, an avoidable rate-limit, or a better orchestration "
    "strategy — END your run with a block:\n"
    "<orchestrator_feedback>[{\"category\":\"context|model|prompt|tooling|guardrail|strategy|"
    "rate_limit|other\",\"severity\":\"low|med|high\",\"observation\":\"...\",\"suggestion\":"
    "\"...\"}]</orchestrator_feedback>\nKeep it specific and free of any private/customer data."
)


def submit(category, observation, suggestion="", severity="med", project=None, slug=None,
           task_id=None, evidence=None, source="agent"):
    cat = category if category in CATEGORIES else "other"
    obs, _ = privacy.scrub(observation or "")
    sug, _ = privacy.scrub(suggestion or "")
    ev, _ = privacy.scrub(evidence or "")
    db.insert("orchestrator_feedback", {"task_id": task_id, "project": project, "slug": slug,
              "source": source, "category": cat, "severity": severity,
              "observation": obs[:2000], "suggestion": sug[:2000], "evidence": ev[:2000]})
    return True


def extract_and_store(log_text, project=None, slug=None, task_id=None):
    n = 0
    for m in TAG.findall(log_text or ""):
        try:
            items = json.loads(m.strip())
        except Exception:
            continue
        for it in (items if isinstance(items, list) else [items]):
            submit(it.get("category", "other"), it.get("observation", ""),
                   it.get("suggestion", ""), it.get("severity", "med"),
                   project, slug, task_id, it.get("evidence"))
            n += 1
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", default="other"); ap.add_argument("--severity", default="med")
    ap.add_argument("--observation", required=True); ap.add_argument("--suggestion", default="")
    ap.add_argument("--project"); ap.add_argument("--source", default="interactive")
    a = ap.parse_args()
    submit(a.category, a.observation, a.suggestion, a.severity, a.project, source=a.source)
    print("feedback recorded.")
