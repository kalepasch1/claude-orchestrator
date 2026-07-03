#!/usr/bin/env python3
"""
plan_stage.py — multi-model PLAN step in the agentic pipeline.

Before an agentic coder (Claude Code / Codex) drafts code for a task, a CHEAPER, NON-Claude
model produces a short implementation strategy that is injected into the draft prompt. This:
  1. makes model optimization real + VISIBLE (a non-Claude model does the "thinking", recorded
     to app_operations telemetry with task_class='plan'),
  2. cuts Claude token burn — Claude drafts against a plan instead of strategizing from scratch,
  3. improves quality, creativity, and speed of the draft.

Fail-soft by design: any error, or no non-Claude planner available, returns (None, None) and the
draft proceeds exactly as before. Toggle with ORCH_MULTIMODEL_PLAN=false.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MIN_LEN = int(os.environ.get("ORCH_PLAN_MIN_LEN", "160"))  # skip trivial/mechanical tasks


def should_plan(task, prompt):
    if os.environ.get("ORCH_MULTIMODEL_PLAN", "true").lower() != "true":
        return False
    # skip very short / mechanical work — planning overhead isn't worth it there
    return len(prompt or "") >= MIN_LEN


def _pick_planner():
    """Cheapest AVAILABLE non-Claude model capable of planning (cap>=6). (provider, model) or None."""
    try:
        import model_policy, model_gateway
        avail = set(model_gateway.available())
        for prov, model, tier, cap in getattr(model_policy, "TRANCHES", []):
            if prov != "claude" and prov in avail and cap >= 6 and model:
                return prov, model
    except Exception:
        pass
    return None


def make_plan(task, prompt, project=None):
    """Return (plan_text, 'provider:model') or (None, None). Non-Claude, cheapest capable."""
    pick = _pick_planner()
    if not pick:
        return None, None
    prov, model = pick
    try:
        import model_gateway
        ask = (
            "You are the STRATEGY model in a multi-model coding pipeline. Produce a SHORT, concrete "
            "implementation plan for the task below: which files to create/edit, the approach, key "
            "edge cases, and how to verify it works. 8-15 bullets max. Do NOT write the full code — "
            "the DRAFT model does that. Task:\n\n" + (prompt or "")
        )
        res = model_gateway.complete(prov, model, ask, project=project, operation="plan",
                                     task_class="plan", timeout=60)
        text = (res or {}).get("text", "").strip()
        if text:
            return text, f"{res.get('provider', prov)}:{res.get('model', model)}"
    except Exception:
        pass
    return None, None


def inject(prompt, plan_text, model_label):
    """Prepend the strategy plan to the draft prompt (or return prompt unchanged)."""
    if not plan_text:
        return prompt
    return (f"# Implementation plan (from strategy model {model_label} — follow it; adapt only if it's "
            f"clearly wrong):\n{plan_text}\n\n# Task:\n{prompt}")


if __name__ == "__main__":
    print("planner:", _pick_planner())
