#!/usr/bin/env python3
"""Same-task agentic repair helpers.

repair_patch(): build a db.update patch that re-queues a task in place, with an
agentic-repair prompt instead of the original. Used by auto_remediate, merge_train,
queue_janitor, blocker_quarantine, and runner.

in_session_prompt(): build the repair prompt string for callers that inject it
directly into a live in-session task dict (runner._agentic_repair_continue).

is_operator_decision(): escalation / human-decision rows are questions for a
person, not work items. repair_patch() refuses to repair them, so no call site
can rewrite the text a human is meant to read.
"""
import os

MARKER = "AGENTIC-REPAIR DIRECTIVE"

# --- Repair termination -----------------------------------------------------------------
# Every repair path in the fleet (auto_remediate, merge_train, queue_janitor, periodic,
# blocker_quarantine, approval_merge, runner) funnels through repair_patch(). Individual call
# sites cap themselves with `transient_retries`. CORRECTED 2026-08-24: that counter is NOT
# per-cause — it is a single shared column that conflict, testfail, buildfail, missing-branch,
# approval_merge and dag_optimizer all increment, so a budget spent on one cause silently
# denies every other cause its repairs. merge_train's regression guard was quarantining tasks
# on their FIRST regression finding for exactly this reason, while writing "after 2 repair
# attempts" into the note; it now derives its own per-cause count. Other sites still share the
# column. The comment previously said the opposite, and the wrong belief is what hid the bug.
# Some sites also
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

# A second ceiling, on `attempt` rather than `remediation_count`.
#
# WHY BOTH.
#
# remediation_count only advances when a repair goes through repair_patch() AND
# the caller happened to SELECT that column. `attempt` advances down other paths
# too. The two therefore diverge, and they diverged enormously:
#
#     slug                                             attempt   remediation_count
#     copyfix-…-public-landing-domain-intent-labels        170                   6
#     copyfix-…-public-landing-founder-navigation          131                   2
#     copyfix-…-public-landing-hero-control                124                   4
#     factory-unblock-…-fix-compilation-types              108                   5
#
# Every one of those is UNDER the ceiling of 8. The ceiling was not broken; it was
# counting about 3.5% of the work actually being done and concluding, correctly
# from what it could see, that the task had barely been tried. A task attempted
# 170 times is not converging, whatever the remediation counter says.
#
# Deliberately higher than GLOBAL_REPAIR_CEILING: `attempt` includes retries that
# are not repairs (a lost lease, a runner restart), so it should tolerate more
# before parking. It is a backstop, not the primary bound.
GLOBAL_ATTEMPT_CEILING = int(os.environ.get("ORCH_GLOBAL_ATTEMPT_CEILING", "20"))
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

UNSPECIFIED_NOTE_PREFIX = "unspecified-prompt:"

#: preflight_check verdicts that mean THE PROMPT CANNOT BE IMPLEMENTED, as opposed to the
#: verdicts about a task's history ("exhausted N attempts", recycled notes). Only these are
#: grounds for terminating early — a well-specified task that has failed on a hard bug is
#: exactly the kind of work repair exists to retry.
#: "prompt too short/empty to be actionable" is deliberately NOT here. Terseness is not
#: unimplementability — "fix the failing lockfile test" is four words and perfectly
#: actionable — and including it parked 11 legitimately-specified tasks in the existing
#: suites on the first try. The two verdicts kept below identify prompts with no request in
#: them at all: a bare template stub, or pure orchestration metadata. Preflight still blocks
#: a too-short prompt at DISPATCH; it just is not grounds for terminating the task.
_UNSPECIFIED_REASON_MARKERS = (
    "PATCH TEMPLATE or garbage prompt",
    "metadata-only prompt with no implementation spec",
)


def is_unspecified(task):
    """True when the task's PROMPT carries no implementable request.

    WHY THIS SHORT-CIRCUITS THE CEILING. "repair-ceiling: rework after 8 repairs without
    reaching a completed state" is the single largest named quarantine cause on this fleet
    (30 rows in 7 days, vs 15 for the next one). The ceiling itself is correct — it is the
    safety valve that stopped tasks reaching remediation_count 28. But reaching it costs
    EIGHT full repair cycles, and for a task whose prompt is a bare "PATCH TEMPLATE <hex>"
    stub every one of those eight was predetermined: no coder can implement a prompt that
    contains no request, so the outcome after eight tries is identical to the outcome after
    one. Observed in this queue: rows at attempt 9, 13 and 36 whose prompts preflight
    classifies as garbage at attempt 0.

    Terminating at the first repair instead of the eighth removes ~7/8 of the cost of the
    largest quarantine cause, and produces a note that names the real problem ("no
    implementation spec") rather than the symptom ("did not converge"), which is what an
    operator needs in order to fix or delete the row.

    Fail-soft: if preflight_filter is unavailable or raises, the answer is False — an
    unavailable classifier must never be read as grounds for terminating a task.
    """
    if not isinstance(task, dict) or "prompt" not in task:
        return False
    try:
        import preflight_filter
    except ImportError:
        return False
    try:
        reason = str(preflight_filter.preflight_check(task) or "")
    except Exception:
        return False
    return any(marker in reason for marker in _UNSPECIFIED_REASON_MARKERS)


