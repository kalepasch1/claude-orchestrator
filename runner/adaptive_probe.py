#!/usr/bin/env python3
"""Probe-first routing for expensive agentic work.

A small local/cheap model gets a minimized diagnostic prompt first. The coder then
receives a smaller, higher-signal slice instead of the full strategic burden.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MARK = "ADAPTIVE PROBE-FIRST SLICE"


def should_probe(task, prompt):
    if os.environ.get("ORCH_ADAPTIVE_PROBE", "true").lower() not in ("1", "true", "yes", "on"):
        return False
    if MARK in str(prompt or ""):
        return False
    kind = str((task or {}).get("kind") or "").lower()
    if kind in ("mechanical", "chore", "docs", "cleanup", "canary"):
        return False
    text = str(prompt or "")
    char_threshold = int(os.environ.get("ORCH_ADAPTIVE_PROBE_CHARS", "1200"))
    if len(text) > char_threshold:
        return True
    if (task or {}).get("material"):
        return True
    return kind in ("build", "security", "legal")


def make_probe(task, prompt, project):
    try:
        import model_policy, model_gateway
        sensitivity = str((task or {}).get("sensitivity") or "standard")
        provider, model, _ = model_policy.choose("review", agentic=False, need=5, sensitivity=sensitivity)
        probe_prompt = (
            "You are a cheap preflight probe. Do not implement. Return a compact routing brief:\n"
            "- PROMISING: yes/no\n"
            "- MINIMAL_SLICE: the smallest file/symbol/test area likely needed\n"
            "- REUSE: existing helpers or prior pattern keywords to search\n"
            "- RISKS: only the top 2 merge/build risks\n\n"
            "TASK:\n" + str(prompt or "")[:8000]
        )
        res = model_gateway.complete(provider, model, probe_prompt, project=project,
                                     timeout=int(os.environ.get("ORCH_ADAPTIVE_PROBE_TIMEOUT", "45")),
                                     operation="adaptive_probe", task_class="review",
                                     fallback=True)
        text = (res.get("text") or "").strip()
        if not text:
            return ""
        return f"\n\n{MARK} ({res.get('provider')}:{res.get('model')}):\n{text[:1600]}\n"
    except Exception:
        return ""


def inject(task, prompt, project="orchestrator"):
    if not should_probe(task, prompt):
        return prompt
    probe = make_probe(task, prompt, project)
    return (probe + "\n" + prompt) if probe else prompt
