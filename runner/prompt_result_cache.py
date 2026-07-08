#!/usr/bin/env python3
"""Prompt/result cache keyed by code intent, not raw prompt text.

The cache is intentionally local-first: it avoids re-sending repeated review,
planning, and probe prompts while keeping potentially sensitive outputs on disk.
"""
import hashlib
import json
import os
import re
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".runtime", "prompt_result_cache.jsonl")
MAX_ROWS = int(os.environ.get("ORCH_PROMPT_CACHE_ROWS", "3000"))
TTL_SECONDS = int(os.environ.get("ORCH_PROMPT_CACHE_TTL_SECONDS", str(14 * 24 * 3600)))

SYMBOL = re.compile(r"\b(?:class|def|function|const|let|var|interface|type)\s+([A-Za-z_][A-Za-z0-9_]*)")
WORD = re.compile(r"[a-z0-9_]{4,}", re.I)


def _words(text):
    return sorted({w.lower() for w in WORD.findall(str(text or "")) if len(w) > 4})[:80]


def intent(prompt):
    text = str(prompt or "")
    symbols = sorted(set(SYMBOL.findall(text)))[:40]
    words = _words(text)
    acceptance = " ".join(w for w in words if w in {
        "acceptance", "build", "test", "tests", "verify", "review", "security",
        "webhook", "schema", "migration", "endpoint", "component", "routing",
        "cache", "ollama", "model", "deploy", "merge"
    })
    return {"symbols": symbols, "words": words, "acceptance": acceptance}


def key(provider, model, task_class, operation, prompt, sensitivity="standard"):
    blob = json.dumps({
        "provider": provider,
        "model": model,
        "task_class": task_class or "unknown",
        "operation": operation or "completion",
        "sensitivity": sensitivity or "standard",
        "intent": intent(prompt),
    }, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def _load():
    rows = []
    try:
        with open(CACHE) as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    except OSError:
        pass
    cutoff = time.time() - TTL_SECONDS
    return [r for r in rows if float(r.get("created_at") or 0) >= cutoff][-MAX_ROWS:]


def lookup(provider, model, task_class, operation, prompt, sensitivity="standard"):
    if os.environ.get("ORCH_PROMPT_RESULT_CACHE", "true").lower() not in ("1", "true", "yes", "on"):
        return None
    k = key(provider, model, task_class, operation, prompt, sensitivity)
    for row in reversed(_load()):
        if row.get("key") == k and row.get("text"):
            return {"text": row["text"], "cost_usd": 0.0, "provider": provider,
                    "model": model, "cached": True}
    return None


def store(provider, model, task_class, operation, prompt, text, sensitivity="standard"):
    if not text or os.environ.get("ORCH_PROMPT_RESULT_CACHE", "true").lower() not in ("1", "true", "yes", "on"):
        return False
    if sensitivity in ("crown_jewel", "crown-jewel", "crownjewel"):
        return False
    row = {"key": key(provider, model, task_class, operation, prompt, sensitivity),
           "provider": provider, "model": model, "task_class": task_class,
           "operation": operation, "created_at": time.time(), "intent": intent(prompt),
           "text": str(text)[:20000]}
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        rows = _load() + [row]
        with open(CACHE, "w") as f:
            for r in rows[-MAX_ROWS:]:
                f.write(json.dumps(r, sort_keys=True) + "\n")
        return True
    except OSError:
        return False