def _unspecified_patch(task, rc):
    """Park an unimplementable task now, rather than after eight identical failures."""
    note = ("%s no implementation spec in the prompt, so repair cannot converge — parked "
            "at remediation_count=%s instead of burning to the ceiling. attempt=%s. Rewrite "
            "the prompt with a concrete request and requeue, or delete the row."
            % (UNSPECIFIED_NOTE_PREFIX, rc, task.get("attempt")))
    return {
        "state": "QUARANTINED",
        "account": None,
        "updated_at": "now()",
        "remediation_count": rc,
        "note": note[:900],
    }

# --- Operator-decision records ----------------------------------------------------------
# Slug prefixes the playbooks use when they STOP a loop and ask a human to decide. These rows
# are not work items: their content is a question, their state is the question's status, and
# their audience is a person.
#
# Measured 2026-08-11: escalate-p1-queue-clearance-no-improvement-20260810-nk73 — the standing
# Guardrail-8 escalation, QUEUED, awaiting an operator — was pulled into this very pipeline.
# attempt went to 4 and note became 'agentic-repair:rework', because a QUEUED row with no
# completed run looks exactly like a failed build to every sweep that selects on state. Repairing
# it would have rewritten the question with "Continue the same implementation to completion.
# Preserve any useful prior work, inspect the existing branch/worktree" — destroying the text a
# human was supposed to read, and burning coder attempts on a row no coder can resolve. The
# escalation cannot be answered by code; only by a person.
OPERATOR_DECISION_PREFIXES = ("escalate-", "human-decision-")

AWAITING_OPERATOR_NOTE = "awaiting-operator: escalation record — not repairable by an agent"


def is_operator_decision(task):
    """True when *task* is an escalation / human-decision record rather than work.

    Matched on the slug because that is what every playbook actually sets and it is present in
    even the narrowest column selection a sweep job uses.
    """
    return str((task or {}).get("slug") or "").startswith(OPERATOR_DECISION_PREFIXES)


def _awaiting_operator_patch(task):
    """Leave an escalation record intact and visible; release any stale claim on it.

    Deliberately minimal: no attempt bump, no remediation_count bump, no coder reassignment and
    above all no prompt rewrite. The only mutation is dropping a dead account so the row is not
    held by a crashed session, plus a note saying why automation declined to touch it.
    """
    return {
        "state": "QUEUED",
        "account": None,
        "updated_at": "now()",
        "note": AWAITING_OPERATOR_NOTE,
    }


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


def _true_counters(task):
    """(remediation_count, attempt) for *task*, re-read if the caller did not select them.

    Both ceilings below read these off the row the caller passed in. A sweep that
    selects a narrow column set therefore handed the ceiling a 0 for a counter
    that was actually 6, and the bound silently did not apply — which is how a
    task reached attempt=170 while its remediation_count read 6.

    Absent is not zero. Absent means unknown, and the safe response to an unknown
    counter is to go and find out, not to assume the task is fresh. One indexed
    read by id, only on the path that was previously guessing.

    Fail-soft: if the read fails we fall back to whatever the row carried, which
    is the old behaviour and no worse than it.
    """
    rc = task.get("remediation_count")
    attempts = task.get("attempt")
    if rc is not None and attempts is not None:
        return int(rc or 0), int(attempts or 0)

    task_id = task.get("id")
    if task_id:
        try:
            import db
            rows = db.select("tasks", {
                "select": "remediation_count,attempt",
                "id": f"eq.{task_id}",
                "limit": "1",
            }) or []
            if rows:
                if rc is None:
                    rc = rows[0].get("remediation_count")
                if attempts is None:
                    attempts = rows[0].get("attempt")
        except Exception:
            pass
    return int(rc or 0), int(attempts or 0)


