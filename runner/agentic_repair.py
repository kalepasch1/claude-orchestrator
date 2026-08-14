#!/usr/bin/env python3
"""Same-task agentic repair helpers.

repair_patch(): build a db.update patch that re-queues a task in place, with an
agentic-repair prompt instead of the original. Used by auto_remediate, merge_train,
queue_janitor, blocker_quarantine, and runner.

in_session_prompt(): build the repair prompt string for callers that inject it
directly into a live in-session task dict (runner._agentic_repair_continue).
"""
import os

MARKER = "AGENTIC-REPAIR DIRECTIVE"

# --- Repair termination -----------------------------------------------------------------
# Every repair path in the fleet (auto_remediate, merge_train, queue_janitor, periodic,
# blocker_quarantine, approval_merge, runner) funnels through repair_patch(). Individual call
# sites cap themselves with `transient_retries`, but that counter is per-cause and some sites
# preserve rather than increment it, so nothing bounded the TOTAL number of times a single task
# could be re-queued. Measured 2026-08-03: live tasks at remediation_count 19, 21, 23, 24, 26, 28
# — several with attempt=0, i.e. repaired two dozen times without ever running. ~700 repair
# cycles on the live queue were spent on tasks past any plausible convergence point, which is a
# large part of why the fleet generated 67 tasks/hr and completed 8.
#
# Two ceilings, both enforced here so no call site can bypass them:
#   GLOBAL  — a task repaired this many times is not converging; park it for a human/QA agent.
#   BLIND   — a repair with NO failure evidence (empty note and log_tail) is a guess. Guessing
#             repeatedly cannot converge, so blind repairs get a much lower ceiling.
GLOBAL_REPAIR_CEILING = int(os.environ.get("ORCH_GLOBAL_REPAIR_CEILING", "8"))
BLIND_REPAIR_CEILING = int(os.environ.get("ORCH_BLIND_REPAIR_CEILING", "4"))

TERMINAL_NOTE_PREFIX = "repair-ceiling:"

_DEFAULT_DIRECTIVE = (
    "Reproduce or inspect the concrete failure before changing broad strategy. "
    "Preserve any useful prior work, repair the root cause, run the relevant checks, and commit."
)


_REPAIR_CODER_FALLBACK = "claude"

# Original prompts are bounded before a repair directive is appended, so N repairs can never
# compound into an unboundedly large prompt (live tasks have reached 28 repairs).
MAX_PROMPT_CHARS = int(os.environ.get("ORCH_REPAIR_MAX_PROMPT_CHARS", "24000"))

# Categories with a concrete technical signal a coder can act on directly.
_TECHNICAL_CATEGORIES = frozenset(
    ("buildfail", "testfail", "timeout", "conflict", "regressfail", "missing-branch"))

# Categories where the blocked mechanism must be REPLACED with a safe variant rather than
# retried verbatim (legal posture, leaked/secret-shaped content, security findings).
_REPLACEMENT_CATEGORIES = frozenset(("legal", "secret", "security"))


def is_technical(category):
    """True when the repair category carries a concrete technical failure signal."""
    return str(category or "").lower() in _TECHNICAL_CATEGORIES


def replacement_required(category):
    """True when the category means the prior mechanism must not be retried verbatim."""
    return str(category or "").lower() in _REPLACEMENT_CATEGORIES


def _default_coder():
    """Coder used when the task itself doesn't pin one (env override first)."""
    env = os.environ.get("ORCH_REPAIR_CODER") or os.environ.get("ORCH_AGENTIC_REPAIR_DEFAULT_CODER")
    if env:
        return env
    return os.environ.get("ORCH_REPAIR_CODER_FALLBACK", _REPAIR_CODER_FALLBACK)


def choose_coder(task, avoid=None):
    """Return the coder to use for agentic repair of this task.

    Priority: task force_coder > task model (non-claude) >
    ORCH_AGENTIC_REPAIR_DEFAULT_CODER > agentic_coders.pick() >
    ORCH_REPAIR_CODER_FALLBACK (default: "claude").  Never hardcodes "ollama"
    so a missing local Ollama server cannot wedge the repair queue.

    `avoid`, when given, is an iterable of coder names that must not be reselected.
    Used when a task is being repaired specifically because it didn't finish
    (orphaned/stuck RUNNING) -- see repair_patch()'s prefer_non_claude -- so the
    vendor that just failed to finish it doesn't just get handed the same task back.
    """
    task = task or {}
    avoid = {str(a) for a in (avoid or []) if a}
    forced = task.get("force_coder")
    if forced and str(forced) not in avoid:
        return forced
    model = task.get("model")
    if model and not str(model).startswith("claude") and str(model) not in avoid:
        return model
    default = os.environ.get("ORCH_AGENTIC_REPAIR_DEFAULT_CODER")
    if default and default not in avoid:
        return default
    fallback = os.environ.get("ORCH_REPAIR_CODER_FALLBACK", _REPAIR_CODER_FALLBACK)
    try:
        import agentic_coders  # type: ignore
        task_for_pick = dict(task)
        if avoid:
            task_for_pick["_avoid_coders"] = sorted(avoid)
        picked = agentic_coders.pick(task_for_pick)
        if picked and str(picked) not in avoid:
            return picked
        return fallback
    except Exception:
        return fallback


