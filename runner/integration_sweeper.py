#!/usr/bin/env python3
"""Find tested-but-unintegrated work and feed it into the canonical merge train.

If passed work lost its agent branch, queue a tiny recovery task instead of
spending a full fresh draft immediately. Recovery prompts are reuse-first:
result cache, patch transplant, and patch templates are injected before any
agentic coder sees the task.
"""
import datetime
import json
import os
import re
import sys
import subprocess
import types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import merge_train

try:
    import branch_prediction_predictor as _bp_predictor
    _ML_AVAILABLE = True
except Exception:
    _ML_AVAILABLE = False

# 80 was below the size of the set it scans (200 tasks in DONE/BLOCKED/RUNNING as of
# 2026-08-06), so more than half the queue was invisible every pass. With the dual-order
# scan below, 150 covers 300 tasks — roughly 1.5x current volume of headroom. Raise it if
# `pipeline_funnel.py` starts reporting a stalled card stage again.
LIMIT = int(os.environ.get("INTEGRATION_SWEEPER_LIMIT", "150"))
RUN_TRAIN = os.environ.get("INTEGRATION_SWEEPER_RUN_TRAIN", "true").lower() in ("true", "1", "yes")
RECOVERY_PREFIX = "recover-missing-branch-"
PRESSURE_KEY = "merge_train_pressure"
ACTIVE_STATES = "in.(QUEUED,RUNNING,RETRY,DONE,MERGED,BLOCKED,QUARANTINED)"

def _branch_exists(repo, branch):
    if not repo or not os.path.isdir(repo):
        return False
    return subprocess.run(["git", "rev-parse", "--verify", branch],
                          cwd=repo, capture_output=True).returncode == 0


# RESTORED: the helpers below were dropped by merges a780345c / d26357a6 and had been
# replaced by stub placeholders that always returned False/None -- which made the sweeper
# treat EVERY passed task as a lost branch and file endless recovery churn. Text is taken
# verbatim from the last pyflakes-clean revision of this file (commit 5ef15641).
_FETCHED_AGENT_REFS = set()
#: repo_path -> did the agent-ref fetch actually succeed this process? A repo absent from
#: this map has not been fetched; False means origin/agent/* cannot be trusted to prove a
#: branch is GONE. See agent_refs_trustworthy().
_AGENT_REFS_OK = {}


def _fetch_agent_refs(repo):
    """One best-effort fetch of the shared agent/* namespace per repo per process.

    The fleet runs on TWO Macs sharing one Supabase queue: agent branches are created on
    whichever machine ran the task, so a purely local rev-parse on the other machine
    mislabels finished work as 'missing branch' and files recovery churn. Fetching
    refs/heads/agent/* into refs/remotes/origin/agent/* makes the check fleet-aware.
    Fail-soft: offline / no remote just means we fall back to local-only visibility.
    """
    if not repo or not os.path.isdir(repo):
        return False
    if repo in _FETCHED_AGENT_REFS:
        return _AGENT_REFS_OK.get(repo, False)
    _FETCHED_AGENT_REFS.add(repo)
    ok = False
    try:
        proc = subprocess.run(["git", "fetch", "origin",
                               "+refs/heads/agent/*:refs/remotes/origin/agent/*", "--prune"],
                              cwd=repo, capture_output=True, timeout=120)
        ok = proc.returncode == 0
        if not ok:
            print(f"integration_sweeper: agent-ref fetch FAILED in {repo} "
                  f"(rc={proc.returncode}); origin/agent/* is not trustworthy this run",
                  flush=True)
    except Exception as e:  # noqa: BLE001 - logged, then degraded (fail-soft)
        print(f"integration_sweeper: agent-ref fetch raised in {repo} "
              f"({type(e).__name__}: {e}); origin/agent/* is not trustworthy this run",
              flush=True)
    _AGENT_REFS_OK[repo] = ok
    return ok


def agent_refs_trustworthy(repo):
    """True when origin/agent/* in *repo* reflects the fleet, so ABSENCE means absent.

    THE 226-TASK BURST (2026-08-23 20:00–23:00 UTC, 9+ projects at once: beethoven 37,
    smarter 34, pareto-2080 30, darwn 28, racefeed 24, prediction-markets-institute 19,
    kalepasch-com 19, santas-secret-workshop 17, sustainable-barks 17). Total rows carrying
    this note across ALL history: 236 — so 96% of it happened in one four-hour window,
    simultaneously, in every project. Nothing task-shaped is simultaneous across nine
    unrelated repositories; only something repo- or host-level is.

    The mechanism: _fetch_agent_refs() swallowed EVERY failure and returned nothing, so a
    network blip, an auth expiry or a timeout was indistinguishable from a clean fetch. The
    fleet runs on two Macs and agent branches live on whichever machine ran the task, so
    with origin/agent/* unpopulated `_branch_exists_anywhere` answers False for every task
    in the sweep. `--prune` makes it worse: a fetch that fails partway can drop the
    remote-tracking refs that were the only local evidence those branches exist. Then the
    once-per-process memo pins that verdict for the rest of the run, across every project.
    The sweep concluded "branch lost and recovery exhausted" 226 times and closed the tasks.

    The module already states the right rule for the sibling predicate: "FAIL CLOSED:
    unable to prove integration => not integrated." The same rule belongs here — unable to
    prove a branch is GONE must not mean it is gone. Callers use this before taking any
    destructive action on missing-branch evidence.
    """
    if not repo or not os.path.isdir(repo):
        return False
    _fetch_agent_refs(repo)
    return bool(_AGENT_REFS_OK.get(repo, False))


def _branch_exists_anywhere(repo, branch):
    """True if the branch exists locally OR on origin (the other runner's Mac)."""
    if _branch_exists(repo, branch):
        return True
    _fetch_agent_refs(repo)
    return _branch_exists(repo, f"refs/remotes/origin/{branch}")


# TRUNCATION FIX (2026-08-14): branch_materializer.derive_branch_name() clamps the slug to
# 80 chars before creating agent/<slug>, but this module looked the branch up as the RAW,
# untruncated `agent/{slug}` from the tasks row. Every task whose slug exceeds 80 characters
# was therefore structurally unfindable: it was reported as missing_branch on EVERY sweep and
# filed a fresh recover-missing-branch-* row each time, whose own slug is 22 chars longer and
# so is itself unfindable -- a self-feeding loop. At the time of this fix the tasks table held
# 3,944 recover-missing-branch-* rows (17.5% of all tasks), 1,445 of them over the 80-char
# limit. Resolve against the SAME derivation the materializer uses, and keep the raw name as a
# candidate so branches created before the clamp existed still resolve.
_BRANCH_SLUG_MAX = 80


