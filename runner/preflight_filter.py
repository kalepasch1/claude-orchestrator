#!/usr/bin/env python3
"""
preflight_filter.py — Pre-dispatch quality gate for the orchestrator.

Standalone module that catches non-actionable tasks BEFORE they consume execution
slots. Called by parallel_dispatch.py (batch dispatch) and db.py (serial claim).

Categories detected:
1. PATCH TEMPLATE garbage prompts (hex-only stubs)
2. Recycled/looped tasks (already quarantined, deduped, or failed)
3. Exhausted attempts (4+ attempts without success)
4. Non-actionable prompts (too short, empty)
5. Blocker-quarantine candidates (legal/security with no code target)
6. Metadata-only prompts (orchestration boilerplate with no implementation spec)
"""
import re, os, logging

log = logging.getLogger(__name__)

_GARBAGE_PROMPT_RE = re.compile(
    r"PATCH TEMPLATE [0-9a-f]|patch-template-corrupt|^[\s#\-\*]*$", re.I)

_RECYCLED_NOTE_RE = re.compile(
    r"swarm-parallel-fail|legacy direct improvement|Meta-decomposition loop|"
    r"queue-bankruptcy|sentinel-dedupe|semantic-dedupe|non-actionable:|"
    r"preflight:|GC:", re.I)

SKIP_NOTE_PATTERNS = (
    "swarm-parallel-fail", "legacy direct improvement",
    "Meta-decomposition loop", "queue-bankruptcy",
    "sentinel-dedupe", "semantic-dedupe", "preflight:",
    "non-actionable:", "GC:",
)

_BLOCKER_KEYWORDS_RE = re.compile(
    r"\b(legal|compliance|license|GDPR|privacy\s+policy|terms\s+of\s+service|"
    r"secret|credential|API\s+key|password|token|private\s+key|"
    r"classified|restricted|confidential|NDA)\b", re.I)

_HAS_CODE_TARGET_RE = re.compile(
    r"\b(function|class|method|module|file|import|endpoint|route|handler|"
    r"component|service|controller|model|schema|migration|test|spec|"
    r"\.py|\.js|\.ts|\.jsx|\.tsx|\.go|\.rs|\.java|\.rb|\.sql)\b", re.I)

_METADATA_ONLY_RE = re.compile(
    r"^(- source:|- project:|- task class:|- preflight|- strategy|"
    r"##\s+ORCHESTRATION|##\s+PIPELINE|spend-limit|repair directive)", re.I | re.MULTILINE)


def preflight_check(task: dict) -> str:
    """Return '' if task is dispatchable, or a quarantine reason string."""
    prompt = str(task.get("prompt") or "")
    note = str(task.get("note") or "")
    attempt = task.get("attempt") or 0

    if _GARBAGE_PROMPT_RE.search(prompt):
        return "preflight: PATCH TEMPLATE or garbage prompt (auto-quarantine)"
    if _RECYCLED_NOTE_RE.search(note):
        return f"preflight: recycled task ({note[:80]})"
    max_attempts = int(os.environ.get("ORCH_PREFLIGHT_MAX_ATTEMPTS", "4"))
    if attempt >= max_attempts:
        return f"preflight: exhausted {attempt} attempts without success"

    body = prompt
    for marker in ("## ORCHESTRATION PIPELINE CONTRACT", "## TASK", "## OBJECTIVE"):
        idx = body.find(marker)
        if idx >= 0:
            body = body[idx:]
    lines = [l for l in body.split("\n") if l.strip()
             and not l.startswith("- source:")
             and not l.startswith("- project:")
             and not l.startswith("- task class:")
             and not l.startswith("- preflight")
             and not l.startswith("- strategy")]
    if len(lines) < 2 and len(prompt) < 80:
        return "preflight: prompt too short/empty to be actionable"
    if _BLOCKER_KEYWORDS_RE.search(prompt) and not _HAS_CODE_TARGET_RE.search(prompt):
        non_meta_lines = [l for l in lines if not _METADATA_ONLY_RE.match(l)]
        if len(non_meta_lines) < 3:
            return "preflight: blocker-category (legal/security/secret) with no code target"
    if prompt and all(_METADATA_ONLY_RE.match(l.strip()) for l in prompt.strip().split("\n") if l.strip()):
        return "preflight: metadata-only prompt with no implementation spec"
    return ""


def should_skip_note(note: str) -> bool:
    """Check if a task's note indicates it should be skipped during claiming."""
    return any(pat in note for pat in SKIP_NOTE_PATTERNS)


def apply_to_batch(tasks: list, quarantine_fn=None) -> tuple:
    """Filter a batch of tasks, quarantining non-actionable ones."""
    dispatchable = []
    killed = 0
    for t in tasks:
        reason = preflight_check(t)
        if reason:
            if quarantine_fn:
                try:
                    quarantine_fn(t, reason)
                except Exception:
                    dispatchable.append(t)
                    continue
            killed += 1
            log.info("preflight: quarantine %s: %s", t.get("slug", "?"), reason)
        else:
            dispatchable.append(t)
    if killed:
        log.info("preflight: killed %d/%d tasks in batch", killed, len(tasks))
    return dispatchable, killed