def original_prompt(task):
    """The task's prompt with every previously-appended repair directive removed.

    in_session_prompt() appends a ~1.5KB directive block to whatever prompt it is given, and it is
    given the CURRENT prompt — which is usually the output of the last repair. So a task repaired
    N times carried N stacked directives, each contradicting the last ("continue the same
    implementation" after "use this revised smaller plan" after "re-scope into the smallest
    visible change"), with the actual work buried at the top. Live tasks reached 28 repairs.
    Stripping at the first marker restores the original text exactly, so a repaired prompt always
    carries exactly one directive: the current one.
    """
    text = str(task.get("prompt") or "")
    cut = text.find("\n\n" + MARKER + "\n")
    return (text[:cut] if cut != -1 else text).strip()[:MAX_PROMPT_CHARS]


# Compat aliases for callers/tests that use the underscore-private name and the
# repair_prompt() spelling of the in-session prompt builder.
_original_prompt = original_prompt


def repair_prompt(task, failure, directive=None, category="rework"):
    """Build the full repair prompt string (alias over in_session_prompt)."""
    return in_session_prompt(task, failure, category=category, directive=directive)


def in_session_prompt(task, failure, category="rework", directive=None):
    directive = directive or _DEFAULT_DIRECTIVE
    base = original_prompt(task) or f"Complete the task '{task.get('slug')}'."
    touched = task.get("touched_files") or "unknown"
    sha = task.get("commit_sha") or "unknown"
    log = str(task.get("log_tail") or task.get("note") or failure or "")[:1000]
    diff = str(failure or "")[:2000]
    repair = (
        f"\n\n{MARKER}\n"
        f"Repair category: {category}\n"
        f"Original task slug: {task.get('slug') or task.get('id')}\n\n"
        f"This is not a fresh requeue. Continue the same implementation to completion. "
        f"Preserve any useful prior work, inspect the existing branch/worktree/artifacts first, "
        f"and fix the root cause of the failure below.\n\n"
        f"{directive}\n\n"
        f"Required completion behavior:\n"
        f"- Reproduce or inspect the concrete failure before changing broad strategy.\n"
        f"- If dependencies/build tools are missing, repair the repo setup or install path minimally.\n"
        f"- If tests/build fail, fix source/config/tests until the relevant checks are green.\n"
        f"- If the branch/worktree is missing, reconstruct the smallest equivalent patch from artifacts, templates, or prior diffs.\n"
        f"- Commit the final implementation on the task branch. Do not finish with only analysis, a plan, or no file changes.\n\n"
        f"Agentic analysis artifacts from prior run:\n"
        f"Touched files from prior run: {touched}\n"
        f"Prior commit SHA: {sha}\n"
        f"Prior patch diff (truncated):\n```diff\n{diff}\n```\n\n"
        f"Failure context:\n```\n{log}\n```\n\n"
        f"bugfix"
    )
    return base + repair


def evidence_text(task, signal=""):
    """Return the diagnostic evidence available for a repair, with bookkeeping stripped.

    A task's own note after a prior repair is literally "agentic-repair:<category>", and its slug
    appears in every generated prompt. Neither says anything about what went wrong, so both are
    removed before deciding whether we actually have evidence. What remains is agent output, a
    traceback, a build log, or a concrete merge/branch condition — the things a repair can act on.
    """
    text = " ".join(str(x or "") for x in (signal, task.get("note"), task.get("log_tail")))
    text = text.replace(TERMINAL_NOTE_PREFIX, " ")
    for cat in ("missing-branch", "orphaned-running", "regressfail", "buildfail", "testfail",
                "transient", "conflict", "capacity", "rework", "noop", "flake"):
        text = text.replace("agentic-repair:" + cat, " ")
    text = text.replace("agentic-repair:", " ")
    slug = str(task.get("slug") or "")
    if slug:
        text = text.replace(slug, " ")
    return text.strip()


def has_evidence(task, signal=""):
    """True when a repair has something concrete to act on rather than a name and a counter."""
    return len(evidence_text(task, signal)) >= 24


def _terminal_patch(task, category, rc, blind, signal=""):
    """Park a task that repair cannot converge on, instead of re-queueing it forever."""
    why = ("%d blind repairs with no failure evidence — every retry was a guess"
           % rc) if blind else ("%d repairs without reaching a completed state" % rc)
    note = ("%s %s after %s. attempt=%s. Repair is not converging; parked for review rather "
            "than re-queued. Requeue by hand (or raise ORCH_GLOBAL_REPAIR_CEILING) only after "
            "the underlying cause is known."
            % (TERMINAL_NOTE_PREFIX, category, why, task.get("attempt")))
    return {
        "state": "QUARANTINED",
        "account": None,
        "updated_at": "now()",
        "remediation_count": rc,
        "note": note[:900],
    }