def _derive_branch_slug(slug):
    """Mirror branch_materializer.derive_branch_name()'s slug normalisation + 80-char clamp.

    Kept as a local copy rather than an import: integration_sweeper runs in contexts where
    branch_materializer is not importable, and a hard dependency here would turn a missing
    module into a fleet-wide "everything is a missing branch" false positive -- the exact
    failure mode the RESTORED block above documents.
    """
    s = re.sub(r"[^a-z0-9\-]", "-", (slug or "unknown").lower().strip())
    s = re.sub(r"-+", "-", s).strip("-")
    if len(s) > _BRANCH_SLUG_MAX:
        s = s[:_BRANCH_SLUG_MAX].rstrip("-")
    return s


def _candidate_branches(slug):
    """All branch names a task's work may legitimately live under, most-canonical first."""
    raw = (slug or "").strip()
    names = []
    for candidate in (f"agent/{_derive_branch_slug(raw)}", f"agent/{raw}"):
        if candidate not in names and candidate != "agent/":
            names.append(candidate)
    return names


def _resolve_agent_branch(repo, slug):
    """Return the candidate branch name that actually exists for this slug, else None."""
    for b in _candidate_branches(slug):
        if _branch_exists_anywhere(repo, b):
            return b
    return None


def _agent_branch_exists(repo, slug):
    """True if ANY candidate branch name for this slug exists locally or on origin."""
    return _resolve_agent_branch(repo, slug) is not None


def _integration_evidence(repo, slug):
    """Return (sha, ref, subject) proving this slug's work landed, else None.

    FIX 2026-08-04 (cowork forensic audit). This used to grep `git log` for slug[:48] and
    treat ANY hit as proof of integration. A full-history audit found 10,584 of 13,816
    MERGED tasks (76.6%) had no real code in the repo, and this predicate was one of the
    three causes. A first patch filtered lines containing "recovery-intent"; re-probing that
    patched code against 400 slugs proven phantom by tree-level git ground truth, it still
    certified 117 of them (29.2%), because grep-for-a-slug is unsound three ways:

      * `Merge branch 'agent/recover-missing-branch-<slug>'` mentions <slug>, says nothing
        about "recovery-intent", and carries none of the work — the recovery attempt
        certified the very task it was created to recover;
      * slug[:48] matched by PREFIX, and 5,900 MERGED slugs share a 48-char prefix with a
        sibling slice, so slice-1 landing certified slice-2..N;
      * empty commits (tree identical to parent) counted as delivered work.

    The decision now lives in landed_evidence.find_evidence(), which requires a
    boundary-exact slug reference on a non-scaffolding commit that actually changes the
    tree — and returns the sha so callers can record it. See
    tests/test_phantom_merge_loop.py for the executable reproduction.
    """
    # os.path.isdir guard matches _branch_exists/_fetch_agent_refs above. Without it the
    # bare subprocess.run(cwd=repo) below raises FileNotFoundError for a repo_path absent
    # from THIS machine — and the fleet runs on two Macs that do not hold the same repos.
    # One missing path aborted the whole sweep, so no task got integration-checked at all
    # and every passed task then looked like a lost branch: recovery churn from a typo.
    if not repo or not slug or not os.path.isdir(repo):
        return None
    try:
        import landed_evidence
    except Exception:
        # FAIL CLOSED: unable to prove integration => not integrated. The failure mode we
        # are designing against is falsely closing real work as MERGED.
        return None
    # Single source of truth for "what counts as upstream" — see _upstream_refs(). It
    # probes origin/<target> AND refs/heads/<target>, because under the dev->prod freeze
    # the staging branch is landed locally and deliberately not pushed. strict=True keeps
    # this call site FAIL CLOSED: repo path missing or unspawnable => cannot prove
    # integration (None), rather than crashing the sweep and stranding every other project.
    refs = _upstream_refs(repo, strict=True)
    if not refs:
        return None
    try:
        return landed_evidence.find_evidence(repo, str(slug), refs=refs)
    except Exception:
        return None


def _already_integrated(repo, slug):
    """Boolean wrapper. Prefer _integration_evidence() so the sha can be persisted."""
    return _integration_evidence(repo, slug) is not None


def _upstream_refs(repo, strict=False):
    """Refs that count as 'upstream' for this repo, in preference order.

    LOCAL REFS COUNT (2026-08-17). This used to probe only `origin/<target>`. Under the
    deliberate dev->prod freeze the staging branch (orchestrator/dev) is landed locally
    and NOT pushed, so `origin/orchestrator/dev` lags by however many commits have landed
    since the last operator-triggered promotion. Every one of those commits was invisible
    to the ancestry test, so genuinely integrated work was reported as "branch lost and
    recovery exhausted" and QUARANTINED. That false negative is TERMINAL: sweep_passed()
    only ever re-selects DONE/BLOCKED/RUNNING, so a quarantined row is never re-examined
    and never recovers even after the branch is pushed. Three verified shadow-* landings
    (aab8797f, 34a0ad90, b3d04dcf) were destroyed this way on 2026-08-12.

    Reachability from the LOCAL staging branch is the same tree-level ground truth as
    reachability from origin: if the tip is an ancestor of local orchestrator/dev then
    every commit on the branch is on the branch the fleet actually lands on. origin is
    still probed FIRST because it additionally proves promotion, and the caller persists
    whichever ref matched — so "integrated locally" and "integrated upstream" stay
    distinguishable in the note rather than being silently conflated.

    strict=True preserves the fail-closed contract _integration_evidence() depends on: an
    unspawnable git (OSError) returns None — "cannot prove integration" — rather than an
    empty list, so a broken repo_path can never be read as "nothing is integrated".
    """
    targets = [t for t in (os.environ.get("ORCH_STAGING_BRANCH", "orchestrator/dev"),
                           os.environ.get("ORCH_CODE_MERGE_TARGET", "dev"),
                           "main", "master") if t]
    refs = []
    seen = set()
    for tgt in targets:
        for ref in (f"origin/{tgt}", f"refs/heads/{tgt}"):
            if ref in seen:
                continue
            try:
                probe = subprocess.run(["git", "rev-parse", "--verify", "--quiet", ref],
                                       cwd=repo, capture_output=True)
            except OSError:
                if strict:
                    return None
                continue
            if probe.returncode == 0:
                seen.add(ref)
                refs.append(ref)
    return refs


def _integration_targets(repo):
    """Existing refs that count as 'upstream' for this repo, in preference order."""
    return _upstream_refs(repo) or []