def _is_provider_quota(signal):
    """Delegate to retry_policy so the phrase list has exactly one home.

    Fail-soft: if retry_policy cannot be imported this returns False, which
    restores the previous behaviour rather than swallowing the task.
    """
    try:
        import retry_policy
        return retry_policy.is_provider_quota(signal)
    except Exception as exc:                             # noqa: BLE001
        print("agentic_repair: provider-quota check unavailable (%s); "
              "falling back to normal repair" % exc)
        return False


def repair_patch(task, signal, category="rework", directive=None, prefer_non_claude=False):
    """Return a db.update patch dict that re-queues a task with an agentic repair prompt.

    Past GLOBAL_REPAIR_CEILING repairs — or BLIND_REPAIR_CEILING repairs with no failure
    evidence — returns a terminal QUARANTINED patch instead. This is the fleet's only
    chokepoint for repair, so the bound holds for every call site.

    Values are never logged; pass the result directly to db.update.
    """
    # Checked before every ceiling and before any prompt work: an escalation is not a failed
    # build, and the cheapest way to guarantee no repair path can consume one is to answer here,
    # at the chokepoint they all share.
    if is_operator_decision(task):
        return _awaiting_operator_patch(task)

    # The provider refusing on credit or spend is not a defect in this task, and the repair
    # path must not rewrite the prompt as though it were. `is_operator_decision` cannot catch
    # it: that matches on the SLUG, and a quota failure lands on ordinary work whose slug says
    # nothing about billing. Without this, the rewrite turns "xai returned 403, out of credits"
    # into an engineering brief instructing an agent to "use a different API key, increase the
    # spending limit, or purchase additional credits" — none of which a coding agent can do,
    # and all of which it will spend a full run discovering.
    #
    # The task stays RETRYABLE (retry_policy still classifies quota as transient, so provider
    # rotation or the monthly reset can serve it). What it does not get is a fabricated prompt.
    if _is_provider_quota(signal):
        patch = _awaiting_operator_patch(task)
        patch["note"] = ("awaiting operator: provider credit/spend exhausted — not a code "
                         "defect. Top up or re-point the router; the task is unchanged and "
                         "will retry. signal: %s" % str(signal or "")[:200])
        return patch

    rc, attempts = _true_counters(task)
    blind = not has_evidence(task, signal)
    # A task tried this many times is stuck on something a requeue does not
    # reach. See GLOBAL_ATTEMPT_CEILING for why this exists alongside rc.
    if attempts >= GLOBAL_ATTEMPT_CEILING:
        return _terminal_patch(task, category, rc, blind, signal)
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
    # Checked AFTER the never-ran guard, deliberately. A task that has never run still gets
    # its plain requeue: a repair pass may yet rewrite the prompt into something real, and
    # quarantining it here would discard work that was never given a chance — the same
    # mistake _never_ran_patch was written to undo. But once a task has actually run and
    # STILL has no implementable prompt, seven more repair cycles cannot change that.
    if is_unspecified(task):
        return _unspecified_patch(task, rc)
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
    # Advance from the TRUE attempt count, not from whatever the caller selected.
    #
    # This used to be `if "attempt" in task`, so a sweep with a narrow column set
    # repaired the task without advancing the counter at all. Combined with the
    # ceiling reading the same absent column as 0, a task could be repaired
    # without limit and without either bound ever noticing. _true_counters()
    # already resolved the real value above; use it.
    patch["attempt"] = attempts + 1
    # Only rewrite the prompt when the caller actually selected it. Sweep jobs that query a narrow
    # column set (periodic.run_unstick used to select id,slug,note,transient_retries,project_id)
    # would otherwise get in_session_prompt()'s fallback — "Complete the task '<slug>'." — written
    # back over the real specification, permanently destroying the task's content and guaranteeing
    # the next run produces nothing useful. Silently omitting the field leaves the prompt intact.
    #
    # Key PRESENCE is not enough. A row can carry a `prompt` key whose value is
    # NULL or empty — a partially-hydrated select, a failed regeneration — and
    # then original_prompt() returns "" and in_session_prompt() falls back to the
    # same "Complete the task '<slug>'." stub, which is written back over the real
    # specification exactly as before. That is the "spec-lost" quarantine cause,
    # still firing 28 times a week with the presence-only guard in place.
    #
    # So require real spec content, not just the column. When there is none there
    # is by definition nothing worth preserving in the patch either, and omitting
    # the field leaves whatever the DB holds untouched — the same fail-soft choice
    # the presence guard already makes. in_session_prompt keeps its fallback: it is
    # safe for building an in-session prompt, and harmful only when written back.
    if "prompt" in task and original_prompt(task):
        patch["prompt"] = in_session_prompt(task, signal, category=category, directive=directive)
    return patch
