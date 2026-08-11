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


def _fetch_agent_refs(repo):
    """One best-effort fetch of the shared agent/* namespace per repo per process.

    The fleet runs on TWO Macs sharing one Supabase queue: agent branches are created on
    whichever machine ran the task, so a purely local rev-parse on the other machine
    mislabels finished work as 'missing branch' and files recovery churn. Fetching
    refs/heads/agent/* into refs/remotes/origin/agent/* makes the check fleet-aware.
    Fail-soft: offline / no remote just means we fall back to local-only visibility.
    """
    if not repo or repo in _FETCHED_AGENT_REFS or not os.path.isdir(repo):
        return
    _FETCHED_AGENT_REFS.add(repo)
    try:
        subprocess.run(["git", "fetch", "origin",
                        "+refs/heads/agent/*:refs/remotes/origin/agent/*", "--prune"],
                       cwd=repo, capture_output=True, timeout=120)
    except Exception:
        pass


def _branch_exists_anywhere(repo, branch):
    """True if the branch exists locally OR on origin (the other runner's Mac)."""
    if _branch_exists(repo, branch):
        return True
    _fetch_agent_refs(repo)
    return _branch_exists(repo, f"refs/remotes/origin/{branch}")


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
    targets = [t for t in (os.environ.get("ORCH_STAGING_BRANCH", "orchestrator/dev"),
                           os.environ.get("ORCH_CODE_MERGE_TARGET", "dev"),
                           "main", "master") if t]
    refs = []
    for tgt in targets:
        ref = f"origin/{tgt}"
        try:
            probe = subprocess.run(["git", "rev-parse", "--verify", "--quiet", ref], cwd=repo,
                                   capture_output=True)
        except OSError:
            # FAIL CLOSED: repo path missing or unspawnable => cannot prove integration.
            # A bad repo_path must not crash the whole sweep (it strands every other project).
            return None
        if probe.returncode == 0:
            refs.append(ref)
    if not refs:
        return None
    try:
        return landed_evidence.find_evidence(repo, str(slug), refs=refs)
    except Exception:
        return None


def _already_integrated(repo, slug):
    """Boolean wrapper. Prefer _integration_evidence() so the sha can be persisted."""
    return _integration_evidence(repo, slug) is not None


def _integration_targets(repo):
    """Existing refs that count as 'upstream' for this repo, in preference order."""
    targets = [t for t in (os.environ.get("ORCH_STAGING_BRANCH", "orchestrator/dev"),
                           os.environ.get("ORCH_CODE_MERGE_TARGET", "dev"),
                           "main", "master") if t]
    refs = []
    for tgt in targets:
        ref = f"origin/{tgt}"
        if subprocess.run(["git", "rev-parse", "--verify", "--quiet", ref], cwd=repo,
                          capture_output=True).returncode == 0:
            refs.append(ref)
    return refs


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
    if not _branch_exists_anywhere(proj.get("repo_path", ""), f"agent/{task.get('slug')}"):
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
        branch = f"agent/{t.get('slug')}"
        bucket = out.setdefault(name, {"passed_waiting": 0, "missing_branch": 0,
                                       "oldest_wait_age_s": 0})
        if _branch_exists_anywhere(repo, branch):
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
        _merged = _merged_branch_evidence(repo, f"agent/{slug}")
        if _merged:
            _sha, _ref = _merged
            if t.get("state") != "MERGED":
                import merge_truth
                merge_truth.guarded_task_update(
                    t,
                    {"state": "MERGED",
                     "artifact_commit": _sha,
                     "note": f"integration_sweeper: agent/{slug} is an ancestor of {_ref} "
                             f"at {_sha[:12]}; already integrated, closed without rebuild"},
                    repo=repo)
            skipped += 1
            continue

        if not _branch_exists_anywhere(repo, f"agent/{slug}"):
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
            db.update("tasks", {"id": t["id"]},
                      {"state": "DONE", "note": "integration_sweeper: queued for canonical merge train"})
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
        branch = f"agent/{slug}"
        if branch in local_set:
            local_out.append({"slug": slug, "branch": branch})
        elif branch in remote_set:
            remote_only_out.append({"slug": slug, "branch": branch})
        else:
            missing_out.append({"slug": slug, "branch": branch})

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


if __name__ == "__main__":
    import json
    print(json.dumps(sweep(), indent=2, default=str))