def _merged_branch_evidence(repo, branch):
    """Return (sha, ref) when `branch` is fully reachable from an upstream ref, else None.

    The gap this closes: the sweeper only ever asked "is the work integrated?" on the
    branch-MISSING path. A branch that still EXISTS was counted as `passed_waiting` and
    left open — even when it had already been merged and its tip was an ancestor of
    master. Nothing in the loop could conclude such a task was finished, so it stayed
    QUEUED, got re-claimed, and the missing-branch auto-creator kept filing fresh
    `recover-missing-branch-*` rows to rebuild work that was already in production.
    Observed repeatedly: agent/ensemble-on-hard and
    agent/canary-claude-27-slice-1-fix-dependencies were both ancestors of origin/master
    with an empty diff against it, and both still had live recovery tasks queued.

    Reachability is tree-level ground truth, so this is immune to all three unsoundness
    modes documented on _integration_evidence(): it does not grep commit messages, cannot
    be satisfied by a sibling slice sharing a slug prefix, and cannot be satisfied by a
    recovery attempt that merely NAMES the slug. If the tip commit is reachable from
    master, every commit on the branch is in master — that is what merged means.

    The returned sha is the branch tip, which satisfies the module invariant that a MERGED
    row must carry the sha proving it.
    """
    if not repo or not os.path.isdir(repo) or not branch:
        return None
    for candidate in (branch, f"refs/remotes/origin/{branch}"):
        rev = subprocess.run(["git", "rev-parse", "--verify", "--quiet", candidate],
                             cwd=repo, capture_output=True, text=True)
        if rev.returncode != 0:
            continue
        sha = (rev.stdout or "").strip()
        if not sha:
            continue
        for ref in _integration_targets(repo):
            merged = subprocess.run(["git", "merge-base", "--is-ancestor", sha, ref],
                                    cwd=repo, capture_output=True)
            if merged.returncode == 0:
                return sha, ref
    return None


def _branch_tip_sha(repo, branch):
    """Tip sha of `branch` (local first, then origin), or "" if unresolvable.

    Fail-soft: a missing repo path, a missing branch or a broken git invocation all
    return "" rather than raising, because the only caller is a closure path that must
    never take the whole sweep down.
    """
    if not repo or not branch or not os.path.isdir(repo):
        return ""
    for candidate in (branch, f"refs/remotes/origin/{branch}"):
        try:
            rev = subprocess.run(["git", "rev-parse", "--verify", "--quiet", candidate],
                                 cwd=repo, capture_output=True, text=True, timeout=30)
        except Exception:
            continue
        if rev.returncode == 0 and (rev.stdout or "").strip():
            return (rev.stdout or "").strip()
    return ""


def _close_done_with_evidence(t, repo, slug):
    """Mark a swept task DONE, carrying the sha that proves the work exists.

    ROOT CAUSE OF THE integration-sweeper CRASH LOOP (2026-08-14): this closure used to
    PATCH `{"state": "DONE"}` with a note and nothing else. The `enforce_evidence_on_closure`
    trigger rejects any DONE/MERGED/DEPLOYED_AND_VERIFIED write with a null artifact_commit,
    so PostgREST answered 400 and the raw HTTPError propagated out of sweep() and killed the
    whole run — 15 identical tracebacks, 94% of this job's failures, every sweep after the
    first offending row silently lost.

    Two things are fixed here:
      * the sweeper now records `agent/<slug>`'s tip sha, which is the artifact the merge
        train is about to integrate, so the closure satisfies the gate honestly;
      * if no sha is resolvable, or the sha is already cited by another task (the
        slice-1-certifies-slice-2..N guard in the same trigger), it falls back to the
        documented NO-ARTIFACT-JUSTIFIED escape hatch instead of asserting a commit it
        cannot prove.

    Fail-soft per repo convention: a broad catch is the convention here (an unwritable row
    must not wedge the runner) but it logs a diagnostic before swallowing.
    """
    sha = _branch_tip_sha(repo, f"agent/{slug}")
    note = "integration_sweeper: queued for canonical merge train"
    if sha:
        try:
            db.update("tasks", {"id": t["id"]},
                      {"state": "DONE", "artifact_commit": sha,
                       "note": f"{note} at {sha[:12]}"})
            return True
        except Exception as e:
            print(f"[integration_sweeper] DONE with artifact_commit={sha[:12]} rejected for "
                  f"{slug} ({e}); retrying as justified no-artifact closure")
    reason = (f"branch agent/{slug} tip unresolvable in {repo or '<no repo>'}"
              if not sha else
              f"agent/{slug} tip {sha[:12]} is already cited by another task")
    try:
        db.update("tasks", {"id": t["id"]},
                  {"state": "DONE",
                   "note": f"{note}; NO-ARTIFACT-JUSTIFIED: {reason}"})
        return True
    except Exception as e:
        # Never re-raise: one unwritable row must not abort the sweep for every other task.
        print(f"[ALARM] integration_sweeper: could not close {slug} as DONE ({e}); left open")
        return False


def _normalize_base(repo, proj, requested):
    for b in (requested, proj.get("default_base"), proj.get("prod_branch"), "main", "master"):
        if b and _branch_exists(repo, b):
            return b
    return requested or proj.get("default_base") or proj.get("prod_branch") or "main"


def _reuse_context(task, proj, repo, base):
    parts = []
    try:
        import result_cache
        sig = result_cache.signature(proj.get("name") or str(task.get("project_id")),
                                     task.get("prompt") or "", repo, base)
        hit = result_cache.lookup(sig)
        if hit:
            parts.append("RESULT CACHE HIT: reuse this prior result before drafting net-new code.\n"
                         f"Cached branch: {hit.get('branch')}\nSummary: {hit.get('summary')}")
    except Exception:
        pass
    try:
        import patch_transplant
        h = patch_transplant.hint(task)
        if h:
            parts.append(h)
    except Exception:
        pass
    # REMOVED 2026-07-11: patch_templates.build() was baking hex-hash keyword
    # salad into recovery task prompts at creation time, producing 1,801+
    # unexecutable tasks. The template is injected at claim time by
    # pre_claim_hook (in-memory only).
    return "\n\n".join(p for p in parts if p)


def _looks_passed(task):
    note = (task.get("note") or "").lower()
    return (
        task.get("state") == "DONE"
        or "verify pass" in note
        or "passed tests" in note
        or "tests pass" in note
        or "work passed tests" in note
    )


def _existing_recovery(project_id, slug):
    if str(slug or "").startswith(RECOVERY_PREFIX):
        return True
    try:
        rows = db.select("tasks", {"select": "slug,state", "project_id": f"eq.{project_id}",
                                   "slug": f"eq.{RECOVERY_PREFIX}{slug}",
                                   "state": ACTIVE_STATES,
                                   "limit": "1"}) or []
        if rows:
            return True
        rework = db.select("tasks", {"select": "slug,state", "project_id": f"eq.{project_id}",
                                     "slug": f"like.rework-%-{RECOVERY_PREFIX}{slug}%",
                                     "state": ACTIVE_STATES,
                                     "limit": "1"}) or []
        return bool(rework)
    except Exception:
        return False