NEVER_RAN_NOTE = "requeue: never attempted — nothing to repair"


def _never_ran_patch(task):
    """A task with attempt=0 and no evidence has not failed; it has never been tried.

    Measured 2026-08-03: 322 of 469 repairs in a three-hour window (69%) were applied to tasks
    that had never run. There was nothing to repair, so each one only rewrote the prompt with a
    directive that is false on its face — "This is not a fresh requeue. Continue the same
    implementation. Preserve any useful prior work, inspect the existing branch/worktree/artifacts
    first" — pointing at prior work, a branch and a diff that never existed. By the time such a
    task finally reached a coder it was carrying several of these stacked on top of each other,
    and the agent, told to continue work it could not find, routinely produced no diff at all.
    That fed straight back in as missing-branch. This is the loop's engine.

    The correct action is a plain requeue: the original prompt, no repair directive, no count.
    """
    patch = {
        "state": "QUEUED",
        "account": None,
        "updated_at": "now()",
        "note": NEVER_RAN_NOTE,
    }
    if "prompt" in task:
        patch["prompt"] = original_prompt(task)
    return patch


def is_terminal(patch):
    """True when repair_patch() gave up rather than re-queueing.

    Call sites that post-process the patch (overwriting note, resetting counters) must check this
    first — stomping the terminal note or the count re-opens the unbounded loop it just closed.
    """
    return str((patch or {}).get("note") or "").startswith(TERMINAL_NOTE_PREFIX)


_BLIND_DIRECTIVE = (
    "No failure evidence was recorded for the previous attempt — there is no log, no traceback "
    "and no diff to work from, so do NOT guess at a fix. First establish what actually happens: "
    "check out the branch/worktree, run the project's build and test commands, and read the real "
    "error. Then fix that error and commit. If the run cannot even start (missing CLI, missing "
    "dependency, wrong path), repair the environment and say so explicitly in your final message "
    "so the next repair has something to read."
)


def repair_patch(task, signal, category="rework", directive=None, prefer_non_claude=False):
    """Return a db.update patch dict that re-queues a task with an agentic repair prompt.

    Past GLOBAL_REPAIR_CEILING repairs — or BLIND_REPAIR_CEILING repairs with no failure
    evidence — returns a terminal QUARANTINED patch instead. This is the fleet's only
    chokepoint for repair, so the bound holds for every call site.

    Values are never logged; pass the result directly to db.update.
    """
    rc = int(task.get("remediation_count") or 0)
    blind = not has_evidence(task, signal)
    # The GLOBAL ceiling is checked first, even for a task that never ran: a row that has been
    # through the machinery this many times and still has not executed once is stuck on something
    # structural (repo not mounted, an unsatisfiable dependency) that no requeue will resolve.
    if rc >= GLOBAL_REPAIR_CEILING:
        return _terminal_patch(task, category, rc, blind, signal)
    # "attempt" absent from the row means the CALLER did not select it, not that the task never
    # ran. Only the explicit value 0 means never attempted. The BLIND ceiling deliberately does
    # NOT apply here: a plain requeue does not advance remediation_count, so a never-run task
    # cannot inflate its way to the ceiling, and parking it on a count inherited from this very
    # bug would discard work that was never given a chance to run.
    if blind and "attempt" in task and int(task.get("attempt") or 0) <= 0:
        return _never_ran_patch(task)
    if blind and rc >= BLIND_REPAIR_CEILING:
        return _terminal_patch(task, category, rc, blind, signal)
    if blind:
        directive = _BLIND_DIRECTIVE if not directive else (directive + "\n\n" + _BLIND_DIRECTIVE)
    avoid = None
    if prefer_non_claude:
        # This repair exists because the task didn't finish -- diversify away from
        # whichever coder was already assigned instead of reselecting it verbatim.
        avoid = {str(x) for x in (task.get("force_coder"), task.get("model")) if x}
    coder = choose_coder(task, avoid=avoid)
    patch = {
        "state": "QUEUED",
        "account": None,
        "updated_at": "now()",
        "remediation_count": rc + 1,
        "force_coder": coder,
        "model": coder,
        "note": f"agentic-repair:{category}",
    }
    # Advance attempt only when the caller selected it, mirroring the prompt rule below.
    if "attempt" in task:
        patch["attempt"] = int(task.get("attempt") or 0) + 1
    # Only rewrite the prompt when the caller actually selected it. Sweep jobs that query a narrow
    # column set (periodic.run_unstick used to select id,slug,note,transient_retries,project_id)
    # would otherwise get in_session_prompt()'s fallback — "Complete the task '<slug>'." — written
    # back over the real specification, permanently destroying the task's content and guaranteeing
    # the next run produces nothing useful. Silently omitting the field leaves the prompt intact.
    if "prompt" in task:
        patch["prompt"] = in_session_prompt(task, signal, category=category, directive=directive)
    return patch
