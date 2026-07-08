#!/usr/bin/env python3
"""Low-cost local Ollama model calibration.

Runs tiny deterministic probes against each discovered local model and records
latency/pass/fail telemetry in app_operations. The model catalog already reads
that table, so local routing improves as these samples accumulate.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import model_gateway
import ollama_catalog


PROBES = [
    {
        "task_class": "mechanical",
        "need": 5,
        "prompt": "Return exactly this JSON and nothing else: {\"ok\":true,\"n\":7}",
        "must": ['"ok"', "true", '"n"', "7"],
    },
    {
        "task_class": "review",
        "need": 6,
        "prompt": "In one sentence, identify the bug: for i in range(len(items)+1): print(items[i])",
        "must": ["range", "len", "index"],
    },
    {
        "task_class": "plan",
        "need": 7,
        "prompt": "Give exactly three short numbered steps to safely update a dependency.",
        "must": ["1", "2", "3"],
    },
]


def _enabled():
    return os.environ.get("ORCH_OLLAMA_CALIBRATION", "true").lower() in ("1", "true", "yes", "on")


def _score(text, must):
    low = (text or "").lower()
    hits = sum(1 for m in must if str(m).lower() in low)
    return hits / max(1, len(must))


def _record(model, task_class, prompt, latency_ms, ok, quality, error=""):
    try:
        db.insert("app_operations", {
            "app": "orchestrator",
            "operation": "ollama_calibration",
            "task_class": task_class,
            "provider": "local",
            "model": model,
            "prompt_chars": len(prompt or ""),
            "cost_usd": 0.0,
            "latency_ms": int(latency_ms or 0),
            "ok": bool(ok),
            "quality_score": float(quality or 0.0),
            "error": (error or "")[:500],
        })
    except Exception:
        # Older schemas may not have quality_score/error yet.
        try:
            db.insert("app_operations", {
                "app": "orchestrator",
                "operation": "ollama_calibration",
                "task_class": task_class,
                "provider": "local",
                "model": model,
                "prompt_chars": len(prompt or ""),
                "cost_usd": 0.0,
                "latency_ms": int(latency_ms or 0),
                "ok": bool(ok),
            })
        except Exception:
            pass


def run(limit_models=None, timeout=None, max_probes_per_model=None):
    if not _enabled():
        return {"calibrated": 0, "reason": "disabled"}
    limit_models = int(limit_models if limit_models is not None else os.environ.get("ORCH_OLLAMA_CALIBRATION_MODELS", "2"))
    timeout = int(timeout if timeout is not None else os.environ.get("ORCH_OLLAMA_CALIBRATION_TIMEOUT", "20"))
    max_probes_per_model = int(max_probes_per_model if max_probes_per_model is not None else os.environ.get("ORCH_OLLAMA_CALIBRATION_PROBES", "1"))
    candidates = sorted(ollama_catalog.candidates(),
                        key=lambda c: (-int(c.get("cap") or 0), c.get("model") or ""))[:limit_models]
    calibrated = 0
    for c in candidates:
        model = c.get("model")
        if not model:
            continue
        for probe in PROBES[:max(1, max_probes_per_model)]:
            if int(c.get("cap") or 0) < int(probe["need"]):
                continue
            t0 = time.time()
            try:
                res = model_gateway.complete("local", model, probe["prompt"], project="orchestrator",
                                             timeout=timeout, operation="ollama_calibration",
                                             task_class=probe["task_class"], fallback=False, record_op=False)
                latency = (time.time() - t0) * 1000
                quality = _score(res.get("text"), probe["must"])
                _record(model, probe["task_class"], probe["prompt"], latency, quality >= 0.75, quality)
                calibrated += 1
            except Exception as e:
                latency = (time.time() - t0) * 1000
                _record(model, probe["task_class"], probe["prompt"], latency, False, 0.0, str(e))
    print(f"ollama_calibrator: recorded {calibrated} probes across {len(candidates)} model(s)")
    return {"calibrated": calibrated, "models": len(candidates)}


if __name__ == "__main__":
    print(run())