def _active_recovery_index(limit=5000):
    """Load active recovery/rework rows once so sweep does not do N DB reads."""
    rows = []
    for pattern in (f"{RECOVERY_PREFIX}%", f"rework-%-{RECOVERY_PREFIX}%"):
        try:
            rows.extend(db.select("tasks", {"select": "slug,state,project_id",
                                            "slug": f"like.{pattern}",
                                            "state": ACTIVE_STATES,
                                            "limit": str(limit)}) or [])
        except Exception:
            continue
    exact = set()
    rework = []
    for row in rows:
        slug = str(row.get("slug") or "")
        project_id = row.get("project_id")
        if slug.startswith(RECOVERY_PREFIX):
            exact.add((project_id, _recovery_root(slug)))
        elif RECOVERY_PREFIX in slug:
            rework.append((project_id, slug))
    return {"exact": exact, "rework": rework}


def _existing_recovery_indexed(project_id, slug, index):
    if str(slug or "").startswith(RECOVERY_PREFIX):
        return True
    if not index:
        return _existing_recovery(project_id, slug)
    root = _recovery_root(slug)
    if (project_id, root) in index.get("exact", set()):
        return True
    needle = f"{RECOVERY_PREFIX}{root}"
    return any(pid == project_id and needle in rework_slug
               for pid, rework_slug in index.get("rework", []))


def _recovery_root(slug):
    s = str(slug or "")
    while s.startswith(RECOVERY_PREFIX):
        s = s[len(RECOVERY_PREFIX):]
    return s


def _has_live_recovery(project_id, slug):
    """True if a recovery for this slug is still in flight (QUEUED/RUNNING/RETRY). A QUARANTINED or
    otherwise terminal recovery does NOT count — that means recovery is exhausted, so the original
    should be closed rather than re-counted as missing_branch on every sweep (phantom pressure)."""
    root = _recovery_root(f"{RECOVERY_PREFIX}{slug}") if not str(slug).startswith(RECOVERY_PREFIX) else _recovery_root(slug)
    for pat in (f"{RECOVERY_PREFIX}{slug}", f"rework-%-{RECOVERY_PREFIX}{slug}%"):
        try:
            rows = db.select("tasks", {"select": "state", "project_id": f"eq.{project_id}",
                                       "slug": (f"eq.{pat}" if not pat.endswith("%") else f"like.{pat}"),
                                       "state": "in.(QUEUED,RUNNING,RETRY)", "limit": "1"}) or []
            if rows:
                return True
        except Exception:
            continue
    return False


# Added function to handle missing agent branches
def _handle_missing_branch(task, proj, recovery_index=None):
    slug = task.get("slug")
    if not slug or _existing_recovery_indexed(task.get("project_id"), slug, recovery_index):
        return False
    repo = proj.get("repo_path", "")
    base = _normalize_base(repo, proj, task.get("base_branch") or proj.get("default_base") or proj.get("prod_branch") or "main")
    reuse = _reuse_context(task, proj, repo, base)
    recovery_slug = f"{RECOVERY_PREFIX}{slug}"
    prompt = (
        "Recover tested-but-not-integrated work whose agent branch is missing.\n"
        f"Goal: recreate the smallest equivalent patch, commit it on agent/{recovery_slug}, "
        "run the project build/tests, and let the canonical merge train integrate it.\n"
        "Do not add new scope. Prefer cache/transplant/template context below before drafting.\n\n"
        f"Original slug: {slug}\n"
        f"Original task note: {(task.get('note') or '')[:1200]}\n\n"
        f"{reuse}\n\n"
        "Original prompt:\n"
        f"{task.get('prompt') or ''}"
    )
    # Coder choice: material/complex work must NOT be force-pinned to local ollama — that is exactly
    # why 160+ recoveries quarantined (ollama can't rebuild things like implement-platform). Only
    # keep a cheap local coder when the original explicitly used one; otherwise let the router pick a
    # capable coder (force_coder=None). Material work never gets forced onto ollama.
    orig = task.get("force_coder")
    if task.get("material"):
        force = None if (not orig or orig == "ollama") else orig
    else:
        force = orig or "ollama"
    # ADMISSION PRECONDITION: never queue a recovery with nothing to recover from.
    # The prompt above asks the agent to "recreate the smallest equivalent patch"; with no
    # branch, no artifact commit and no stored diff there is no patch to recreate, so the
    # task cannot produce code — it just re-detects as missing and queues another recovery.
    # Fail-soft by construction: recovery_admission.enforce() returns True on any error.
    try:
        import recovery_admission
        if not recovery_admission.enforce(
                {"project_id": task.get("project_id"), "slug": recovery_slug,
                 "submitted_by": task.get("submitted_by"),
                 "submitted_by_label": task.get("submitted_by_label"),
                 "_reuse_context": reuse},
                repo=repo):
            db.update("tasks", {"id": task["id"]},
                      {"note": f"integration_sweeper: missing branch for {slug}, but no "
                               f"recoverable input — recovery NOT queued (recorded in "
                               f"admission_rejections)"})
            return False
    except Exception:
        pass    # fail-open: the gate must never break the sweep
    row = {"project_id": task.get("project_id"), "slug": recovery_slug, "prompt": prompt,
           "base_branch": base, "kind": task.get("kind") or "bugfix", "state": "QUEUED",
           "deps": [], "material": bool(task.get("material")),
           "force_coder": force,
           "model": force,
           "note": f"integration_sweeper: rebuild missing branch for {slug} using reuse-first context"}
    try:
        db.insert("tasks", row, upsert=True)
        db.update("tasks", {"id": task["id"]},
                  {"note": f"integration_sweeper: missing branch; queued recovery {recovery_slug}"})
        return True
    except Exception:
        return False

# Modified _queue_recovery function to use the new _handle_missing_branch function
def _queue_recovery(task, proj, recovery_index=None):
    # recovery_index is the prebuilt active-recovery index from _active_recovery_index(); sweep()
    # passes it so the duplicate check is one in-memory lookup instead of 2 DB reads per task.
    # None keeps the old per-task DB path (used by any caller that has no index).
    if not _agent_branch_exists(proj.get("repo_path", ""), task.get("slug")):
        return _handle_missing_branch(task, proj, recovery_index=recovery_index)
    return False

def _age_seconds(ts):
    if not ts:
        return 0
    raw = str(ts).replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(raw)
        if dt.tzinfo:
            now = datetime.datetime.now(datetime.timezone.utc)
        else:
            now = datetime.datetime.utcnow()
        return max(0, int((now - dt).total_seconds()))
    except Exception:
        return 0


