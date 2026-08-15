#!/usr/bin/env python3
"""Automatic sub-subtask slicing before expensive agentic work."""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

AI_SLICE_MODEL = os.environ.get("ORCH_AI_SLICE_MODEL", "claude-haiku-4-5-20251001")
_AI_SLICE_PROMPT = """\
You are a task decomposition assistant for an autonomous code orchestration system.
Break the following task prompt into {n} independent sub-tasks that can be worked
on sequentially. Each sub-task should be a self-contained unit of work.

Return ONLY a JSON array with {n} objects, each with:
  "title": short kebab-case suffix (will be appended to the parent slug)
  "prompt": the full sub-task prompt (copy relevant context from the parent)

Keep titles under 20 chars. Do not include explanations outside the JSON.

Parent slug: {slug}
Parent prompt:
{prompt}
"""

THRESHOLD = int(os.environ.get("ORCH_SLICE_PROMPT_CHARS", "2400"))
MAX_PARTS = int(os.environ.get("ORCH_SLICE_MAX_PARTS", "5"))
MAX_DEPTH = int(os.environ.get("ORCH_SLICE_MAX_DEPTH", "1"))
MARK = "auto-sliced-before-agent"
AI_SLICE_MODEL = os.environ.get("ORCH_AI_SLICE_MODEL", "claude-haiku-4-5-20251001")
PROTECTED_PREFIXES = (
    "qafix-", "relfix-", "buildfix-", "deployfix-",
    "recover-missing-branch-", "rework-", "canary-",
)


# SLICING A PROMPT WITH NO IMPLEMENTATION INTENT MANUFACTURES GARBAGE (2026-08-06).
#
# backlog-batch-beethoven-18fa8e4 was a prompt made ENTIRELY of retrieval scaffolding:
# "PATCH TEMPLATE b28aba37e6cd", "Intent: 0343183 056af630dd5f 07062319 ... abstract
# acceptance across actionable", "SOURCE x/y similarity=0.303", an ORCHESTRATION
# PIPELINE CONTRACT block, and generic advice lines. It tripped should_slice() on length
# alone and was cut into five children. The children were not tasks. slice-3's entire
# prompt is "- Locate the existing owner module/function before adding new files."
# slice-4's entire prompt begins "- 2.".
#
# One unworkable task became five, each of which then burned attempts, requeues and
# agentic-repair cycles of its own. The quarantine gate did not catch them because it
# only rejects hex-ONLY stubs and these contain stray English.
#
# The fix is upstream: refuse to slice what has no implementation intent to divide.
_SCAFFOLD_PATTERNS = (
    r"^\s*[-*]?\s*PATCH TEMPLATE\s+[0-9a-f]{6,}\s*$",
    r"^\s*[-*]?\s*PATCH TRANSPLANT:.*$",
    r"^\s*[-*]?\s*Intent:.*$",
    r"^\s*[-*]?\s*Acceptance:.*$",
    r"^\s*[-*]?\s*SOURCE\s+\S+\s+similarity=[\d.]+.*$",
    r"^\s*[-*]?\s*SUMMARY:.*$",
    r"^\s*[-*]?\s*\S+/\S+\s+sim=[\d.]+.*$",
    r"^\s*#+\s*(END\s+)?ORCHESTRATION PIPELINE CONTRACT\s*$",
    r"^\s*#+\s*(END\s+)?OPERATOR PHANTOM RECOVERY CONTRACT\s*$",
    r"^\s*\[patch-template:[0-9a-f]+\]\s*$",
    r"^\s*[-*]?\s*(MERGED-DIFF LIBRARY|REUSE FIRST|OPERATOR_PHANTOM_RECOVERY)\b.*$",
    # pipeline metadata: "- strategy planner: local:deepseek-coder-v2:16b (qpd leader ...)"
    r"^\s*[-*]?\s*(source|project|task class|preflight triage|strategy planner|agentic coder|"
    r"independent QA route|QA panel|legal gate|merge/release|coordination rule|"
    r"cross-learning context|learned route|operator feedback|recent outcome signal|"
    r"Repair category|Original task slug|Parent task|Original slug|Collapsed queued tasks|"
    r"Touched files from prior run|Prior commit SHA|Preflight scope concern)\s*:.*$",
    # bare enumerators the sentence splitter leaves behind: "3.", "- 2."
    r"^\s*[-*]?\s*\d+\.\s*$",
    r"^\s*[-*]?\s*`{0,3}(diff|```)?\s*$",
)
_SCAFFOLD_RE = re.compile("|".join(_SCAFFOLD_PATTERNS), re.IGNORECASE | re.MULTILINE)

# Generic process advice that is true of every task and therefore identifies none.
_BOILERPLATE_ADVICE = (
    "preserve existing behavior", "make the smallest mergeable diff", "run build/tests",
    "implementation slots", "locate the existing owner module", "reuse matching project",
    "add or update the narrowest test", "prior merged patterns to adapt",
    "adapt it instead of rebuilding", "before drafting", "do not add new scope",
    "reproduce or inspect the concrete failure", "this is not a fresh requeue",
    "commit the final implementation on the task branch",
    "required completion behavior", "agentic analysis artifacts from prior run",
    "prior patch diff", "failure context", "original prompt", "original improvement request",
)

