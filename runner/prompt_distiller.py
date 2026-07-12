#!/usr/bin/env python3
"""
prompt_distiller.py - compress winning merged patterns into tighter prompts.
Analyses merged tasks to extract recurring conventions, distils into compact
prompt fragments so future tasks trend cheaper. Tracks token savings.
"""
from __future__ import annotations
import collections, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

SAMPLE_LIMIT = int(os.environ.get("ORCH_DISTILL_SAMPLE_LIMIT", "100"))
MIN_PATTERN_FREQ = int(os.environ.get("ORCH_DISTILL_MIN_FREQ", "3"))
_CONVENTION_RE = re.compile(r"(?:DO|AVOID|ALWAYS|NEVER|MUST|CONVENTION|RULE)[\s:]+(.{20,200})", re.I)
_DIRECTIVE_RE = re.compile(r"(?:PREFLIGHT DIRECTIVE|AGENTIC-REPAIR|AUTO-REMEDIATION)\b.*$", re.MULTILINE)

def _estimate_tokens(text):
    return len(text or "") // 4

def _strip_directives(prompt):
    return _DIRECTIVE_RE.sub("", prompt or "").strip()

def extract_conventions(prompts):
    counts = collections.Counter()
    for p in prompts:
        for m in _CONVENTION_RE.finditer(p or ""):
            counts[re.sub(r"\s+", " ", m.group(1).strip().rstrip("."))] += 1
    return [c for c, n in counts.most_common() if n >= MIN_PATTERN_FREQ]

def distill_prompt(prompt):
    cleaned = _strip_directives(prompt)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    seen = []
    for line in cleaned.split("\n"):
        s = line.strip()
        if s and s in seen:
            continue
        seen.append(s)
    return "\n".join(seen).strip()

def measure_savings(original, distilled):
    orig = _estimate_tokens(original)
    dist = _estimate_tokens(distilled)
    saved = orig - dist
    return {"original_tokens": orig, "distilled_tokens": dist,
            "tokens_saved": saved, "savings_pct": round(saved / orig * 100, 1) if orig else 0.0}

def sweep(project_id):
    try:
        rows = db.select("tasks", {
            "select": "id,slug,prompt,note",
            "project_id": f"eq.{project_id}",
            "state": "in.(DONE,MERGED)",
            "order": "updated_at.desc", "limit": str(SAMPLE_LIMIT),
        }) or []
    except Exception:
        return {"tasks_analysed": 0, "conventions_found": [], "total_potential_savings": {}}
    prompts = [r.get("prompt", "") for r in rows]
    conventions = extract_conventions(prompts)
    total_orig = sum(_estimate_tokens(p) for p in prompts)
    total_dist = sum(_estimate_tokens(distill_prompt(p)) for p in prompts)
    return {
        "tasks_analysed": len(rows), "conventions_found": conventions,
        "total_potential_savings": {
            "original_tokens": total_orig, "distilled_tokens": total_dist,
            "tokens_saved": total_orig - total_dist,
            "savings_pct": round((total_orig - total_dist) / total_orig * 100, 1) if total_orig else 0.0,
        },
    }

def record_savings(project_id, savings):
    try:
        db.upsert("controls", {"key": f"distill_savings_{project_id}", "value": json.dumps(savings)})
    except Exception:
        pass
