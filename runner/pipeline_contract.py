#!/usr/bin/env python3
"""
pipeline_contract.py - one shared task envelope for every improvement source.

Dashboard prompts, intake files, autonomous miners, recovered tasks, and loop-generated work should
enter the same operating model:
  * cheap provider triage and planning before agentic spend,
  * agentic coding through the best available coder route,
  * independent cross-model QA,
  * automatic dev-branch merge and batched production release,
  * human approval only for secrets or true regulatory-posture changes.

This module is intentionally fail-soft. If live telemetry or provider discovery is unavailable, it
still returns a deterministic contract rather than blocking task execution.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import agentic_coders
import legal_filter
import model_gateway as mg
import model_policy
import model_router

try:
    import app_triage
except Exception:  # pragma: no cover - import should normally work, contract still degrades
    app_triage = None

try:
    import judge
except Exception:  # pragma: no cover
    judge = None


MARKER = "ORCHESTRATION PIPELINE CONTRACT"
ORIGINAL_HEADER = "# Original improvement request"
CONTROL_PREFIXES = ("REPLAY:", "ROTATE_KEY:", "REVOKE_AND_STOP:")

SECURITY_RX = re.compile(r"\b(auth|oauth|permission|rls|secret|token|credential|security|xss|csrf|sql injection)\b", re.I)
MIGRATION_RX = re.compile(r"\b(schema|migration|database|backfill|data model|rls|release train|merge train)\b", re.I)
RESEARCH_RX = re.compile(r"\b(research|investigate|ideate|concept|strategy|proposal|experiment|ab test|a/b)\b", re.I)
MECHANICAL_RX = re.compile(r"\b(copy|typo|format|lint|rename|style|css|tailwind|docs?|changelog)\b", re.I)


def is_control_prompt(prompt: str) -> bool:
    text = (prompt or "").lstrip()
    return any(text.startswith(p) for p in CONTROL_PREFIXES)


def already_wrapped(prompt: str) -> bool:
    return MARKER in (prompt or "")


def original_request(prompt: str) -> str:
    """Return the human/task body without the orchestration wrapper, when present."""
    text = prompt or ""
    if MARKER not in text:
        return text
    idx = text.find(ORIGINAL_HEADER)
    if idx >= 0:
        return text[idx + len(ORIGINAL_HEADER):].strip()
    # Fallback for partially copied prompts: remove the first contract block.
    return re.sub(r"## ORCHESTRATION PIPELINE CONTRACT.*?## END ORCHESTRATION PIPELINE CONTRACT\s*",
                  "", text, count=1, flags=re.S).strip()


def classify(prompt: str, kind: str = "build", material: bool = False) -> Dict[str, Any]:
    """Return the task class and capability need used for route planning."""
    text = prompt or ""
    k = (kind or "build").lower()
    if material or legal_filter.requires_owner_approval(text=text):
        return {"task_class": "legal", "need": 9, "risk": "legal_posture"}
    if SECURITY_RX.search(text):
        return {"task_class": "security", "need": 9, "risk": "security"}
    if k in ("research", "strategy") or RESEARCH_RX.search(text):
        return {"task_class": "plan", "need": 8, "risk": "strategy"}
    if k in ("efficiency", "cost") or MECHANICAL_RX.search(text):
        return {"task_class": "mechanical", "need": 5, "risk": "routine"}
    if k == "speculative" or MIGRATION_RX.search(text):
        return {"task_class": "hard", "need": 8, "risk": "broad_change"}
    return {"task_class": "build", "need": 6, "risk": "standard"}


def _safe_route(app: str, operation: str, task_class: str, need: Optional[int] = None,
                agentic: bool = False) -> Dict[str, str]:
    try:
        if app_triage is not None:
            r = app_triage.route(app, operation, task_class=task_class, agentic=agentic, need=need)
            return {
                "provider": str(r.get("provider") or ""),
                "model": str(r.get("model") or ""),
                "reason": str(r.get("reason") or r.get("source") or "policy"),
            }
    except Exception:
        pass
    try:
        p, m, why = model_policy.choose(task_class=task_class, agentic=agentic, need=need)
        return {"provider": p, "model": m, "reason": why}
    except Exception:
        return {"provider": "claude", "model": "claude-haiku-4-5-20251001", "reason": "fallback policy"}


def _author_model(prompt: str, kind: str) -> str:
    try:
        return model_router.route(prompt, 1)["model"]
    except Exception:
        return os.environ.get("ORCH_DEFAULT_MODEL", "claude-haiku-4-5-20251001")


def _coder(slug: str, prompt: str, material: bool) -> str:
    task = {"slug": slug or "", "prompt": prompt or "", "material": material, "deps": []}
    try:
        return agentic_coders.pick(task)
    except Exception:
        return "claude"


def _qa_panel(author_model: str) -> List[str]:
    try:
        if judge is not None and hasattr(judge, "_panel_providers"):
            providers = judge._panel_providers(author_model)  # existing reviewer ordering
            reviewers = getattr(judge, "REVIEWERS", {})
            return [f"{p}:{reviewers.get(p, '')}".rstrip(":") for p in providers]
    except Exception:
        pass
    try:
        avail = [p for p in ("local", "deepseek", "google", "openai", "claude") if p in set(mg.available())]
        return avail[:2] or ["claude:claude-haiku-4-5-20251001"]
    except Exception:
        return ["claude:claude-haiku-4-5-20251001"]


def _recent_context(project: str) -> List[str]:
    """Small cross-learning bundle. Best effort only; DB/network failure returns an empty list."""
    if not project:
        return []
    try:
        import db
    except Exception:
        return []
    items: List[str] = []
    try:
        rows = db.select("outcomes", {"select": "model,tests_passed,integrated,usd",
                                      "project": f"eq.{project}",
                                      "order": "created_at.desc", "limit": "12"}) or []
        if rows:
            merged = sum(1 for r in rows if r.get("integrated"))
            passed = sum(1 for r in rows if r.get("tests_passed"))
            spend = sum(float(r.get("usd") or 0) for r in rows)
            models = ", ".join(sorted({str(r.get("model") or "?") for r in rows})[:4])
            items.append(f"recent outcome signal: {merged}/{len(rows)} merged, {passed}/{len(rows)} test-pass, ${spend:.2f}, models {models}")
    except Exception:
        pass
    try:
        routes = db.select("app_op_routes", {"select": "operation,provider,model,avg_quality",
                                             "app": f"eq.{project}", "limit": "4"}) or []
        for r in routes[:4]:
            q = r.get("avg_quality")
            qtxt = f", q={q}" if q is not None else ""
            items.append(f"learned route: {r.get('operation')} -> {r.get('provider')}:{r.get('model')}{qtxt}")
    except Exception:
        pass
    try:
        fb = db.select("orchestrator_feedback", {"select": "category,severity,observation",
                                                 "status": "in.(new,open)",
                                                 "order": "created_at.desc", "limit": "3"}) or []
        for f in fb[:3]:
            obs = str(f.get("observation") or "").replace("\n", " ")[:140]
            if obs:
                items.append(f"operator feedback: {f.get('severity')}/{f.get('category')} - {obs}")
    except Exception:
        pass
    return items[:8]


def build_plan(prompt: str, project: str = "", kind: str = "build", source: str = "unknown",
               slug: str = "", material: bool = False) -> Dict[str, Any]:
    cls = classify(prompt, kind=kind, material=material)
    author = _author_model(prompt, kind)
    coder = _coder(slug, prompt, material)
    preflight = _safe_route("orchestrator", "task_preflight", "rating", need=5, agentic=False)
    strategy = _safe_route("orchestrator", "task_strategy", "plan", need=max(7, int(cls["need"])), agentic=False)
    qa = _safe_route("orchestrator", "task_qa", "review", need=6 if cls["need"] < 8 else 8, agentic=False)
    return {
        "source": source or "unknown",
        "project": project or "selected app",
        "kind": kind or "build",
        "slug": slug or "(auto)",
        "task_class": cls["task_class"],
        "need": cls["need"],
        "risk": cls["risk"],
        "preflight": preflight,
        "strategy": strategy,
        "coder": coder,
        "author_model": author,
        "qa": qa,
        "qa_panel": _qa_panel(author),
        "legal_gate": "owner-only when the change would force licensing/registration/custody/transmission/advice or needs a secret",
        "release": f"auto-merge to {os.environ.get('ORCH_STAGING_BRANCH', 'orchestrator/dev')} after tests, verify, judge; production release via batch train",
        "collaboration": _recent_context(project),
    }


def render_plan(plan: Dict[str, Any]) -> str:
    def route_line(label: str, r: Dict[str, str]) -> str:
        model = f"{r.get('provider', '?')}:{r.get('model', '?')}"
        why = r.get("reason") or "policy"
        return f"- {label}: {model} ({why})"

    lines = [
        f"## {MARKER}",
        f"- source: {plan.get('source')}",
        f"- project: {plan.get('project')}",
        f"- task class: {plan.get('task_class')} (need {plan.get('need')}, risk {plan.get('risk')})",
        route_line("preflight triage", plan.get("preflight") or {}),
        route_line("strategy planner", plan.get("strategy") or {}),
        f"- agentic coder: {plan.get('coder')} using author model {plan.get('author_model')}",
        route_line("independent QA route", plan.get("qa") or {}),
        f"- QA panel: {', '.join(plan.get('qa_panel') or [])}",
        f"- legal gate: {plan.get('legal_gate')}",
        f"- merge/release: {plan.get('release')}",
        "- coordination rule: reconcile with active loop-generated work, reuse prior solutions first, do not delete or overwrite unrelated queued improvements, and leave recovered work in the queue until shipped.",
    ]
    ctx = plan.get("collaboration") or []
    if ctx:
        lines.append("- cross-learning context:")
        lines.extend(f"  - {item}" for item in ctx)
    lines.append(f"## END {MARKER}")
    return "\n".join(lines)


def wrap_prompt(prompt: str, project: str = "", kind: str = "build", source: str = "unknown",
                slug: str = "", material: bool = False) -> str:
    """Prepend the shared contract unless the prompt is already wrapped or is a control command."""
    text = prompt or ""
    if not text.strip() or already_wrapped(text) or is_control_prompt(text):
        return text
    plan = build_plan(text, project=project, kind=kind, source=source, slug=slug, material=material)
    return render_plan(plan) + "\n\n" + ORIGINAL_HEADER + "\n" + text


def note(existing: str = "", source: str = "unknown") -> str:
    base = (existing or "").strip()
    suffix = f"pipeline:{source or 'unknown'}; triage-plan-code-qa-devmerge-release"
    return f"{base}; {suffix}" if base else suffix


def artifact(prompt: str, project: str = "", kind: str = "build", source: str = "unknown",
             slug: str = "", material: bool = False) -> str:
    """Return a compact JSON string capturing the analysis plan for this task.

    Stored alongside the task (e.g. in log_tail or a dedicated column) so the routing
    decisions made before the agent ran are queryable without re-parsing the prompt.
    Fail-soft: returns "{}" on any error so callers are never blocked.
    """
    try:
        plan = build_plan(prompt, project=project, kind=kind, source=source, slug=slug, material=material)
        storable = {
            "task_class": plan.get("task_class"),
            "need": plan.get("need"),
            "risk": plan.get("risk"),
            "coder": plan.get("coder"),
            "author_model": plan.get("author_model"),
            "preflight": plan.get("preflight", {}).get("model"),
            "strategy": plan.get("strategy", {}).get("model"),
            "qa": plan.get("qa", {}).get("model"),
            "qa_panel": plan.get("qa_panel"),
            "source": plan.get("source"),
            "project": plan.get("project"),
        }
        return json.dumps(storable, separators=(",", ":"))
    except Exception:
        return "{}"


if __name__ == "__main__":
    print(wrap_prompt("Improve the dashboard queue flow.", project="beethoven", source="manual"))
