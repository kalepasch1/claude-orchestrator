#!/usr/bin/env python3
from __future__ import annotations
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
    """Return '' if task is dispatchable, or a quarantine reason string.

    E: the verdict is recorded for liveness. A preflight that starts quarantining
    (or passing) essentially everything is a bug, and now alarms within a day.
    """
    verdict = _preflight_check_inner(task)
    try:
        import gate_liveness
        gate_liveness.record("preflight", verdict or "pass", task.get("slug"), verdict or None)
    except Exception:
        pass
    return verdict


def _preflight_check_inner(task: dict) -> str:
    prompt = str(task.get("prompt") or "")
    note = str(task.get("note") or "")
    attempt = task.get("attempt") or 0

    # 2026-07-22: strip MERGED-DIFF LIBRARY preamble before garbage check.
    # The library injects prior diffs that may contain "PATCH TEMPLATE" text
    # from old tasks — matching on those false-positives quarantines real work.
    _check_prompt = prompt
    for _lib_marker in ("## ORCHESTRATION PIPELINE CONTRACT", "## TASK", "## OBJECTIVE"):
        _lib_idx = _check_prompt.find(_lib_marker)
        if _lib_idx >= 0:
            _check_prompt = _check_prompt[_lib_idx:]
            break
    else:
        # No marker found — if it starts with "MERGED-DIFF LIBRARY", skip that block
        if _check_prompt.startswith("MERGED-DIFF LIBRARY"):
            _eol = _check_prompt.find("\n\n")
            if _eol > 0:
                _check_prompt = _check_prompt[_eol + 2:]

    # 2026-07-31: "PATCH TEMPLATE <hex>" also occurs INSIDE legitimate bodies
    # (merged-diff-library excerpts, patch-transplant prior-diff quotes) — that
    # cost 10 real 5KB work prompts today. A genuine garbage stub has the marker
    # near the TOP of a SHORT stripped body; embedded occurrences deep in a long
    # real prompt are evidence of reuse, not garbage.
    _gm = _GARBAGE_PROMPT_RE.search(_check_prompt)
    if _gm and (_gm.start() < 120 or len(_check_prompt.strip()) < 500):
        return "preflight: PATCH TEMPLATE or garbage prompt (auto-quarantine)"
    if _RECYCLED_NOTE_RE.search(note):
        return f"preflight: recycled task ({note[:80]})"
    # ATTEMPT COUNT ALONE MUST NOT CONDEMN A WELL-SPECIFIED TASK (2026-08-15).
    #
    # This quarantined anything that had failed 4 times. Audited today: 139 tasks were destroyed
    # by this rule, every one in the cowork lane, and every one carrying a real specification —
    # prompt lengths from 1,311 to 25,230 characters, median 5,985. Not one was a garbage stub.
    # That single rule is most of the cowork lane's 45% completion rate.
    #
    # An attempt is consumed by ANY failure, and this fleet spent months failing for reasons
    # that had nothing to do with the task: a merge train wedged behind an orphaned lock, gates
    # timing out inside their own telemetry, scan windows hiding most of the queue, cross-host
    # push races. Counting those against the task and then deleting its prompt is how a
    # 6,000-character brief becomes nothing at all.
    #
    # So the rule now needs BOTH signals: repeated failure AND a thin prompt. A thin prompt that
    # keeps failing really is unactionable. A detailed one that keeps failing is evidence about
    # the fleet, and the right response is to keep it and fix the fleet. Substantial specs still
    # face a hard ceiling, so nothing retries forever.
    max_attempts = int(os.environ.get("ORCH_PREFLIGHT_MAX_ATTEMPTS", "4"))
    hard_ceiling = int(os.environ.get("ORCH_PREFLIGHT_HARD_CEILING", "12"))
    substantial = int(os.environ.get("ORCH_PREFLIGHT_SUBSTANTIAL_CHARS", "500"))
    _is_substantial = len((prompt or "").strip()) >= substantial
    if attempt >= hard_ceiling:
        return (f"preflight: exhausted {attempt} attempts without success "
                f"(hard ceiling {hard_ceiling})")
    if attempt >= max_attempts and not _is_substantial:
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
