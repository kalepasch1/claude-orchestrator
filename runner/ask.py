#!/usr/bin/env python3
"""
ask.py - natural-language analytics over the orchestrator itself.
  python3 ask.py "which projects are bleeding money or blocked > 2 days?"
Pulls a compact telemetry snapshot and lets a model answer in plain English.
"""
import os, sys, json, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, health, roi, claude_cli

MODEL = os.environ.get("ASK_MODEL", "claude-sonnet-4-6")


def snapshot() -> dict:
    """Return a compact telemetry dict (health, inbox, ROI, open tasks) for LLM analysis."""
    return {
        "health": db.select("v_project_health", {"select": "*"}) or [],
        "inbox": (db.select("v_action_inbox", {"select": "*"}) or [])[:30],
        "roi": roi.report(),
        "open_tasks": db.select("tasks", {"select": "project_id,slug,state,note,updated_at",
                                          "state": "in.(RUNNING,QUEUED,WAITING,BLOCKED)"}) or [],
    }


def answer(question: str) -> str:
    snap = json.dumps(snapshot())[:60000]
    prompt = (f"You are an analyst for a multi-project autonomous build system. Using ONLY "
              f"this telemetry JSON, answer the question concisely with specific projects/"
              f"numbers.\nQUESTION: {question}\nTELEMETRY: {snap}")
    try:
        return claude_cli.run(prompt, MODEL, timeout=120)["text"]
    except Exception as e:
        return f"(ask failed: {e})"


if __name__ == "__main__":
    print(answer(" ".join(sys.argv[1:]) or "what needs my attention most right now?"))