def pressure(limit=1000):
    projects = {p["id"]: p for p in (db.select("projects") or [])}
    rows = db.select("tasks", {"select": "id,slug,project_id,state,note,updated_at",
                               "state": "in.(DONE,BLOCKED,RUNNING)",
                               "order": "updated_at.asc",
                               "limit": str(limit)}) or []
    out = {}
    for t in rows:
        if not _looks_passed(t):
            continue
        proj = projects.get(t.get("project_id")) or {}
        name = proj.get("name") or str(t.get("project_id"))
        repo = proj.get("repo_path", "")
        bucket = out.setdefault(name, {"passed_waiting": 0, "missing_branch": 0,
                                       "oldest_wait_age_s": 0})
        if _agent_branch_exists(repo, t.get("slug")):
            bucket["passed_waiting"] += 1
            bucket["oldest_wait_age_s"] = max(bucket["oldest_wait_age_s"], _age_seconds(t.get("updated_at")))
        else:
            bucket["missing_branch"] += 1
    payload = {"generated_at": datetime.datetime.utcnow().isoformat(), "projects": out}
    try:
        db.insert("controls", {"key": PRESSURE_KEY, "value": json.dumps(payload),
                               "updated_at": "now()"}, upsert=True)
    except Exception:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            ".runtime", "merge_train_pressure.json")
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(payload, f, indent=2)
        except OSError:
            pass
    return payload


def recovery_dedup(limit=5000):
    """Collapse duplicate recovery rows without touching the original solved task.

    Recovery tasks are intentionally protected from the generic task_dedup pass, but the sweeper can
    still encounter stale DONE/BLOCKED recovery rows and accidentally create recoveries of recoveries.
    Keep one active representative per (project, original slug) and quarantine the rest so lanes go to
    real rebuilds instead of recursive backlog churn.

    FIX 2026-07-30: this function was CALLED by sweep() (and reported in its payload) but had been
    dropped from the file -- every integration-sweeper run died on NameError, ~3,948 crashes in
    .runtime/logs/integration-sweeper.err while the sweeper appeared "scheduled and healthy".

    RESTORED 2026-08-02: that emergency fix reimplemented this from scratch and grouped by EXACT
    slug, so nested recover-missing-branch-recover-missing-branch-* rows never collapsed -- the one
    thing this function exists to do -- and its return keys stopped matching the test. This is the
    original implementation (5ef15641), grouping by (project, recovery root).
    """
    rows = db.select("tasks", {"select": "id,slug,state,project_id,created_at,note",
                               "slug": f"like.{RECOVERY_PREFIX}%",
                               "limit": str(limit),
                               "order": "created_at.asc"}) or []
    groups = {}
    for row in rows:
        groups.setdefault((row.get("project_id"), _recovery_root(row.get("slug"))), []).append(row)
    state_rank = {"MERGED": 0, "DONE": 1, "RUNNING": 2, "QUEUED": 3, "RETRY": 4,
                  "BLOCKED": 5, "QUARANTINED": 6}
    quarantined = duplicate_groups = 0
    for group in groups.values():
        if len(group) <= 1:
            continue
        duplicate_groups += 1
        group.sort(key=lambda r: (state_rank.get(r.get("state"), 9), r.get("created_at") or ""))
        keep = group[0]
        for dup in group[1:]:
            if dup.get("state") in ("MERGED", "QUARANTINED"):
                continue
            db.update("tasks", {"id": dup["id"]},
                      {"state": "QUARANTINED",
                       "note": f"recovery-dedup: duplicate of {keep.get('slug')}; keeping one recovery lane for {_recovery_root(keep.get('slug'))}",
                       "updated_at": "now()"})
            quarantined += 1
    return {"duplicate_groups": duplicate_groups, "quarantined": quarantined}