# A slice must carry at least this much genuinely task-specific text to be worth a run.
MIN_INTENT_CHARS = int(os.environ.get("ORCH_SLICE_MIN_INTENT_CHARS", "120"))


def _strip_scaffolding(prompt):
    """Remove retrieval/pipeline scaffolding and generic advice, leaving real intent."""
    text = _SCAFFOLD_RE.sub("", str(prompt or ""))
    kept = []
    for line in text.splitlines():
        stripped = line.strip(" -*\t")
        if not stripped:
            continue
        low = stripped.lower()
        if any(phrase in low for phrase in _BOILERPLATE_ADVICE):
            continue
        # "Intent:" soup survives as bare token runs — long lines of short lowercase/hex
        # words with no punctuation. Real prose has punctuation or long words.
        words = stripped.split()
        if len(words) >= 8 and not any(c in stripped for c in ".,:;()/"):
            if sum(1 for w in words if len(w) <= 12) / len(words) > 0.9:
                continue
        kept.append(stripped)
    return "\n".join(kept)


def has_implementation_intent(prompt):
    """True when a prompt says something specific enough to implement.

    Deliberately permissive: it only has to find SOME task-specific substance after the
    scaffolding is removed. The failure mode being prevented is a prompt that is 100%
    template, not a prompt that is merely terse.
    """
    residue = _strip_scaffolding(prompt)
    return len(residue) >= MIN_INTENT_CHARS


def has_any_intent(prompt):
    """True when ANY task-specific text survives scaffolding removal.

    The weaker sibling of has_implementation_intent, for output that was authored rather
    than mechanically cut: a model asked for self-contained sub-prompts can legitimately
    return a terse one ("Add a --dry-run flag to runner/janitor.py."), and a length floor
    would reject it. What must still be rejected is a child made ONLY of boilerplate.
    """
    return bool(_strip_scaffolding(prompt).strip())


def should_slice(task):
    if not isinstance(task, dict):
        return False
    if os.environ.get("ORCH_AUTO_SLICE", "true").lower() not in ("1", "true", "yes", "on"):
        return False
    if MARK in str(task.get("note") or ""):
        return False
    slug = str(task.get("slug") or "")
    if slug.startswith(PROTECTED_PREFIXES):
        return False
    if slug.count("-slice-") >= MAX_DEPTH:
        return False
    prompt = str(task.get("prompt") or "")
    if not (len(prompt) >= THRESHOLD or prompt.count("\n- ") >= 6
            or prompt.lower().count(" and ") >= 8):
        return False
    # Length is not intent. A long prompt with nothing implementable in it must reach the
    # agent (or the quarantine gate) whole, so ONE task fails visibly instead of five.
    return has_implementation_intent(prompt)


def _sentences(prompt):
    chunks = [c.strip(" -\n\t") for c in re.split(r"\n\s*[-*]\s+|(?<=[.!?])\s+", prompt) if c.strip()]
    return chunks or [prompt]


def _is_actionable_group(chunks):
    """A slice must carry real intent of its own, not just inherited scaffolding.

    Uses the WEAKER gate on purpose. MIN_INTENT_CHARS decides whether a whole prompt is
    worth dividing; applying it per group would discard legitimately small steps ("Step 4:
    edit runner/x.py and update its test.") and silently lose requested work — a worse
    failure than the boilerplate children this is meant to stop. A group only has to say
    something task-specific.
    """
    return has_any_intent("\n".join(chunks))


