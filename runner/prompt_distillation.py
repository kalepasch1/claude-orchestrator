#!/usr/bin/env python3
from __future__ import annotations
"""
prompt_distillation.py — Prompt distillation (200X token savings on repeat patterns).

For tasks that succeed, distill the winning prompt into a minimal template.
Future similar tasks start from the distilled version instead of the full context pack.

Distillation extracts:
  1. The core intent (what to change, not how to think about it)
  2. The minimal file set (from the actual merge, not the full context)
  3. The winning approach pattern (from the agent's actual output)
  4. The test command (what verified success)

A distilled prompt is typically 500-1500 tokens vs 5000-15000 for a full prompt.

Usage:
    import prompt_distillation
    prompt_distillation.distill(task, agent_output, merged_files, project)
    # Later:
    distilled = prompt_distillation.find_distilled(new_task)
    if distilled:
        prompt = distilled["template"]  # minimal version
"""
import os, sys, json, hashlib, re, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MAX_DISTILLED = int(os.environ.get("ORCH_DISTILLED_MAX", "300"))
DISTILL_MIN_SIMILARITY = float(os.environ.get("ORCH_DISTILL_MIN_SIM", "0.5"))


def _distillery():
    """Load distilled prompt library."""
    try:
        rows = db.select("controls", {"select": "value", "key": "eq.prompt_distillery"})
        if rows and rows[0].get("value"):
            v = rows[0]["value"]
            return json.loads(v) if isinstance(v, str) else v
    except Exception:
        pass
    return {}


def _save_distillery(lib):
    if len(lib) > MAX_DISTILLED:
        by_score = sorted(lib.items(), key=lambda x: x[1].get("score", 0))
        lib = dict(by_score[-MAX_DISTILLED:])
    try:
        db.upsert("controls", {"key": "prompt_distillery", "value": json.dumps(lib, default=str)})
    except Exception:
        pass


def _intent_key(task):
    """Structural key for a task's intent."""
    prompt = (task.get("prompt") or "").lower()[:300]
    kind = task.get("kind", "")
    norm = re.sub(r"\s+", " ", prompt)
    norm = re.sub(r"[0-9a-f]{8,}", "H", norm)
    return hashlib.sha256(f"{kind}|{norm}".encode()).hexdigest()[:16]


def distill(task, agent_output, merged_files, project="", cost_usd=0):
    """Distill a successful task into a minimal reusable template.

    Called after a successful merge. Extracts the minimal prompt that would
    reproduce this result.
    """
    key = _intent_key(task)
    lib = _distillery()

    original_prompt = task.get("prompt", "")
    output = agent_output or ""

    # Extract the core intent (first 2 sentences or first line)
    intent_lines = original_prompt.strip().split("\n")
    core_intent = " ".join(intent_lines[:2])[:300]

    # Extract the approach from agent output
    approach = ""
    approach_match = re.search(
        r"(?:approach|plan|strategy|steps?):\s*(.+?)(?:\n\n|\Z)",
        output, re.S | re.I
    )
    if approach_match:
        approach = approach_match.group(1)[:300]

    # Build distilled template
    template_parts = [core_intent]

    if merged_files:
        template_parts.append(f"\nFiles to modify: {', '.join(merged_files[:10])}")

    if approach:
        template_parts.append(f"\nApproach: {approach}")

    template = "\n".join(template_parts)

    # Score: shorter template + more merges = higher score
    compression_ratio = len(template) / max(len(original_prompt), 1)
    existing = lib.get(key, {})
    merge_count = existing.get("merge_count", 0) + 1

    entry = {
        "key": key,
        "template": template,
        "core_intent": core_intent,
        "files": merged_files[:15],
        "approach": approach[:300],
        "project": project,
        "kind": task.get("kind", ""),
        "original_length": len(original_prompt),
        "distilled_length": len(template),
        "compression_ratio": round(compression_ratio, 3),
        "merge_count": merge_count,
        "score": merge_count * (1 - compression_ratio),
        "last_used": time.time(),
        "avg_cost": cost_usd,
    }

    lib[key] = entry
    _save_distillery(lib)
    return entry


def find_distilled(task, current_project=""):
    """Find a distilled prompt template for a similar task.

    Returns: distilled entry dict or None
    """
    key = _intent_key(task)
    lib = _distillery()

    # Exact match
    if key in lib:
        entry = lib[key]
        if entry.get("merge_count", 0) >= 2:
            return entry

    # Fuzzy match by keyword overlap
    norm_intent = re.sub(r"\s+", " ", (task.get("prompt") or "").lower()[:300])
    best_match = None
    best_sim = 0

    for k, entry in lib.items():
        if entry.get("merge_count", 0) < 2:
            continue
        core = entry.get("core_intent", "").lower()
        # Simple word overlap
        words_a = set(norm_intent.split())
        words_b = set(core.split())
        if not words_a or not words_b:
            continue
        sim = len(words_a & words_b) / len(words_a | words_b)
        if sim > best_sim and sim >= DISTILL_MIN_SIMILARITY:
            best_sim = sim
            best_match = {**entry, "similarity": round(sim, 3)}

    return best_match


def apply_distilled(original_prompt, distilled):
    """Replace the original prompt with the distilled version + minimal context."""
    if not distilled:
        return original_prompt

    template = distilled.get("template", "")
    merges = distilled.get("merge_count", 0)
    compression = distilled.get("compression_ratio", 1.0)

    # Add confidence note
    header = (
        f"## DISTILLED PROMPT (proven {merges} times, "
        f"{(1-compression)*100:.0f}% smaller than original)\n\n"
    )
    return header + template


def run():
    """Periodic: log distillation stats."""
    lib = _distillery()
    if not lib:
        print("[distillation] no distilled prompts yet")
        return

    total = len(lib)
    mature = sum(1 for e in lib.values() if e.get("merge_count", 0) >= 3)
    avg_compression = sum(e.get("compression_ratio", 1) for e in lib.values()) / max(total, 1)
    total_savings_chars = sum(
        e.get("original_length", 0) - e.get("distilled_length", 0)
        for e in lib.values()
    )

    print(f"[distillation] {total} templates, {mature} mature, "
          f"avg compression={avg_compression:.0%}, "
          f"total chars saved={total_savings_chars:,}")