def sweep(limit=LIMIT, run_train=RUN_TRAIN):
    dedup = recovery_dedup()
    projects = {p["id"]: p for p in (db.select("projects") or [])}
    # SCAN-WINDOW STARVATION, THIRD INSTANCE (2026-08-06).
    #
    # This took the `limit` OLDEST tasks by updated_at. Measured today: 183 tasks in the state
    # set against a limit of 80, so 103 were never looked at — and because the order is
    # ascending, the invisible ones are always the NEWEST. The window reached updated_at 18:26
    # while work was still finishing at 22:22.
    #
    # 60 of 107 cowork-executor DONE tasks sat beyond that horizon. That is the whole reason 28
    # finished tasks had a pushed agent/ branch, no approvals row, and no way to ever get one:
    # the sweeper is what files their card, and it could not see them.
    #
    # Same shape and same fix as merge_train._pick_cards: scan both ends. The head of the
    # backlog stays visible (that ordering is deliberate — oldest work first), and freshly
    # finished work enters through the desc pass instead of waiting for the queue to drain
    # below the cap. Dedup by id since the two windows overlap once the set fits in one page.
    query = {"select": "id,slug,project_id,state,note,kind,prompt,base_branch,material,force_coder,model,updated_at",
             "state": "in.(DONE,BLOCKED,RUNNING)"}
    # A dual-ended bounded window still has a blind middle as soon as eligible
    # work exceeds 2*limit.  That is exactly where the three completed landing
    # page changes sat after their release failed.  This is a correctness scan,
    # so page the filtered set to exhaustion.  Test doubles and old fleet builds
    # retain the bounded fallback.
    if isinstance(db, types.ModuleType) and callable(getattr(db, "select_all", None)):
        rows = db.select_all("tasks", query, order="updated_at.asc,id.asc") or []
    else:
        scan_rows, _seen_ids = [], set()
        for _order in ("updated_at.asc", "updated_at.desc"):
            for _r in (db.select("tasks", {**query, "order": _order,
                                           "limit": str(limit)}) or []):
                _id = _r.get("id")
                if _id in _seen_ids:
                    continue
                _seen_ids.add(_id)
                scan_rows.append(_r)
        rows = scan_rows
    recovery_index = _active_recovery_index()
    queued = missing = skipped = recovery = card_failed = 0
    for t in rows:
        if t.get("state") == "RUNNING" and "verify pass" not in (t.get("note") or "").lower():
            skipped += 1
            continue
        if not _looks_passed(t):
            skipped += 1
            continue
        slug = t.get("slug")
        # NESTING GUARD: never file recovery for anything that already IS recovery work,
        # including rework-* wrappers around recovery slugs — recovery-of-recovery churn
        # ("rework-missing-branch-recover-missing-branch-...") burned lanes for days.
        #
        # SCOPE FIX (2026-08-06): this guard used to `continue` HERE, before the branch check
        # and before ensure_integration_card. That made it skip recovery work entirely — not
        # just the filing of new recovery, but the INTEGRATION of recovery that had already
        # succeeded. Recovery is the fleet's largest category (4,063 tasks); when one finished
        # it went to DONE and no card was ever filed, so the merge train could not see it.
        # Measured at the time of the fix: 134 of the 191 DONE tasks (70%) were completed
        # recovery work stranded this way, the oldest waiting 13 days, while the train sat idle
        # with zero undecided cards. The guard belongs on the recovery-FILING path only.
        _is_recovery = RECOVERY_PREFIX in str(slug or "")
        proj = projects.get(t.get("project_id")) or {}
        repo = proj.get("repo_path", "")

        # A branch that still EXISTS but is already fully merged used to fall straight
        # through to the "queue an integration card" path below and be left open, so the
        # task was re-swept and re-claimed forever and the auto-creator kept filing
        # recover-missing-branch rows for work that was already in production. Reachability
        # settles it without any commit-message heuristic: if the tip is an ancestor of an
        # upstream ref, the whole branch is upstream.
        # Resolve once against every legitimate branch-name form for this slug (see the
        # TRUNCATION FIX block above) so an over-80-char slug is not mistaken for lost work.
        _agent_branch = _resolve_agent_branch(repo, slug) or f"agent/{slug}"

        _merged = _merged_branch_evidence(repo, _agent_branch)
        if _merged:
            _sha, _ref = _merged
            if t.get("state") != "MERGED":
                import merge_truth
                merge_truth.guarded_task_update(
                    t,
                    {"state": "MERGED",
                     "artifact_commit": _sha,
                     "note": f"integration_sweeper: {_agent_branch} is an ancestor of {_ref} "
                             f"at {_sha[:12]}; already integrated, closed without rebuild"},
                    repo=repo)
            skipped += 1
            continue

        if not _agent_branch_exists(repo, slug):
            # Branch gone. If the work already landed upstream, CLOSE it (no rebuild) — this is what
            # kills the phantom missing_branch recount + endless recovery churn on merged work.
            evidence = _integration_evidence(repo, slug)
            if evidence:
                # INVARIANT (2026-08-04): never write MERGED without the sha that proves it.
                # Every phantom merge in the audit was a MERGED row with artifact_commit NULL,
                # so recording the evidence is what makes the reconciliation detector able to
                # tell a real merge from a manufactured one.
                sha, ref, subject = evidence
                if t.get("state") != "MERGED":
                    # `evidence` proves the sha exists SOMEWHERE (a ref, a reflog, a merged
                    # diff) — not that it reached prod. That gap is the phantom: 42% of recent
                    # MERGED rows had a sha that was not an ancestor of master. merge_truth
                    # demands reachability and downgrades to PHANTOM_UNVERIFIED (never
                    # silently) when the sha did not land.
                    import merge_truth
                    merge_truth.guarded_task_update(
                        t,
                        {"state": "MERGED",
                         "artifact_commit": sha,
                         "note": f"integration_sweeper: work verified in {ref} at {sha[:12]} "
                                 f"({subject[:80]}); closed (branch GC'd)"},
                        repo=repo)
                continue
            if _is_recovery and not agent_refs_trustworthy(repo):
                # Same fail-closed rule as the branch below: with origin/agent/* unreadable
                # this run, "gone with no upstream evidence" is unproven, and this path
                # closes the task outright.
                skipped += 1
                print(f"integration_sweeper: not closing recovery task {slug!r} — agent "
                      f"refs unreadable in {repo}", flush=True)
                continue
            if _is_recovery:
                # This IS recovery work and its branch is gone with no upstream evidence.
                # Filing recovery-for-recovery is the churn the nesting guard exists to stop,
                # so close it instead of rebuilding a rebuild.
                db.update("tasks", {"id": t["id"]},
                          {"state": "QUARANTINED",
                           "note": "integration_sweeper: recovery branch lost with no upstream "
                                   "evidence; closed rather than filing recovery-of-recovery"})
                skipped += 1
                continue
            if _queue_recovery(t, proj, recovery_index=recovery_index):
                missing += 1
                recovery += 1
            elif _has_live_recovery(t.get("project_id"), slug):
                missing += 1  # rebuild still in flight — leave the original open
            elif not agent_refs_trustworthy(repo):
                # FAIL CLOSED. We cannot see origin/agent/* this run, so "the branch is
                # gone" is not a finding — it is the absence of one. Closing here is what
                # produced the 226-task burst of 2026-08-23; leave the task open and let a
                # later sweep with a working fetch decide.
                skipped += 1
                print(f"integration_sweeper: not closing {t.get('slug')!r} — agent refs "
                      f"unreadable in {repo}, cannot prove the branch is gone", flush=True)
            else:
                # branch gone, not integrated, and recovery is exhausted (quarantined/dead): stop
                # re-counting + re-sweeping this forever. Close it so pressure reflects reality.
                db.update("tasks", {"id": t["id"]},
                          {"state": "QUARANTINED",
                           "note": "integration_sweeper: branch lost and recovery exhausted; closed to stop phantom missing_branch churn"})
            continue
        # SAME DEFECT AS cowork_executor (audited 2026-08-06): this call site also
        # promoted the task to DONE without checking whether a card actually exists.
        # `created` is False both when a card already covers the slug (fine) and when
        # nothing was created at all (a permanent strand) — the two were indistinguishable,
        # and DONE was written either way. Use the tri-state and only close the task once
        # the slug is genuinely visible to the train.
        card_state = merge_train.ensure_integration_card_result(
            proj.get("name") or str(t.get("project_id")),
            slug,
            kind="integrate",
            title=f"merge of {slug}",
            why="integration sweeper found passed work with an agent branch",
            detail=(t.get("note") or "")[-2000:],
            status="approved",
            decided_by="canonical-train:sweeper",
        )
        if card_state == merge_train.CARD_CREATED:
            queued += 1
        if card_state not in merge_train.CARD_OK:
            card_failed += 1
            print(f"[ALARM] integration_card_failed slug={slug} "
                  f"project={proj.get('name')} source=integration_sweeper")
            db.update("tasks", {"id": t["id"]},
                      {"note": "integration_sweeper: card write failed; left open for retry "
                               "(not marked DONE — a DONE task with no card is invisible)"})
            continue
        if t.get("state") != "DONE":
            _close_done_with_evidence(t, repo, slug)
    train = merge_train.train_run() if run_train and queued else {}
    press = pressure(limit=max(limit, 200))
    out = {"queued": queued, "missing_branch": missing, "recovery_queued": recovery,
           "recovery_dedup": dedup, "card_failed": card_failed,
           "skipped": skipped, "pressure": press, "train": train}
    print(f"integration_sweeper: queued={queued} missing_branch={missing} "
          f"recovery_queued={recovery} skipped={skipped} card_failed={card_failed} train={train}")
    return out