def slice_task(task):
    prompt = str(task.get("prompt") or "")
    chunks = _sentences(prompt)
    if len(chunks) <= 1:
        return []
    n_groups = min(MAX_PARTS, max(2, len(chunks) // 2))
    # CONTIGUOUS, NOT ROUND-ROBIN (2026-08-06). This used to deal chunks out with
    # `groups[i % len(groups)]`, which scatters adjacent sentences into different slices —
    # so step 1 of a procedure landed in slice-1 and step 2 in slice-2, each stripped of
    # the other's context. Whatever order the prompt was written in is the only ordering
    # signal available; contiguous blocks preserve it.
    base_size, extra = divmod(len(chunks), n_groups)
    groups, cursor = [], 0
    for idx in range(n_groups):
        size = base_size + (1 if idx < extra else 0)
        groups.append(chunks[cursor:cursor + size])
        cursor += size
    parts = []
    base = str(task.get("slug") or task.get("id") or "task")[:50]
    prev = None
    for group in groups:
        if not group or not _is_actionable_group(group):
            continue  # never insert a child whose whole prompt is boilerplate
        title = f"{base}-slice-{len(parts) + 1}"
        body = "\n".join(f"- {g}" for g in group)
        deps = [prev] if prev else []
        parts.append({"slug": title, "prompt": body, "deps": deps})
        prev = title
    # One survivor is not a decomposition — let the parent run whole instead.
    return parts if len(parts) >= 2 else []


def ai_slice_task(task):
    """Use Claude to decompose a task into semantically meaningful slices.

    Returns the same format as slice_task() — list of {"slug", "prompt", "deps"} dicts —
    or None if AI slicing is disabled, fails, or produces unusable output.

    Credentials come exclusively from the environment via claude_cli; no hardcoded keys.
    """
    if os.environ.get("ORCH_AI_SLICE", "false").lower() not in ("1", "true", "yes", "on"):
        return None
    try:
        import claude_cli
    except ImportError:
        return None

    prompt = str(task.get("prompt") or "")
    slug = str(task.get("slug") or task.get("id") or "task")
    n = min(MAX_PARTS, max(2, len(prompt) // 800))
    ai_prompt = _AI_SLICE_PROMPT.format(n=n, slug=slug, prompt=prompt[:6000])
    try:
        result = claude_cli.run(ai_prompt, AI_SLICE_MODEL, max_turns=1, timeout=60)
        raw = (result.get("text") or "").strip()
    except Exception:
        return None

    match = re.search(r"\[.*?\]", raw, re.DOTALL)
    if not match:
        return None
    try:
        items = json.loads(match.group(0))
    except Exception:
        return None
    if not isinstance(items, list) or len(items) < 2:
        return None

    base = slug[:50]
    parts = []
    prev = None
    for idx, item in enumerate(items[:MAX_PARTS]):
        if not isinstance(item, dict):
            continue
        body = str(item.get("prompt") or "").strip()
        if not body or not has_any_intent(body):
            continue  # no boilerplate-only children, but terse authored slices are fine
        slice_slug = f"{base}-slice-{len(parts) + 1}"
        deps = [prev] if prev else []
        parts.append({"slug": slice_slug, "prompt": body, "deps": deps})
        prev = slice_slug

    return parts if len(parts) >= 2 else None


def _slice_exists(task, slug):
    """True if a slice row with this slug already exists for the task's project (any state)."""
    try:
        rows = db.select("tasks", {"select": "id",
                                   "project_id": f"eq.{task.get('project_id')}",
                                   "slug": f"eq.{slug}",
                                   "limit": "1"}) or []
        return bool(rows)
    except Exception:
        # DB unreachable: report absent so the normal path (which is also fail-soft) proceeds.
        return False


def pre_agent_hook(task):
    if not isinstance(task, dict) or not should_slice(task):
        return False
    parts = ai_slice_task(task) or slice_task(task)
    if len(parts) < 2:
        return False
    # Idempotency guard (2026-07-10): the parent used to flip to DECOMPOSED only AFTER the
    # slice inserts. Any DB blip on that final update left a QUEUED parent that re-sliced on
    # the next claim, re-inserting the same 5 slugs — the dominant source of sentinel-dedupe
    # quarantines (235/255 quarantined rows on 2026-07-09/10 were *-slice-N). If slices
    # already exist, just finish flipping the parent.
    if _slice_exists(task, parts[0]["slug"]):
        try:
            db.update("tasks", {"id": task["id"]},
                      {"state": "DECOMPOSED", "updated_at": "now()",
                       "note": f"{MARK}: slices already present; parent flip retried"})
        except Exception:
            pass
        return True
    # Flip the parent BEFORE inserting slices so a mid-insert failure can never leave a
    # QUEUED parent alongside live slices. If the flip itself fails, do nothing this cycle.
    try:
        db.update("tasks", {"id": task["id"]},
                  {"state": "DECOMPOSED", "updated_at": "now()",
                   "note": f"{MARK}: spawning {len(parts)} sub-subtasks"})
    except Exception:
        return False
    inserted = 0
    for part in parts:
        row = {"project_id": task.get("project_id"), "slug": part["slug"],
               "kind": task.get("kind") or "build", "state": "QUEUED",
               "prompt": part["prompt"] + f"\n\nParent task: {task.get('slug')}",
               "deps": part["deps"], "base_branch": task.get("base_branch"),
               "note": f"{MARK}: parent={task.get('slug')}"}
        try:
            if _slice_exists(task, part["slug"]):
                inserted += 1  # already landed on a previous attempt
                continue
            _insert_task(row)
            inserted += 1
        except Exception:
            pass
    if not inserted:
        # Nothing landed — restore the parent so the work isn't silently lost.
        try:
            db.update("tasks", {"id": task["id"]},
                      {"state": "QUEUED", "updated_at": "now()",
                       "note": f"{MARK}: slice inserts failed; parent restored"})
        except Exception:
            pass
        return False
    return True


def _insert_task(row):
    variants = [
        row,
        {k: v for k, v in row.items() if k != "deps"},
        {k: v for k, v in row.items() if k not in ("deps", "base_branch")},
    ]
    for candidate in variants:
        try:
            db.insert("tasks", candidate)
            return True
        except Exception:
            continue
    raise RuntimeError("no compatible task insert shape")
