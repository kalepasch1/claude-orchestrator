#!/usr/bin/env python3
"""Nightly local-model canaries against real historical merged tasks."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import model_gateway
import ollama_catalog


def _enabled():
    return os.environ.get("ORCH_HISTORICAL_MODEL_CANARIES", "true").lower() in ("1", "true", "yes", "on")


def _historical_tasks(limit=6):
    try:
        rows = db.select("tasks", {"select": "project_id,slug,kind,prompt,note",
                                   "state": "eq.MERGED",
                                   "order": "updated_at.desc",
                                   "limit": str(limit * 3)}) or []
    except Exception:
        rows = []
    out = []
    for row in rows:
        prompt = str(row.get("prompt") or "").strip()
        if len(prompt) < 120:
            continue
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _score(text):
    low = str(text or "").lower()
    must = ("risk", "files", "test")
    return sum(1 for m in must if m in low) / len(must)


def _record(model, task, latency_ms, ok, quality, prompt, error=""):
    try:
        db.insert("app_operations", {
            "app": "orchestrator",
            "operation": "model_canary",
            "task_class": task.get("kind") or "build",
            "provider": "local",
            "model": model,
            "prompt_chars": len(prompt or ""),
            "cost_usd": 0.0,
            "latency_ms": int(latency_ms or 0),
            "ok": bool(ok),
            "quality_score": float(quality or 0.0),
            "verdict": ("pass" if ok else ("error: " + (error or "quality below threshold"))[:500]),
        })
    except Exception as e:
        print(f"historical_model_canary: telemetry insert failed for {model}: {e}")


def _probe_prompt(task):
    return (
        "You are benchmarking routing on a real previously merged task. Do not implement. "
        "Return exactly three bullets labeled Files, Test, Risk.\n\n"
        f"Historical slug: {task.get('slug')}\n"
        "Prompt excerpt:\n" + str(task.get("prompt") or "")[:3500]
    )


def run(limit_models=None, limit_tasks=None, timeout=None):
    if not _enabled():
        return {"ran": 0, "reason": "disabled"}
    limit_models = int(limit_models if limit_models is not None else os.environ.get("ORCH_HISTORICAL_CANARY_MODELS", "8"))
    limit_tasks = int(limit_tasks if limit_tasks is not None else os.environ.get("ORCH_HISTORICAL_CANARY_TASKS", "4"))
    timeout = int(timeout if timeout is not None else os.environ.get("ORCH_HISTORICAL_CANARY_TIMEOUT", "60"))
    models = ollama_catalog.candidates(include_canary_only=True)
    only = [m.strip() for m in os.environ.get("ORCH_HISTORICAL_CANARY_MODELS_ONLY", "").split(",") if m.strip()]
    if only:
        allowed = set(only)
        models = [c for c in models if c.get("model") in allowed]
    models = sorted(models, key=lambda c: (not bool(c.get("canary_only")), -int(c.get("cap") or 0), c.get("model") or ""))[:limit_models]
    tasks = _historical_tasks(limit_tasks)
    ran = 0
    for c in models:
        model = c.get("model")
        if not model:
            continue
        for task in tasks:
            prompt = _probe_prompt(task)
            t0 = time.time()
            try:
                res = model_gateway.complete("local", model, prompt, project="orchestrator",
                                             timeout=timeout, operation="historical_model_canary",
                                             task_class=task.get("kind") or "build",
                                             fallback=False, record_op=False)
                latency = (time.time() - t0) * 1000
                q = _score(res.get("text"))
                _record(model, task, latency, q >= 0.67, q, prompt)
                ran += 1
            except Exception as e:
                _record(model, task, (time.time() - t0) * 1000, False, 0.0, prompt, str(e))
                ran += 1
    print(f"historical_model_canary: ran {ran} model/task probes ({len(models)} models, {len(tasks)} tasks)")
    return {"ran": ran, "models": len(models), "tasks": len(tasks)}


if __name__ == "__main__":
    print(run())