def local_branch_audit(repo, slugs=None, limit=200):
    """Read-only audit of local agent/* branch state vs pending task slugs.

    For each slug, classifies the branch as: local, remote_only, or missing.
    Also lists stale worktrees (agent/* branches checked out but task not running).
    Does not write to git or the DB. Fail-soft on unavailable repo or DB.

    Returns:
        {
          "local": [{"slug": ..., "branch": ...}, ...],
          "remote_only": [{"slug": ..., "branch": ...}, ...],
          "missing": [{"slug": ..., "branch": ...}, ...],
          "stale_worktrees": [{"branch": ..., "worktree": ...}, ...],
          "reflog_hints": [{"slug": ..., "sha": ...}, ...],
        }
    """
    local_set = set()
    remote_set = set()
    wt_map = {}

    if repo and os.path.isdir(repo):
        _fetch_agent_refs(repo)
        try:
            r = subprocess.run(
                ["git", "branch", "--list", "agent/*", "--format=%(refname:short)"],
                cwd=repo, capture_output=True, text=True, timeout=30,
            )
            local_set = {line.strip() for line in r.stdout.splitlines() if line.strip()}
        except Exception:
            pass
        try:
            r = subprocess.run(
                ["git", "branch", "-r", "--list", "origin/agent/*", "--format=%(refname:short)"],
                cwd=repo, capture_output=True, text=True, timeout=30,
            )
            for line in r.stdout.splitlines():
                b = line.strip()
                if b.startswith("origin/"):
                    remote_set.add(b[len("origin/"):])
        except Exception:
            pass
        try:
            r = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                cwd=repo, capture_output=True, text=True, timeout=30,
            )
            wt_path = None
            for line in r.stdout.splitlines():
                if line.startswith("worktree "):
                    wt_path = line[len("worktree "):].strip()
                elif line.startswith("branch refs/heads/"):
                    b = line[len("branch refs/heads/"):].strip()
                    if b.startswith("agent/"):
                        wt_map[b] = wt_path
                elif not line.strip():
                    wt_path = None
        except Exception:
            pass

    if slugs is None:
        try:
            rows = db.select("tasks", {
                "select": "slug",
                "state": "in.(QUEUED,RUNNING,DONE,BLOCKED)",
                "order": "updated_at.desc",
                "limit": str(limit),
            }) or []
            slugs = [row["slug"] for row in rows if row.get("slug")]
        except Exception:
            slugs = []

    local_out, remote_only_out, missing_out = [], [], []
    for slug in slugs:
        # Candidate order is canonical-first, so the reported branch is the materialized
        # (<=80 char) name when it exists and the raw name only as a legacy fallback.
        candidates = _candidate_branches(slug)
        branch = next((b for b in candidates if b in local_set), None)
        if branch:
            local_out.append({"slug": slug, "branch": branch})
            continue
        branch = next((b for b in candidates if b in remote_set), None)
        if branch:
            remote_only_out.append({"slug": slug, "branch": branch})
            continue
        missing_out.append({"slug": slug, "branch": candidates[0] if candidates else f"agent/{slug}"})

    running_slugs = set()
    try:
        rows = db.select("tasks", {
            "select": "slug",
            "state": "in.(RUNNING,RETRY)",
        }) or []
        running_slugs = {r["slug"] for r in rows if r.get("slug")}
    except Exception:
        pass
    stale_wt = [
        {"branch": b, "worktree": wt_map[b]}
        for b in wt_map
        if b.startswith("agent/") and b[len("agent/"):] not in running_slugs
    ]

    missing_slugs = {item["slug"] for item in missing_out}
    reflog_hints = []
    if missing_slugs and repo and os.path.isdir(repo):
        try:
            r = subprocess.run(
                ["git", "reflog", "--format=%H %gs"],
                cwd=repo, capture_output=True, text=True, timeout=30,
            )
            seen = set()
            for line in r.stdout.splitlines():
                parts = line.split(None, 1)
                if len(parts) != 2:
                    continue
                sha, ref_action = parts
                for slug in missing_slugs:
                    if slug in ref_action and slug not in seen:
                        seen.add(slug)
                        reflog_hints.append({"slug": slug, "sha": sha})
        except Exception:
            pass

    return {
        "local": local_out,
        "remote_only": remote_only_out,
        "missing": missing_out,
        "stale_worktrees": stale_wt,
        "reflog_hints": reflog_hints,
    }


run = sweep


# --------------------------------------------------------------- phantom verify

PHANTOM_STATE = "PHANTOM_UNVERIFIED"
VERIFY_ATTEMPT_CAP = int(os.environ.get("ORCH_PHANTOM_VERIFY_ATTEMPTS", "2"))


def _verify_attempts(task):
    """How many times this task has already been through a phantom-verify pass."""
    try:
        return int((task.get("verify_attempts") or 0))
    except (TypeError, ValueError):
        return 0


def _bump_verify_attempts(task, note):
    """Record one failed verification attempt without losing the count.

    The column may not exist on every deployment, so the count is also embedded in the
    note as `[verify-attempt N/CAP]` and parsed back out — the attempt cap must work
    before the migration lands, or the batch would loop on the same rows forever.
    """
    attempts = _verify_attempts(task) + 1
    stamped = f"[verify-attempt {attempts}/{VERIFY_ATTEMPT_CAP}] {note}"
    try:
        db.update("tasks", {"id": task["id"]},
                  {"verify_attempts": attempts, "note": stamped})
        return attempts
    except Exception:
        pass
    try:
        db.update("tasks", {"id": task["id"]}, {"note": stamped})
    except Exception:
        pass
    return attempts


def _note_attempts(task):
    """Attempts recovered from the note stamp, for pre-migration deployments."""
    import re
    m = re.search(r"\[verify-attempt (\d+)/", str(task.get("note") or ""))
    return int(m.group(1)) if m else 0


def verify_phantom(project=None, limit=100, dry_run=False, include_quarantined=False):
    """Batch-verify PHANTOM_UNVERIFIED tasks against real git evidence.

    For each task: look for boundary-exact, tree-changing integration evidence via the
    same _integration_evidence() the sweep uses. Evidence found -> MERGED with the sha
    that proves it. No evidence after VERIFY_ATTEMPT_CAP attempts -> requeued for a
    rebuild. Bounded by `limit`; never raises.

    This exists because the orch-repair loop had no way to drain the 10k+ phantom
    population without hand-rolled git archaeology, which the operator runbook forbids.
    """
    out = {"scanned": 0, "merged": [], "requeued": [], "still_unproven": [],
           "skipped_no_repo": [], "project": project, "limit": limit, "dry_run": dry_run}
    try:
        limit = max(1, int(limit))
    except (TypeError, ValueError):
        limit = 100

    projects = {}
    try:
        for p in (db.select("projects", {"select": "id,name,repo_path,default_base"}) or []):
            projects[p["id"]] = p
    except Exception as e:
        out["error"] = f"project lookup failed: {e}"
        return out

    # QUARANTINED rows are scanned too (2026-08-17), making the demotion IDEMPOTENT.
    # sweep() re-selects only DONE/BLOCKED/RUNNING, so a row it closed as "branch lost and
    # recovery exhausted" was never looked at again — the demotion was one-way and terminal.
    # When that verdict came from the origin-only ancestry defect (see _upstream_refs) the
    # work was in fact integrated, and nothing in the fleet could ever notice or recover it.
    # Re-verifying here is safe in both directions: evidence restores the row, and ABSENCE
    # OF EVIDENCE CHANGES NOTHING — a quarantined row is never requeued for rebuild, because
    # it was closed deliberately and resurrecting it is the churn quarantine exists to stop.
    states = [PHANTOM_STATE, "QUARANTINED"] if include_quarantined else [PHANTOM_STATE]
    # `eq.` for the single-state default, `in.(...)` only when include_quarantined widens it.
    # The original 2026-08-11 version switched every call to `in.(...)`, which changed the
    # wire filter for the DEFAULT path that nothing had asked to change -- and two existing
    # tests pin `eq.PHANTOM_UNVERIFIED` precisely because that filter is the contract with
    # PostgREST. Widening a query shape for a case that is off by default is a silent
    # behaviour change on every existing caller, so the default is left byte-identical.
    state_filter = f"eq.{states[0]}" if len(states) == 1 else f"in.({','.join(states)})"
    query = {"select": "id,slug,project_id,state,note,kind,base_branch",
             "state": state_filter, "order": "updated_at.asc", "limit": str(limit)}
    if project:
        pid = next((p["id"] for p in projects.values() if p.get("name") == project), None)
        if pid is None:
            out["error"] = f"unknown project {project!r}"
            return out
        query["project_id"] = f"eq.{pid}"
    try:
        tasks = db.select("tasks", query) or []
    except Exception as e:
        out["error"] = f"task query failed: {e}"
        return out

    for t in tasks:
        out["scanned"] += 1
        slug = t.get("slug") or ""
        proj = projects.get(t.get("project_id")) or {}
        repo = proj.get("repo_path") or ""
        try:
            repo = db.localize_repo_path(repo)
        except Exception:
            pass
        if not repo or not os.path.isdir(repo):
            # Not evidence of anything — this machine simply does not hold the repo.
            out["skipped_no_repo"].append(slug)
            continue

        evidence = _integration_evidence(repo, slug)
        if evidence:
            sha, ref, subject = evidence
            out["merged"].append({"slug": slug, "sha": sha, "ref": ref})
            if dry_run:
                continue
            try:
                import merge_truth
                merge_truth.guarded_task_update(
                    t, {"state": "MERGED", "artifact_commit": sha,
                        "note": f"integration_sweeper --verify-phantom: evidence in {ref} "
                                f"at {sha[:12]} ({str(subject)[:80]})"}, repo=repo)
            except Exception as e:
                print(f"[verify-phantom] {slug}: merge write failed: {e}")
            continue

        if (t.get("state") or "") == "QUARANTINED":
            # No evidence for a deliberately-closed row. Leave it EXACTLY as it is: do not
            # requeue (that is the recovery churn quarantine exists to stop) and do not
            # bump an attempt counter, so re-running this pass is a no-op rather than a
            # slow march toward rebuilding dead work.
            out["still_unproven"].append({"slug": slug, "state": "QUARANTINED",
                                          "action": "left closed"})
            continue

        attempts = max(_verify_attempts(t), _note_attempts(t))
        if attempts + 1 >= VERIFY_ATTEMPT_CAP:
            out["requeued"].append({"slug": slug, "attempts": attempts + 1})
            if dry_run:
                continue
            try:
                db.update("tasks", {"id": t["id"]},
                          {"state": "QUEUED", "artifact_commit": None,
                           "note": f"integration_sweeper --verify-phantom: no integration "
                                   f"evidence after {attempts + 1} attempts; requeued for rebuild"})
            except Exception as e:
                print(f"[verify-phantom] {slug}: requeue failed: {e}")
            continue

        out["still_unproven"].append({"slug": slug, "attempts": attempts + 1})
        if not dry_run:
            _bump_verify_attempts(t, "integration_sweeper --verify-phantom: no evidence yet")

    return out


def _build_parser():
    import argparse
    parser = argparse.ArgumentParser(
        prog="integration_sweeper.py",
        description="Find tested-but-unintegrated work, and batch-verify phantom merges.")
    parser.add_argument("--verify-phantom", action="store_true",
                        help=f"batch-verify {PHANTOM_STATE} tasks against git evidence "
                             "instead of running the normal sweep")
    parser.add_argument("--project", default=None, help="restrict to one project by name")
    parser.add_argument("--limit", type=int, default=None,
                        help="max rows to process (default 100 for --verify-phantom)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change without writing")
    parser.add_argument("--no-train", action="store_true",
                        help="sweep without running the merge train afterwards")
    parser.add_argument("--include-quarantined", action="store_true",
                        help="with --verify-phantom, also re-verify QUARANTINED rows. "
                             "Evidence restores them to MERGED; absence of evidence leaves "
                             "them closed and untouched (never requeued)")
    return parser


def main(argv=None):
    """CLI entry point.

    There was no argument handling at all: `--verify-phantom --project x --limit 100`
    was silently ignored and the module ran a full unbounded sweep instead, which is
    worse for an operator than an error, because it looks like it worked.
    """
    args = _build_parser().parse_args(argv)
    if args.verify_phantom:
        result = verify_phantom(project=args.project,
                                limit=args.limit if args.limit is not None else 100,
                                dry_run=args.dry_run,
                                include_quarantined=args.include_quarantined)
        print(json.dumps(result, indent=2, default=str))
        for row in result.get("merged", []):
            print(f"MERGED   {row['slug']} <- {row['sha'][:12]} in {row['ref']}")
        for row in result.get("requeued", []):
            print(f"REQUEUED {row['slug']} (no evidence after {row['attempts']} attempts)")
        return 0 if not result.get("error") else 1
    result = sweep(limit=args.limit if args.limit is not None else LIMIT,
                   run_train=(RUN_TRAIN and not args.no_train))
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
