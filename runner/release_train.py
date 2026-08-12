#!/usr/bin/env python3
"""
release_train.py - the zero-conflict shipping model. Instead of merging each agent branch straight into
the prod branch (which serialized into phantom + real conflicts), all work accumulates on a per-project
STAGING branch, is QA'd as a batch, then released to prod (main/master) and deployed via Vercel — with a
recorded last-good commit so a bad prod deploy can be rolled back with zero downtime.

Prod branch is AUTO-DETECTED per repo (main or master, whatever origin/HEAD points to) — never hardcoded,
so it's correct for every project. Runs ON THE RUNNER MACHINE (needs the real repos + matching paths).

Flow per project:
  1. ensure staging = fresh branch off prod (rebased to prod each cycle so it never drifts far).
  2. merge every judge-passed agent branch into staging (conflicts resolved ONCE here, not vs a moving
     prod). Agents also BRANCH FROM staging (see setup-worktrees base) so their base is always current.
  3. QA staging: run the project's test/build command.
  4. if green AND batch/cadence gates are satisfied: record last_good = prod tip, merge staging -> prod, push.
     deploy_verify then confirms Vercel success or rolls back to last_good.
"""
import concurrent.futures, os, sys, subprocess, datetime, json, tempfile, threading
RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(RUNNER_DIR)
RUNTIME_DIR = os.environ.get("CLAUDE_ORCH_HOME", os.path.join(REPO_ROOT, ".runtime"))
RELEASE_FLOW_FILE = os.path.join(RUNTIME_DIR, "release_flow.json")
sys.path.insert(0, RUNNER_DIR)
import db
import commit_overlay
import integration_runtime
import paused_host_guard
import release_manifest

# BATCH-DEV defaults: ship agent work to the unified staging branch quickly, but promote
# prod in QA'd batches. This avoids improvement-by-improvement Vercel churn while keeping
# the queue draining. Hotfix lanes can still override these envs explicitly.
# Cost-control floors: ordinary releases cannot silently regress to one-change/hourly
# production deploys through stale process or machine-local environment overrides.
# The explicit AUTOPILOT_RELEASE_BLOCKER_FLUSH hot lane may still set these module
# values to 1/0 temporarily for a genuine production blocker.
# cowork 2026-08-02: floor lowered 10->1 so recovery mode (RELEASE_MIN_BATCH=1) can flush small batches
MIN_BATCH = max(1, int(os.environ.get("RELEASE_MIN_BATCH", os.environ.get("ORCH_RELEASE_BATCH_MIN", "10"))))
RELEASE_INTERVAL_HOURS = max(6.0, float(os.environ.get("RELEASE_INTERVAL_HOURS", os.environ.get("ORCH_RELEASE_INTERVAL_HOURS", "6"))))
STAGING = os.environ.get("ORCH_STAGING_BRANCH", "orchestrator/dev")
RELEASE_FIX_PREFIXES = ("relfix-", "buildfix-", "deployfix-")
QA_FIX_PREFIXES = ("qafix-",)
COPY_FIX_PREFIXES = ("copyfix-",)
RED_GATE_COOLDOWN_MIN = float(os.environ.get("ORCH_RELEASE_RED_GATE_COOLDOWN_MIN", "180"))
# A fix lineage gets a bounded wall-clock budget measured from its OLDEST task, not from
# whichever sub-task was touched last. Without this ceiling a decomposed fix DAG renews its
# own hold forever: every sub-task that goes RUNNING refreshes updated_at, so the release
# train never retries. 0 disables the ceiling and restores the old unbounded behaviour.
RELEASE_FIX_HOLD_MAX_H = float(os.environ.get("ORCH_RELEASE_FIX_HOLD_MAX_H", "12"))
QA_EVIDENCE_CHARS_PER_STREAM = 12000

# release_kpi writes this: the set of apps whose recent prod deploys keep failing, so we promote their
# tests to a HARD release gate until they recover (self-tuning loop). Read fail-soft.
_GATE_FILE = os.path.join(tempfile.gettempdir(), "orch-release-gate.json")
_FLOW_LOCK = threading.Lock()


def _release_decision(ahead, due, minimum=None):
    """Release a full batch immediately or flush a partial batch on cadence."""
    minimum = MIN_BATCH if minimum is None else int(minimum)
    ahead = int(ahead or 0)
    if ahead <= 0:
        return "up-to-date"
    if ahead >= minimum or due:
        return "release"
    return "hold"


def _candidate_state_filter():
    """Keep integration in the canonical merge train unless legacy ingestion is explicitly enabled."""
    return "in.(DONE,MERGED)" if _truthy("ORCH_RELEASE_INGEST_DONE", False) else None


def _record_release_flow(project, status, **extra):
    """Small local status file so dashboard/autopilot can show staged-vs-prod release state."""
    try:
        os.makedirs(RUNTIME_DIR, exist_ok=True)
        with _FLOW_LOCK:
            state = {}
            if os.path.exists(RELEASE_FLOW_FILE):
                try:
                    with open(RELEASE_FLOW_FILE, encoding="utf-8") as f:
                        state = json.load(f) or {}
                except Exception:
                    state = {}
            state[project] = {
                "at": datetime.datetime.utcnow().isoformat() + "Z",
                "status": status,
                "staging_branch": STAGING,
                "release_min_batch": MIN_BATCH,
                "release_interval_hours": RELEASE_INTERVAL_HOURS,
                "prod_push_enabled": _truthy("ORCH_PUSH_ON_RELEASE", True),
                **extra,
            }
            tmp = RELEASE_FLOW_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, sort_keys=True)
            os.replace(tmp, RELEASE_FLOW_FILE)
    except Exception:
        pass


def _detect_test_cmd(repo):
    """Return (cmd, is_real). is_real is True ONLY when the app has a genuine, runnable test suite —
    not a placeholder like `echo "no test specified" && exit 1`. This is what lets tests become a TRUE
    release gate where they actually exist, and stay advisory (build-gated) where they don't."""
    try:
        import dependency_prewarm
        import build_gate
        roots = dependency_prewarm.package_roots(repo)
    except Exception:
        roots = [repo]
        build_gate = None
    for root in roots:
        try:
            with open(os.path.join(root, "package.json"), encoding="utf-8") as f:
                scripts = (json.load(f) or {}).get("scripts", {}) or {}
        except Exception:
            continue
        t = str(scripts.get("test") or "").strip()
        if not t:
            continue
        low = t.lower()
        if "no test specified" in low or "exit 1" in low or low.startswith("echo") or low == "true":
            continue  # placeholder script — not a real suite
        if build_gate:
            return build_gate.script_cmd(repo, root, "test"), True
        return "npm test", True
    return "", False


def _kpi_requires_tests(project):
    """True when release_kpi flagged this app as chronically failing its prod deploy → gate harder."""
    try:
        with open(_GATE_FILE) as f:
            return bool((json.load(f) or {}).get(project))
    except Exception:
        return False


def _self_heal_build(p, project, repo, branch, blog):
    """On a RED release build, don't just dead-end at deploy_status='failed': capture the build log,
    ask a fast non-Claude model for a concrete fix directive, and auto-queue a per-app build-fix task
    so the swarm self-corrects (this is what turns santas-style 'BUILD red' into a shipped fix)."""
    try:
        import build_fixer
        # don't pile up: skip if an open build-fix task already exists for this app
        import failure_compiler
        compiled = failure_compiler.record(project, "release-build", blog)
        uslug = failure_compiler.task_slug("relfix", project, "release-build", blog)
        existing = db.select("tasks", {"select": "slug", "project_id": f"eq.{p['id']}",
                                       "state": "in.(QUEUED,RUNNING,RETRY,BLOCKED)"}) or []
        if any(str(e.get("slug", "")) == uslug for e in existing):
            return
        build_fixer.save_log(f"rel-{project}", blog)
        diff = _git(repo, "log", "-1", "--stat", branch).stdout[:3000]
        directive = build_fixer.fix_directive(blog or "", diff=diff, project=project)
        prompt = ("The production build for this app is RED and is BLOCKING release. Make `npm run build` "
                  "pass with the SMALLEST possible change (fix types/imports/syntax). Do NOT add features.\n\n"
                  f"Failure signature: {compiled['signature']} (observed {compiled['count']} time(s)).\n"
                  "# Build error (tail):\n" + (blog or "")[-3000:] + "\n\n" + (directive or ""))
        try:
            import pipeline_contract
            prompt = pipeline_contract.wrap_prompt(prompt, project=project, kind="bugfix",
                                                   source="release-self-heal", slug=uslug, material=False)
        except Exception:
            pass
        db.insert("tasks", {"project_id": p["id"], "slug": uslug, "prompt": prompt,
                  "base_branch": p.get("default_base", "main"), "kind": "bugfix", "state": "QUEUED",
                  "deps": [], "material": False,
                  "note": "auto-queued by release_train build-red self-heal"})
        print(f"release_train: queued build-fix task {uslug} for RED {project}")
    except Exception as e:
        print(f"release_train: self-heal failed for {project}: {e}")


def _self_heal_qa(p, project, repo, branch, qlog):
    """Queue one targeted QA-fix task when a required staging test gate is red."""
    try:
        existing = db.select("tasks", {"select": "slug", "project_id": f"eq.{p['id']}",
                                       "state": "in.(QUEUED,RUNNING,RETRY,BLOCKED)"}) or []
        if any(str(e.get("slug", "")).startswith("qafix-") for e in existing):
            return
        diff = _git(repo, "log", "-1", "--stat", branch).stdout[:3000]
        uslug = f"qafix-{project}-{datetime.datetime.utcnow().strftime('%m%d%H%M')}"
        prompt = ("The required staging QA/test gate is RED and is BLOCKING Vercel release. "
                  "Fix the smallest test/build issue. Do NOT add features.\n\n"
                  "# QA error tail:\n" + (qlog or "")[-3000:] + "\n\n# Latest staged diff summary:\n" + diff)
        try:
            import pipeline_contract
            prompt = pipeline_contract.wrap_prompt(prompt, project=project, kind="bugfix",
                                                   source="release-qa-self-heal", slug=uslug, material=False)
        except Exception:
            pass
        db.insert("tasks", {"project_id": p["id"], "slug": uslug, "prompt": prompt,
                  "base_branch": p.get("default_base", "main"), "kind": "bugfix", "state": "QUEUED",
                  "deps": [], "material": False,
                  "note": "auto-queued by release_train QA-red self-heal"})
        print(f"release_train: queued QA-fix task {uslug} for RED {project}")
    except Exception as e:
        print(f"release_train: QA self-heal failed for {project}: {e}")


def _self_heal_release_conflict(p, project, repo, prod, log):
    """Queue a targeted task when staging cannot be refreshed/released to prod."""
    try:
        existing = db.select("tasks", {"select": "slug", "project_id": f"eq.{p['id']}",
                                       "state": "in.(QUEUED,RUNNING,RETRY,BLOCKED)"}) or []
        if any(str(e.get("slug", "")).startswith("relfix-") for e in existing):
            return
        uslug = f"relfix-{project}-{datetime.datetime.utcnow().strftime('%m%d%H%M')}"
        stat = _git(repo, "log", "--oneline", "--left-right", "--cherry-pick",
                    f"{prod}...{STAGING}").stdout[:4000]
        prompt = ("The release train cannot fast-forward production from staging. Resolve the "
                  "staging/prod divergence with the smallest safe merge or patch so the Vercel "
                  "release can proceed. Do NOT add features.\n\n"
                  f"# Production branch\n{prod}\n\n# Error/log tail:\n{(log or '')[-3000:]}\n\n"
                  f"# Divergence summary:\n{stat}")
        try:
            import pipeline_contract
            prompt = pipeline_contract.wrap_prompt(prompt, project=project, kind="bugfix",
                                                   source="release-conflict-self-heal",
                                                   slug=uslug, material=False)
        except Exception:
            pass
        db.insert("tasks", {"project_id": p["id"], "slug": uslug, "prompt": prompt,
                  "base_branch": prod, "kind": "bugfix", "state": "QUEUED",
                  "deps": [], "material": False,
                  "note": "auto-queued by release_train fast-forward self-heal"})
        print(f"release_train: queued release-conflict task {uslug} for {project}")
    except Exception as e:
        print(f"release_train: release-conflict self-heal failed for {project}: {e}")


def _deploy_health_for(project):
    try:
        rows = db.select("deploy_health", {"select": "app,vercel_project,git_branch",
                                           "app": f"eq.{project}", "limit": "1"}) or []
        return rows[0] if rows else {}
    except Exception:
        return {}


def _truthy(name, default=True):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


def _parse_time(value):
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _fix_lineage_root(slug):
    """Group a decomposed fix DAG back to the fix it came from."""
    parts = str(slug or "").split("-")
    return "-".join(parts[:3]) if len(parts) >= 3 else str(slug or "")


def _lineage_birth(rows):
    """Oldest created_at per fix lineage - the start of that lineage's hold budget."""
    births = {}
    for row in rows:
        born = _parse_time(row.get("created_at"))
        if not born:
            continue
        if born.tzinfo is None:
            born = born.replace(tzinfo=datetime.timezone.utc)
        root = _fix_lineage_root(row.get("slug"))
        if root not in births or born < births[root]:
            births[root] = born
    return births


def _open_release_fix_tasks(p, gate=None):
    """Return open fix tasks that should be allowed to clear before another release retry."""
    if not p.get("id"):
        return []
    try:
        rows = db.select("tasks", {"select": "slug,state,note,updated_at,created_at",
                                   "project_id": f"eq.{p['id']}",
                                   "state": "in.(QUEUED,RUNNING,RETRY,BLOCKED)",
                                   "order": "updated_at.desc", "limit": "200"}) or []
    except Exception:
        return []
    births = _lineage_birth(rows)
    if gate == "qa":
        prefixes = QA_FIX_PREFIXES
    elif gate == "copy":
        prefixes = COPY_FIX_PREFIXES
    elif gate in ("build", "refresh", "push"):
        prefixes = RELEASE_FIX_PREFIXES
    else:
        prefixes = QA_FIX_PREFIXES + RELEASE_FIX_PREFIXES + COPY_FIX_PREFIXES
    hold_minutes = float(os.environ.get("ORCH_RELEASE_FIX_HOLD_MIN", "180"))
    hold_states = {
        value.strip().upper()
        for value in os.environ.get("ORCH_RELEASE_FIX_HOLD_STATES", "RUNNING,RETRY").split(",")
        if value.strip()
    }
    now = datetime.datetime.now(datetime.timezone.utc)
    out = []
    for row in rows:
        slug = str(row.get("slug") or "")
        note = str(row.get("note") or "").lower()
        # A provenance note is not a gate identity.  Otherwise one stale QA task
        # can block copy, build, and deploy forever.
        matches_gate = slug.startswith(prefixes)
        if gate is None:
            matches_gate = matches_gate or "release_train" in note or "vercel" in note
        if not matches_gate:
            continue
        # Queued history is not a mutex. Only a fix consuming a lane gets a
        # bounded exclusivity window, after which the candidate may prove itself.
        if str(row.get("state") or "").upper() not in hold_states:
            continue
        touched = _parse_time(row.get("updated_at") or row.get("created_at"))
        if touched:
            if touched.tzinfo is None:
                touched = touched.replace(tzinfo=datetime.timezone.utc)
            if (now - touched).total_seconds() > hold_minutes * 60:
                continue
        # Bounded budget per lineage: sub-task churn cannot renew the hold indefinitely.
        born = births.get(_fix_lineage_root(slug))
        if RELEASE_FIX_HOLD_MAX_H > 0:
            if born and (now - born).total_seconds() > RELEASE_FIX_HOLD_MAX_H * 3600:
                continue
        row["_lineage_age_h"] = (
            round((now - born).total_seconds() / 3600.0, 1) if born else 0.0
        )
        out.append(row)
    return out


def _self_heal_public_copy(p, project, repo, staging, findings):
    """RESTORED 2026-07-31: phantom helper — queue a copyfix task for public-copy
    gate findings so the red gate self-heals instead of NameError-ing."""
    try:
        slug = "copyfix-" + str(project) + "-" + datetime.datetime.utcnow().strftime("%m%d%H%M")
        db.insert("tasks", {
            "project_id": (p or {}).get("id") if isinstance(p, dict) else p,
            "slug": slug, "kind": "build", "state": "QUEUED", "base_branch": staging,
            "prompt": ("PUBLIC-COPY GATE RED — the public staging copy exposes protected "
                       "IP/legal strategy. Remove/redact ONLY the flagged content; change "
                       "nothing else. Findings: " + json.dumps(findings)[:2000]),
        }, upsert=False)
        print(f"release_train: queued {slug} for public-copy findings")
    except Exception as e:
        print(f"release_train: copyfix queue failed ({e})")


def _raise_hold_alarm(project, gate, fix, age_h):
    """Surface a long-running release hold. Fail-soft: never raise, never block the train."""
    try:
        detail = (f"{project}: {gate} gate held {age_h}h by fix lineage "
                  f"{_fix_lineage_root((fix or {}).get('slug'))} "
                  f"(hot task {(fix or {}).get('slug')}, state {(fix or {}).get('state')}); "
                  f"ceiling {RELEASE_FIX_HOLD_MAX_H}h")
        existing = db.select("orch_gate_alarms", {
            "select": "id", "gate": f"eq.{gate}", "kind": "eq.release_hold",
            "resolved_at": "is.null", "detail": f"like.{project}:%", "limit": "1"}) or []
        if existing:
            return
        db.insert("orch_gate_alarms", {
            "gate": gate, "kind": "release_hold", "verdict": "held", "n": 1,
            "window_hours": int(RELEASE_FIX_HOLD_MAX_H), "detail": detail}, upsert=False)
        print(f"release_train: raised release_hold alarm — {detail}")
    except Exception as e:
        print(f"release_train: hold alarm failed ({e})")


def _hold_for_open_fix(p, project, gate):
    if not _truthy("ORCH_RELEASE_HOLD_WHILE_FIX_OPEN", True):
        return None
    fixes = _open_release_fix_tasks(p, gate=gate)
    if not fixes:
        return None
    hot = fixes[0]
    # A silent hold is indistinguishable from an idle train — that is exactly why this
    # ran unnoticed for 17 days. Always log; alarm once past half the ceiling.
    age_h = float(hot.get("_lineage_age_h") or 0.0)
    print(f"release_train: {project} gate={gate} HELD {age_h}h by fix {hot.get('slug')} "
          f"({hot.get('state')}); ceiling {RELEASE_FIX_HOLD_MAX_H}h")
    if RELEASE_FIX_HOLD_MAX_H > 0 and age_h >= RELEASE_FIX_HOLD_MAX_H / 2.0:
        _raise_hold_alarm(project, gate, hot, age_h)
    return {"project": project, "gate": gate, "note": "held for open release-fix task",
            "fix": hot.get("slug"), "fix_state": hot.get("state"), "held_hours": age_h}


def _recent_failed_gate(project, staging_sha, gate):
    """True when this exact staging SHA already failed this gate recently."""
    if not staging_sha or RED_GATE_COOLDOWN_MIN <= 0:
        return False
    try:
        rows = db.select("releases", {"select": "project,deploy_status,note,created_at,to_sha",
                                      "project": f"eq.{project}", "deploy_status": "eq.failed",
                                      "order": "created_at.desc", "limit": "50"}) or []
    except Exception:
        return False
    now = datetime.datetime.now(datetime.timezone.utc)
    tag = f"[gate:{gate}]"
    for row in rows:
        if str(row.get("to_sha") or "") != str(staging_sha):
            continue
        if tag not in str(row.get("note") or ""):
            continue
        created = _parse_time(row.get("created_at"))
        if created and (now - created).total_seconds() <= RED_GATE_COOLDOWN_MIN * 60:
            return True
    return False


def _insert_release(row):
    """Insert a releases row stamped with the host that produced it.

    `releases` recorded no host, so when a paused, stale machine started writing
    deploy_status='failed' rows the only evidence of WHO wrote them was an npm log
    path that happened to leak into the note ("/Users/mandypa..."). A failure that
    flips a project RED fleet-wide should not be attributable only by accident.

    Retries without `host` if the column is not present yet: code and migrations
    deploy independently, and a lagging DB must not take releases down entirely.
    """
    try:
        return db.insert("releases", dict(row, host=paused_host_guard.HOST))
    except Exception:
        return db.insert("releases", row)


def _insert_failed_release(project, gate, ahead, from_sha, to_sha, note):
    """Insert one failed gate row per gate/SHA/cooldown window."""
    if _recent_failed_gate(project, to_sha, gate):
        return None
    # A gate is a new unit of work, so a paused host must not record its verdict —
    # this is the row that flips a project RED and trips fleet-wide back-pressure.
    ok, why = paused_host_guard.may_start(f"gate:{gate}", project=project)
    if not ok:
        paused_host_guard.record_rejection(
            f"gate:{gate}", f"{why}; refused releases row deploy_status=failed "
                            f"to_sha={(to_sha or '')[:8]}", project=project)
        return None
    return _insert_release({"project": project, "from_sha": from_sha or "",
                    "to_sha": to_sha or "", "n_changes": int(ahead or 0),
                    "deploy_status": "failed", "note": f"[gate:{gate}] {note}"})


def _git(repo, *args, timeout=120):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=timeout)


def _link_shared_runtime(repo, worktree):
    """Reuse warmed repo-local runtime files inside ephemeral QA/build worktrees."""
    try:
        import dependency_prewarm
        dependency_prewarm.link_shared_runtime(repo, worktree)
    except Exception:
        for shared in ("node_modules", ".env", ".env.local"):
            src = os.path.join(repo, shared)
            dst = os.path.join(worktree, shared)
            if os.path.exists(src) and not os.path.exists(dst):
                try:
                    os.symlink(src, dst)
                except Exception:
                    pass


def _prepare_generated_types(worktree):
    """Generate checkout-local framework types for every typed Nuxt package root."""
    roots = [worktree]
    try:
        import dependency_prewarm
        roots.extend(dependency_prewarm.package_roots(worktree))
    except Exception:
        pass
    logs = []
    prepared = 0
    for root in dict.fromkeys(os.path.abspath(path) for path in roots):
        package = os.path.join(root, "package.json")
        tsconfig = os.path.join(root, "tsconfig.json")
        if not os.path.isfile(package) or not os.path.isfile(tsconfig):
            continue
        try:
            with open(package, encoding="utf-8") as package_file:
                package_text = package_file.read()
            with open(tsconfig, encoding="utf-8") as tsconfig_file:
                tsconfig_text = tsconfig_file.read()
        except OSError as e:
            return False, str(e)
        if '"nuxt"' not in package_text or ".nuxt/tsconfig" not in tsconfig_text:
            continue
        proc = subprocess.run(["bash", "-lc", "npx nuxi prepare"], cwd=root,
                              capture_output=True, text=True, timeout=180)
        log = ((proc.stdout or "") + "\n" + (proc.stderr or ""))[-4000:]
        logs.append(f"[{os.path.relpath(root, worktree)}]\n{log}")
        generated = os.path.join(root, ".nuxt", "tsconfig.json")
        if proc.returncode != 0 or not os.path.exists(generated):
            return False, "\n".join(logs)
        prepared += 1
    return True, "\n".join(logs) if prepared else "framework generation not required"


def _qa_ref(repo, ref, command, timeout=1800):
    """Run QA against an exact Git tree; used for production-baseline comparison."""
    import commit_overlay
    try:
        with commit_overlay.checkout(repo, ref, prefix="baseline-qa-overlay-") as overlay:
            worktree = overlay["path"]
            _link_shared_runtime(repo, worktree)
            prepared, prepare_log = _prepare_generated_types(worktree)
            if not prepared:
                return False, "Nuxt type preparation failed:\n" + prepare_log
            result = subprocess.run(["bash", "-lc", command], cwd=worktree, capture_output=True,
                                    text=True, timeout=timeout)
            log = (
                (result.stdout or "")[-QA_EVIDENCE_CHARS_PER_STREAM:]
                + "\n"
                + (result.stderr or "")[-QA_EVIDENCE_CHARS_PER_STREAM:]
            ).strip()
            return result.returncode == 0, f"overlay:{overlay['commit'][:12]} {log}"
    except subprocess.TimeoutExpired:
        return False, f"tests timed out after {timeout}s"


def prod_branch(repo):
    """Auto-detect the production branch: origin/HEAD target, else main, else master."""
    r = _git(repo, "symbolic-ref", "refs/remotes/origin/HEAD")
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip().rsplit("/", 1)[-1]
    for b in ("main", "master"):
        if _git(repo, "rev-parse", "--verify", b).returncode == 0:
            return b
    return "main"


def _release_base_ref(repo, prod):
    """Prefer the remote prod tip for release math.

    Local prod branches are often checked out/dirty on operator machines. After
    a direct staging->prod push, local prod can remain stale; comparing against
    it causes duplicate release rows for the same staging SHA.
    """
    if os.environ.get("ORCH_RELEASE_FETCH_REMOTE_BASE", "true").lower() in ("1", "true", "yes", "on"):
        _git(repo, "fetch", "origin", prod, timeout=120)
    remote = f"origin/{prod}"
    if _git(repo, "rev-parse", "--verify", remote).returncode == 0:
        return remote
    return prod


def _ensure_staging(repo, prod):
    # create/refresh staging without disturbing the checked-out worktree. Prefer remote
    # staging when another Mac has already pushed a batch into the shared integration branch.
    try:
        _git(repo, "fetch", "origin", prod, timeout=120)
        _git(repo, "fetch", "origin", STAGING, timeout=120)
    except Exception:
        pass
    remote_staging = f"refs/remotes/origin/{STAGING}"
    has_remote_staging = _git(repo, "rev-parse", "--verify", remote_staging).returncode == 0
    if _git(repo, "rev-parse", "--verify", STAGING).returncode != 0:
        _git(repo, "branch", STAGING, remote_staging if has_remote_staging else prod)
    else:
        if (has_remote_staging
                and _git(repo, "merge-base", "--is-ancestor", STAGING, remote_staging).returncode == 0):
            _git(repo, "fetch", ".", f"{remote_staging}:refs/heads/{STAGING}")
        # fast-forward staging to include any new prod commits (keeps it current, avoids drift)
        _git(repo, "fetch", ".", f"{prod}:{STAGING}") if _git(repo, "merge-base", "--is-ancestor", STAGING, prod).returncode == 0 else None


def _refresh_staging_with_prod(repo, prod):
    """Ensure staging contains the current prod tip before prod fast-forwards."""
    if _git(repo, "merge-base", "--is-ancestor", prod, STAGING).returncode == 0:
        return True, "staging already includes prod"
    import shutil
    tmp = tempfile.mkdtemp(prefix="rel-refresh-")
    try:
        if _git(repo, "worktree", "add", "-f", tmp, STAGING).returncode != 0:
            return False, "could not create staging refresh worktree"
        r = subprocess.run(["git", "merge", "--no-ff", "-m",
                            f"release-train: refresh {STAGING} from {prod}", prod],
                           cwd=tmp, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            repaired, repair_note = _repair_lockfile_only_merge(tmp)
            if repaired:
                return True, repair_note
            subprocess.run(["git", "merge", "--abort"], cwd=tmp, capture_output=True)
            log = ((r.stdout or "")[-1500:] + "\n" + (r.stderr or "")[-1500:]).strip()
            if repair_note:
                log += f"\nlockfile auto-repair: {repair_note}"
            return False, log or "staging/prod merge conflict"
        return True, "staging refreshed from prod"
    except subprocess.TimeoutExpired:
        return False, "staging refresh merge timed out"
    except Exception as e:
        return False, f"staging refresh error: {e}"
    finally:
        _git(repo, "worktree", "unlock", tmp)
        _git(repo, "worktree", "remove", "--force", tmp)
        shutil.rmtree(tmp, ignore_errors=True)
        _git(repo, "worktree", "prune")


def _repair_lockfile_only_merge(worktree):
    """Regenerate generated lockfiles when they are the only refresh conflict.

    Source conflicts remain fail-closed.  This avoids sending a deterministic
    generated-artifact conflict through an implementation or LLM repair lane.
    """
    unresolved = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=U"], cwd=worktree,
        capture_output=True, text=True, timeout=30,
    )
    files = [name.strip() for name in (unresolved.stdout or "").splitlines() if name.strip()]
    lockfiles = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock"}
    if unresolved.returncode != 0 or not files or any(name not in lockfiles for name in files):
        return False, "not a lockfile-only conflict"
    for name in files:
        seeded = subprocess.run(
            ["git", "checkout", "--theirs", "--", name], cwd=worktree,
            capture_output=True, text=True, timeout=30,
        )
        if seeded.returncode != 0:
            return False, f"could not seed {name} for regeneration"
        if name == "package-lock.json":
            command = ["npm", "install", "--package-lock-only", "--ignore-scripts",
                       "--prefer-offline", "--no-audit", "--fund=false"]
        elif name == "pnpm-lock.yaml":
            command = ["pnpm", "install", "--lockfile-only", "--no-frozen-lockfile",
                       "--ignore-scripts", "--prefer-offline"]
        else:
            command = ["yarn", "install", "--mode=update-lockfile", "--ignore-scripts"]
        generated = subprocess.run(
            command, cwd=worktree, capture_output=True, text=True, timeout=300,
        )
        if generated.returncode != 0:
            message = (generated.stderr or generated.stdout or "")[-300:]
            return False, f"{name} regeneration failed: {message}"
    added = subprocess.run(
        ["git", "add", "--", *files], cwd=worktree,
        capture_output=True, text=True, timeout=30,
    )
    if added.returncode != 0:
        return False, "could not stage regenerated lockfile"
    remaining = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=U"], cwd=worktree,
        capture_output=True, text=True, timeout=30,
    )
    if (remaining.stdout or "").strip():
        return False, "unresolved files remain after lockfile regeneration"
    committed = subprocess.run(
        ["git", "commit", "--no-edit"], cwd=worktree,
        capture_output=True, text=True, timeout=60,
    )
    if committed.returncode != 0:
        return False, f"regenerated lockfile commit failed: {(committed.stderr or '')[-300:]}"
    return True, "staging refreshed; lockfile-only conflict regenerated deterministically"


def _merge_into_staging(repo, branch):
    """Merge an agent branch into staging via an ephemeral worktree (no checkout of the main tree)."""
    import tempfile, shutil
    tmp = tempfile.mkdtemp(prefix="stg-")
    try:
        if _git(repo, "worktree", "add", "-f", tmp, STAGING).returncode != 0:
            return False
        pre = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp,
                             capture_output=True, text=True).stdout.strip()
        r = subprocess.run(["git", "merge", "--no-ff", "-m", f"train: {branch}", branch],
                           cwd=tmp, capture_output=True, text=True)
        if r.returncode != 0:
            subprocess.run(["git", "merge", "--abort"], cwd=tmp, capture_output=True)
            return False
        # ANTI-LOSS GATE (added 2026-08-04): a CLEAN merge into staging can still silently
        # revert improvements the branch forked before. Same fail-closed gate stack as
        # auto_conflict_resolver; on findings roll staging back and refuse the merge (the
        # agent branch is preserved by the caller's conflict handling).
        findings = ""
        try:
            import auto_conflict_resolver as _acr
            findings = _acr.verify_merge(tmp, pre, STAGING, branch)
        except Exception as exc:
            findings = f"verify_merge unavailable (fail-closed): {type(exc).__name__}: {exc}"
        if findings:
            if pre:
                subprocess.run(["git", "reset", "--hard", pre], cwd=tmp, capture_output=True)
            print(f"release_train: REGRESSION BLOCKED merging {branch} into {STAGING}: "
                  f"{findings[:400]}")
            return False
        return True
    finally:
        _git(repo, "worktree", "unlock", tmp)  # locked worktrees survive remove --force (see above)
        _git(repo, "worktree", "remove", "--force", tmp)
        shutil.rmtree(tmp, ignore_errors=True)
        _git(repo, "worktree", "prune")



# A push rejected because the remote tip is not an ancestor of what we are pushing.
# git phrases this several ways depending on version and transport.
NON_FAST_FORWARD_MARKERS = (
    "non-fast-forward",
    "fetch first",
    "failed to push some refs",
    "updates were rejected",
    "behind its remote counterpart",
)


def _is_non_fast_forward(result):
    """True when a push failed because origin/<prod> moved under us."""
    blob = ((getattr(result, "stdout", "") or "") + "\n"
            + (getattr(result, "stderr", "") or "")).lower()
    return any(marker in blob for marker in NON_FAST_FORWARD_MARKERS)


def _integrate_prod_into_staging(repo, prod):
    """Fetch origin/<prod> and integrate it into STAGING before any prod push.

    origin/<prod> advances constantly — other runners, other hosts, PRs merged
    through GitHub — so a staging tip that contained the prod tip when the
    gates ran is routinely stale by push time, and the push is then correctly
    rejected as a non-fast-forward. Integrating first is the fix; forcing would
    discard whatever advanced production.

    Returns (ok, note, staging_sha, moved). `moved` is True when integration
    changed the staging tip, in which case the caller MUST re-run the release
    gates against the new tip before shipping it.
    """
    base_ref = _release_base_ref(repo, prod)
    before = _git(repo, "rev-parse", STAGING).stdout.strip()
    ok, note = _refresh_staging_with_prod(repo, base_ref)
    after = _git(repo, "rev-parse", STAGING).stdout.strip()
    return ok, note, (after or before), bool(after and before and after != before)


def _rerun_release_gates(repo, sha, test_cmd, require_tests, build_cmd):
    """Re-run the QA and build gates against an integrated staging tip.

    Integrating new prod commits can break a batch that was green before them.
    Shipping on the pre-integration verdict is how a green gate ends up
    certifying a tree that was never built. Fail-closed, like the gates above.

    Returns (ok, gate_name, log).
    """
    # RESOLVED-FILE GATE (2026-08-12), first because it is the cheapest and because a
    # marker in the tree makes every later gate's verdict meaningless — a .gitignore with
    # conflict markers silently stops ignoring, and the build still goes green. Runs over
    # the WHOLE tree at `sha`, not a change list, since the marker that reaches production
    # is characteristically in a file this batch never touched.
    try:
        import resolved_file_gate
        marker_findings = resolved_file_gate.scan_repo(repo, ref=sha)
        if marker_findings:
            files = sorted({f.get("file") for f in marker_findings if f.get("file")})
            return False, "conflict-markers", (
                "release refused: %d unresolved conflict-marker finding(s) at %s in %s. "
                "Nothing was force-pushed and neither side of any conflict was discarded — "
                "resolve the files and re-run."
                % (len(marker_findings), (sha or "")[:12], ", ".join(files[:10]) or "the tree"))
    except Exception as exc:
        # Fail-closed, like every other gate in this function.
        return False, "conflict-markers", (
            "resolved-file gate error (fail-closed): %s: %s" % (type(exc).__name__, exc))

    if test_cmd and require_tests:
        try:
            with commit_overlay.checkout(repo, sha, prefix="release-regate-overlay-") as overlay:
                tmp = overlay["path"]
                _link_shared_runtime(repo, tmp)
                prepared, prepare_log = _prepare_generated_types(tmp)
                if not prepared:
                    return False, "qa", "Nuxt type preparation failed:\n" + prepare_log
                qa = subprocess.run(["bash", "-lc", test_cmd], cwd=tmp,
                                    capture_output=True, text=True, timeout=1800)
                if qa.returncode != 0:
                    return False, "qa", (
                        (qa.stdout or "")[-QA_EVIDENCE_CHARS_PER_STREAM:] + "\n"
                        + (qa.stderr or "")[-QA_EVIDENCE_CHARS_PER_STREAM:]).strip()
        except Exception as exc:
            return False, "qa", f"post-integration QA overlay failed: {type(exc).__name__}: {exc}"
    try:
        import build_gate
        if not build_cmd:
            return False, "build", "no production build command could be determined for re-gate"
        bok, blog = build_gate.run_build(repo, sha, build_cmd)
    except Exception as exc:
        return False, "build", f"post-integration build gate error (fail-closed): {type(exc).__name__}: {exc}"
    if not bok:
        return False, "build", blog or "post-integration build red"
    return True, "", ""


def _persist_production_build_proof(repo, commit, build_cmd):
    """Persist the exact proof required by the production pre-push hook.

    The release train built the candidate successfully but recorded only a QA
    proof.  The production hook deliberately accepts only ``kind=build`` (or
    ``vercel-build``), so every otherwise-green promotion was rejected as
    unverified.  Record and immediately read back the exact commit/command proof
    before attempting the push; proof persistence is part of the release gate,
    not best-effort telemetry.
    """
    try:
        import build_gate
        import proof_graph
        guard_cmd = str(build_gate.detect_build_cmd(repo) or "").strip()
        ran_cmd = str(build_cmd or "").strip()
        if not guard_cmd:
            return False, "production push guard could not detect a build command"
        if ran_cmd != guard_cmd:
            return False, (f"release built `{ran_cmd}` but production guard requires "
                           f"`{guard_cmd}`; refusing to certify a command that did not run")
        proof_graph.record_verification(repo, commit, guard_cmd, "build", True)
        if not proof_graph.reusable_verification(repo, commit, guard_cmd, "build"):
            return False, "exact production build proof was not durably readable after write"
        return True, guard_cmd
    except Exception as exc:
        return False, f"production build proof persistence failed: {type(exc).__name__}: {exc}"


def _withdraw_unreleased_merged(p, project, repo, prod, note):
    """A failed prod push must not leave tasks claiming MERGED.

    merge_train marks a task MERGED when its branch lands in LOCAL staging. If
    the release push then fails, that commit exists only on this machine's
    disk: the task reads MERGED forever, the code never reaches origin, and
    nothing revisits it. Any MERGED task whose artifact commit is not
    reachable from origin/<prod> goes back to DONE so a later release picks it
    up again — branches already merged into staging are skipped by the staging
    loop, so this costs nothing once a push finally succeeds.
    """
    withdrawn = []
    try:
        remote = f"origin/{prod}"
        if _git(repo, "rev-parse", "--verify", remote).returncode != 0:
            return withdrawn
        rows = db.select("tasks", {"select": "id,slug,artifact_commit",
                                   "project_id": f"eq.{p.get('id')}", "state": "eq.MERGED",
                                   "order": "updated_at.desc", "limit": "200"}) or []
        for t in rows:
            sha = str(t.get("artifact_commit") or "").strip()
            if not sha:
                continue
            # returncode != 0 covers both "not an ancestor" and "commit does not exist here"
            if _git(repo, "merge-base", "--is-ancestor", sha, remote).returncode == 0:
                continue
            db.update("tasks", {"id": t["id"]},
                      {"state": "DONE",
                       "note": (f"MERGED withdrawn: {sha[:12]} is not on {remote} after a failed "
                                f"release push — {(note or '')[-160:]}")})
            # The old integration card is stamped train:MERGED and therefore terminal.
            # Merely returning the task to DONE leaves it invisible until a bounded sweeper
            # happens to see it; in practice the middle of that window never did.  File a
            # fresh canonical card now.  If the write fails, the full-scan sweeper remains
            # the retry path and the task stays honestly open in DONE.
            try:
                import merge_train
                merge_train.ensure_integration_card_result(
                    project, t.get("slug"), kind="integrate",
                    title=f"release retry: merge of {t.get('slug')}",
                    why=f"prior integration commit {sha[:12]} never reached {remote}",
                    detail=(note or "failed production push")[-2000:],
                    status="approved", decided_by="canonical-train:release-retry")
            except Exception as exc:
                print(f"release_train: could not re-card {t.get('slug')}: {exc}", flush=True)
            withdrawn.append(t.get("slug"))
    except Exception:
        pass
    return withdrawn


def _integrate_regate_and_push(p, project, repo, prod, ahead, release_base_sha, staging_sha,
                               test_cmd, require_tests, build_cmd, manifest=None,
                               attempts=None):
    """Integrate origin/<prod>, re-verify the integrated tip, then fast-forward push.

    Returns (pushed, to_sha, log). `pushed` is False on any failure; the caller
    must not record a successful release, and no task may keep claiming MERGED
    for a commit in a batch that never reached origin.

    Nothing here ever forces. `--force`/`--force-with-lease` against a
    production branch would discard whatever advanced it; if a push cannot
    fast-forward, the answer is to integrate, not to override.
    """
    # release_manifest is used below to record the post-integration gate, but it was
    # only ever imported inside run() further down this file — so the call at the
    # `if manifest:` branch resolved against nothing. It sits inside `except
    # Exception: pass`, so the NameError was swallowed and the gate was silently
    # never recorded; static_sanity caught the undefined name and, being CRITICAL,
    # aborted merge_train at startup on every invocation (4670 tracebacks). Import
    # it here, in the scope that uses it, fail-soft so a missing module degrades to
    # "no manifest recording" rather than taking the release path down.
    try:
        import release_manifest
    except Exception:
        release_manifest = None

    if attempts is None:
        attempts = max(1, int(os.environ.get("ORCH_RELEASE_PUSH_ATTEMPTS", "2") or 2))
    to_sha = _git(repo, "rev-parse", STAGING).stdout.strip()
    for attempt in range(1, attempts + 1):
        integrated, inote, integrated_sha, moved = _integrate_prod_into_staging(repo, prod)
        if not integrated:
            # A conflicting prod integration is a real problem that needs resolving, not
            # overriding. No push is attempted.
            _self_heal_release_conflict(p, project, repo, prod, inote)
            _insert_failed_release(project, "refresh", ahead, release_base_sha, staging_sha,
                                   f"prod integration conflicted before push — self-heal "
                                   f"queued: {(inote or '')[-160:]}")
            return False, to_sha, (inote or "prod integration conflict")
        if moved:
            # Gates were green on the pre-integration tip. Re-verify the tip we will ship.
            gok, gate, glog = _rerun_release_gates(repo, integrated_sha, test_cmd,
                                                   require_tests, build_cmd)
            if not gok:
                if gate == "build":
                    _self_heal_build(p, project, repo, STAGING, glog)
                else:
                    _self_heal_qa(p, project, repo, STAGING, glog)
                _insert_failed_release(project, gate, ahead, release_base_sha, integrated_sha,
                                       f"post-integration {gate} red — self-heal queued: "
                                       f"{(glog or '')[-160:]}")
                return False, integrated_sha, (glog or f"post-integration {gate} red")
            if manifest and release_manifest is not None:
                try:
                    # Local import: this helper runs outside the caller's scope, where
                    # release_manifest was imported. Without it the call raised NameError
                    # into the bare except below, so post-integration gates were silently
                    # never recorded on any release.
                    import release_manifest
                    release_manifest.record_gate(
                        manifest["id"], "post-integration", True,
                        detail=f"QA+build re-verified on integrated tip {integrated_sha[:12]}")
                except Exception:
                    pass
        to_sha = integrated_sha
        proof_ok, proof_note = _persist_production_build_proof(repo, to_sha, build_cmd)
        if not proof_ok:
            _insert_failed_release(project, "proof", ahead, release_base_sha, to_sha,
                                   proof_note[-500:])
            return False, to_sha, proof_note
        pr = _git(repo, "push", "origin", f"{STAGING}:{prod}", timeout=300)
        if pr.returncode == 0:
            # Keep local prod fresh when possible, but do not fail a good remote release
            # just because the operator has prod checked out with edits.
            _git(repo, "fetch", "origin", prod)
            _git(repo, "fetch", ".", f"{STAGING}:{prod}")
            return True, to_sha, ""
        plog = ((pr.stdout or "")[-1000:] + "\n" + (pr.stderr or "")[-1000:]).strip()
        if _is_non_fast_forward(pr) and attempt < attempts:
            # origin/<prod> moved between integration and push. Re-integrate and retry.
            continue
        _self_heal_release_conflict(p, project, repo, prod, plog or "push staging to prod failed")
        _insert_failed_release(project, "push", ahead, release_base_sha, to_sha,
                               f"push {STAGING}->{prod} failed: {(plog or '')[-160:]}")
        return False, to_sha, plog or "push staging to prod failed"
    return False, to_sha, "push attempts exhausted"


def _release_window_open(project, repo, ahead):
    """True when a prod promotion may push now (see policy note at call site).

    Env dials:
      ORCH_RELEASE_WINDOWS       "HH:MM,HH:MM,..." ET (default 09:00,13:00,18:00)
      ORCH_RELEASE_WINDOW_MIN    minutes each window stays open (default 45)
      ORCH_RELEASE_EARLY_THRESHOLD  pending-change count that opens an early
                                    window (default 25) — a big verified batch
                                    should not wait hours
      ORCH_RELEASE_WINDOWS_EXEMPT   comma list of projects that always push
                                    (default "beethoven" — the console has no
                                    end-user sessions to interrupt)
      ORCH_RELEASE_WINDOWS_ENABLED  master toggle (default true)
    P0 bypass: any commit subject in the pending range containing [P0], [SEC],
    [HOTFIX], or "security" pushes immediately.
    """
    try:
        if os.environ.get("ORCH_RELEASE_WINDOWS_ENABLED", "true").lower() not in ("true", "1", "yes"):
            return True
        exempt = {x.strip() for x in os.environ.get(
            "ORCH_RELEASE_WINDOWS_EXEMPT", "beethoven").split(",") if x.strip()}
        if project in exempt:
            return True
        if ahead >= int(os.environ.get("ORCH_RELEASE_EARLY_THRESHOLD", "25")):
            return True
        try:
            subjects = _git(repo, "log", "--format=%s", "-n", "60",
                            f"{_git(repo, 'rev-parse', 'origin/' + (os.environ.get('ORCH_DEFAULT_BRANCH','master'))).stdout.strip() or 'HEAD~1'}..{STAGING}").stdout or ""
        except Exception:
            subjects = ""
        low = subjects.lower()
        if any(m in low for m in ("[p0]", "[sec]", "[hotfix]", "security")):
            return True
        import datetime
        try:
            from zoneinfo import ZoneInfo
            now = datetime.datetime.now(ZoneInfo("America/New_York"))
        except Exception:
            now = datetime.datetime.utcnow() - datetime.timedelta(hours=4)
        span = int(os.environ.get("ORCH_RELEASE_WINDOW_MIN", "45"))
        for w in os.environ.get("ORCH_RELEASE_WINDOWS", "09:00,13:00,18:00").split(","):
            w = w.strip()
            if not w:
                continue
            try:
                hh, mm = (int(x) for x in w.split(":"))
            except ValueError:
                continue
            start = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if start <= now < start + datetime.timedelta(minutes=span):
                return True
        return False
    except Exception:
        return True  # fail-open: a broken window check must never freeze releases


def _release_gate_slug(project, staging_sha):
    """Stable identity for one staging batch's operator review card."""
    return f"release:{project}:{(staging_sha or '')[:12]}"


def _release_approval_gate(p, project, repo, prod, release_base_sha, staging_sha, ahead,
                           qa_note=""):
    """Wave-0 operator review gate (review-gate spec item 1): a QA/build-green staging
    batch that met the release floors does NOT promote to prod until an operator
    approves a kind='release' approval card. Returns None to proceed, or a hold
    result dict. Deny keeps the batch on staging (nothing is lost; a fresh card is
    filed when staging changes). ORCH_RELEASE_AUTOPROMOTE=true restores the old
    fully-automatic promotion (default false)."""
    if _truthy("ORCH_RELEASE_AUTOPROMOTE", False):
        return None
    slug = _release_gate_slug(project, staging_sha)
    try:
        cards = db.select("approvals", {"select": "id,status,decided_by,slug",
                                        "kind": "eq.release", "slug": f"eq.{slug}",
                                        "order": "created_at.desc", "limit": "1"}) or []
    except Exception as e:
        # fail-closed: if the approvals queue is unreachable we must not silently promote
        _record_release_flow(project, "staging-gate-error", prod=prod, ahead=int(ahead),
                             note=f"release gate could not read approvals: {str(e)[:160]}")
        return {"project": project, "gate": "release-approval",
                "note": "release gate could not read approvals; holding"}
    card = cards[0] if cards else None
    if card and str(card.get("status")) == "approved":
        try:
            import steering
            steering.record_once("release_decision", card.get("id"), project=project,
                                 actor_label=card.get("decided_by"),
                                 rationale="release approved by operator",
                                 payload={"staging_sha": staging_sha, "base_sha": release_base_sha,
                                          "ahead": int(ahead), "decision": "approved"})
        except Exception:
            pass
        return None
    if card and str(card.get("status")) == "denied":
        try:
            import steering
            steering.record_once("release_decision", card.get("id"), project=project,
                                 actor_label=card.get("decided_by"),
                                 rationale="release denied by operator; batch stays on staging",
                                 payload={"staging_sha": staging_sha, "base_sha": release_base_sha,
                                          "ahead": int(ahead), "decision": "denied"})
        except Exception:
            pass
        _record_release_flow(project, "staging-release-denied", prod=prod, ahead=int(ahead),
                             note="operator denied this staging batch; it stays on staging and a "
                                  "fresh card is filed when staging changes")
        return {"project": project, "gate": "release-approval",
                "note": "release denied by operator; batch requeued on staging"}
    if card:  # pending — hold without re-filing
        _record_release_flow(project, "staging-awaiting-approval", prod=prod, ahead=int(ahead),
                             note="release approval card pending operator decision")
        return {"project": project, "gate": "release-approval",
                "note": "awaiting operator release approval"}
    # No card for this staging SHA yet: file one with the full wave summary.
    subjects, diffstat = "", ""
    try:
        subjects = (_git(repo, "log", "--format=%s", "-n", "60",
                         f"{release_base_sha}..{STAGING}").stdout or "").strip()
        diffstat = (_git(repo, "diff", "--stat", f"{release_base_sha}..{staging_sha}").stdout or "").strip()
    except Exception:
        pass
    import re as _re
    branch_lines = []
    for s_line in subjects.splitlines():
        m = _re.match(r"Merge branch '([^']+)'", s_line)
        branch_lines.append(f"- {m.group(1)}" if m else f"- {s_line[:120]}")
    deploy_target = p.get("vercel_project") or project
    brief = {"staging_sha": staging_sha, "base_sha": release_base_sha, "ahead": int(ahead),
             "staging_branch": STAGING, "prod_branch": prod, "deploy_targets": [deploy_target],
             "qa": qa_note or "QA/build gates green", "included": branch_lines[:60]}
    try:
        card = db.insert("approvals", {
            "project": project, "kind": "release", "slug": slug,
            "title": f"Release wave ready: {project} — {ahead} changes to {prod}",
            "why": f"Staging batch on {STAGING} is QA/build green and met release floors "
                   f"(min batch {MIN_BATCH}). Operator review required before prod promotion "
                   f"(Wave-0 gate; ORCH_RELEASE_AUTOPROMOTE=true bypasses).",
            "value": f"Promotes {ahead} verified changes to {prod} ({deploy_target}).",
            "risk": "Prod deploy via Vercel; deploy_verify confirms or rolls back to last_good.",
            "detail": ("INCLUDED WORK:\n" + "\n".join(branch_lines[:60])
                       + "\n\nDIFFSTAT:\n" + diffstat[-2500:]
                       + f"\n\nQA: {qa_note or 'green'}\nSTAGING {staging_sha}\nBASE {release_base_sha}"),
            "brief_json": brief,
        })
    except Exception as e:
        _record_release_flow(project, "staging-gate-error", prod=prod, ahead=int(ahead),
                             note=f"release approval card insert failed: {str(e)[:160]}")
        return {"project": project, "gate": "release-approval",
                "note": "release approval card insert failed; holding"}
    if isinstance(card, list):
        card = card[0] if card else {}
    card = card or {}
    # Ready-for-review notification (spec item 2): notifications row (the source of
    # truth every surface drains) + best-effort direct ping via scripts/notify.sh.
    review_url = os.environ.get("ORCH_REVIEW_URL", "https://madeus.cc/waves")
    title = f"Release ready for review: {project} ({ahead} changes)"
    body = (f"[{project}] staging batch ready for prod promotion.\n\n"
            f"Batch: {ahead} changes -> {prod}\nStaging SHA: {staging_sha}\n\n"
            "WAVE SUMMARY:\n" + "\n".join(branch_lines[:25])
            + f"\n\nReview + decide: {review_url}\n")
    try:
        aud = os.environ.get("APPROVAL_PUSH_EMAIL", "kalepasch@gmail.com")
        nrow = {"channel": "email", "audience": aud, "kind": "decision", "title": title[:180],
                "body": body[:4000], "approval_id": card.get("id"), "sent": False}
        db.insert("notifications", nrow)
        db.insert("notifications", {**nrow, "channel": "smarter"})
    except Exception:
        pass
    try:
        import notify
        notify.send(f"{title}\n{review_url}")
    except Exception:
        pass
    _record_release_flow(project, "staging-awaiting-approval", prod=prod, ahead=int(ahead),
                         note="release approval card created; operator notified")
    return {"project": project, "gate": "release-approval", "card": card.get("id"),
            "note": f"release approval card created for {ahead} changes; awaiting operator"}


def _run_for_unlocked(project, repo_override=None):
    p = (db.select("projects", {"select": "*", "name": f"eq.{project}"}) or [{}])[0]
    repo = repo_override or p.get("repo_path", "")
    if not repo or not os.path.isdir(repo):
        return {"project": project, "skip": "repo missing on this machine"}
    prod = p.get("prod_branch") or prod_branch(repo)
    if p.get("prod_branch") != prod:
        db.update("projects", {"name": project}, {"prod_branch": prod})
    dh = _deploy_health_for(project)
    if dh.get("vercel_project") and p.get("vercel_project") != dh.get("vercel_project"):
        p["vercel_project"] = dh["vercel_project"]
        db.update("projects", {"name": project}, {"vercel_project": dh["vercel_project"]})
    _ensure_staging(repo, prod)
    # The canonical merge train owns DONE -> MERGED and is the only default
    # writer to staging. Database MERGED state is not sufficient evidence that
    # a branch landed: stale rows previously recreated the same worktree tax.
    # Legacy direct ingestion remains an explicit emergency opt-in.
    merged = 0
    state_filter = _candidate_state_filter()
    candidates = (db.select("tasks", {"select": "slug", "project_id": f"eq.{p['id']}",
                                      "state": state_filter, "order": "updated_at.desc", "limit": "60"}) or []) if state_filter else []
    for t in candidates:
        br = f"agent/{t['slug']}"
        if _git(repo, "rev-parse", "--verify", br).returncode != 0:
            continue
        # already on staging?
        if _git(repo, "merge-base", "--is-ancestor", br, STAGING).returncode == 0:
            continue
        if _merge_into_staging(repo, br):
            merged += 1
    release_base = _release_base_ref(repo, prod)
    release_base_sha = _git(repo, "rev-parse", release_base).stdout.strip()
    staging_sha = _git(repo, "rev-parse", STAGING).stdout.strip()
    # count staging changes vs the deployable prod tip, not necessarily a stale checked-out local branch
    ahead = _git(repo, "rev-list", "--count", f"{release_base}..{STAGING}").stdout.strip() or "0"
    if int(ahead) < MIN_BATCH:
        return {"project": project, "prod": prod, "staged": merged, "ahead": ahead, "note": "below batch size"}
    due, due_note = _release_due(project)
    # Amortize normal traffic into batches, but never strand low-volume projects
    # forever below MIN_BATCH: cadence expiry flushes whatever is ready.
    if _release_decision(ahead, due) == "hold":
        _record_release_flow(project, "staging-held-batch", prod=prod, staged=merged,
                             ahead=int(ahead), note=due_note)
        return {"project": project, "prod": prod, "staged": merged, "ahead": ahead,
                "note": f"below batch size; {due_note}"}
    # Freeze the exact candidate, commands, dependency graph, and file set
    # before any expensive gate runs. This manifest is the release identity.
    det_cmd, has_real_tests = _detect_test_cmd(repo)
    test_cmd = p.get("test_cmd") or det_cmd or os.environ.get("DEFAULT_TEST_CMD", "")
    if p.get("test_cmd") and not os.path.isfile(os.path.join(repo, "package.json")) and det_cmd:
        test_cmd = det_cmd
        db.update("projects", {"name": project}, {"test_cmd": det_cmd})
    require_tests = (has_real_tests
                     or os.environ.get("ORCH_RELEASE_REQUIRE_TESTS", "false").lower() == "true"
                     or _kpi_requires_tests(project))
    try:
        import build_gate
        bcmd = build_gate.build_cmd_for(p, repo)
    except Exception:
        bcmd = ""
    manifest = None
    try:
        import release_manifest
        manifest_tasks = release_manifest.discover_tasks(
            db, p.get("id"), repo, release_base_sha, staging_sha)
        known_slugs = {str(t.get("slug") or "") for t in manifest_tasks}
        manifest_tasks.extend({"slug": t.get("slug")} for t in candidates
                              if str(t.get("slug") or "") not in known_slugs)
        manifest = release_manifest.create(project, repo, release_base_sha, staging_sha,
                                           test_cmd=test_cmd, build_cmd=bcmd,
                                           tasks=manifest_tasks)
    except Exception:
        manifest = None
    # A full batch is already amortized and should ship immediately. Cadence is
    # only the deadline that flushes a partial batch.
    # PUBLIC COPY/IP GATE: anything added to public-facing pages/components/content must describe
    # value at a general abstraction level. Specific proprietary mechanisms, AI vendor routing, IP
    # partitioning, and legal/regulatory playbooks are blocked and rewritten before release.
    try:
        import public_copy_guard
        held = _hold_for_open_fix(p, project, "copy")
        if held:
            return held
        if _recent_failed_gate(project, staging_sha, "copy"):
            return {"project": project, "copy": "HELD",
                    "note": "unchanged staging SHA already failed public-copy disclosure recently"}
        copy_gate = public_copy_guard.scan_diff(repo, release_base, STAGING, project=project)
        if not copy_gate.get("pass"):
            findings = copy_gate.get("findings") or []
            _self_heal_public_copy(p, project, repo, STAGING, findings)
            _insert_failed_release(project, "copy", ahead, release_base_sha, staging_sha,
                                   f"public-copy disclosure gate red — self-heal queued: "
                                   f"{public_copy_guard.format_findings(findings)[:160]}")
            _record_release_flow(project, "staging-red-copy", prod=prod, ahead=int(ahead),
                                 note="public copy exposes protected IP/legal strategy")
            return {"project": project, "copy": "RED",
                    "note": "public copy exposes protected IP/legal strategy; copy-fix task queued"}
        if manifest:
            release_manifest.record_gate(manifest["id"], "copy", True, detail="public copy gate green")
    except Exception as e:
        _insert_failed_release(project, "copy", ahead, release_base_sha, staging_sha,
                               f"public-copy disclosure gate failed closed: {str(e)[:160]}")
        _record_release_flow(project, "staging-red-copy", prod=prod, ahead=int(ahead),
                             note="public-copy gate failed closed")
        return {"project": project, "copy": "FAILED", "note": "public-copy gate failed closed"}
    # QA staging tests. The BUILD gate below is always the hard release gate. Tests GATE the release
    # too when the app has a genuine, runnable suite (AUTO-DETECTED from package.json), when the owner
    # forces it (ORCH_RELEASE_REQUIRE_TESTS=true), or when release_kpi flagged this app as chronically
    # failing its prod deploy. Otherwise tests are advisory — so a missing/placeholder `npm test` never
    # hard-blocks a deploy (the bug that stalled tomorrow/pareto/smarter) while real suites still gate.
    det_cmd, has_real_tests = _detect_test_cmd(repo)
    test_cmd = p.get("test_cmd") or det_cmd or os.environ.get("DEFAULT_TEST_CMD", "")
    if p.get("test_cmd") and not os.path.isfile(os.path.join(repo, "package.json")) and det_cmd:
        test_cmd = det_cmd
        db.update("projects", {"name": project}, {"test_cmd": det_cmd})
    require_tests = (has_real_tests
                     or os.environ.get("ORCH_RELEASE_REQUIRE_TESTS", "false").lower() == "true"
                     or _kpi_requires_tests(project))
    qa_plan = {"reason": ""}
    if test_cmd and require_tests:
        qa_cmd = test_cmd
        try:
            import selective_qa
            qa_plan = selective_qa.plan(repo, release_base_sha, staging_sha, test_cmd)
            qa_cmd = qa_plan.get("command") or test_cmd
        except Exception as exc:
            qa_plan = {"reason": f"selective QA unavailable: {exc}"}
        held = _hold_for_open_fix(p, project, "qa")
        if held:
            return held
        if _recent_failed_gate(project, staging_sha, "qa"):
            return {"project": project, "qa": "HELD", "note": "unchanged staging SHA already failed QA recently"}
        import tempfile, shutil
        tmp = tempfile.mkdtemp(prefix="qa-")
        try:
            try:
                import dependency_prewarm
                warmed = dependency_prewarm.ensure_all(repo, reason="release_train_qa")
                if not warmed.get("ok"):
                    qlog = "dependency prewarm failed: " + (warmed.get("error") or str(warmed))[-1600:]
                    _self_heal_qa(p, project, repo, STAGING, qlog)
                    _insert_failed_release(project, "qa", ahead, release_base_sha, staging_sha,
                                           f"staging QA dependency prewarm failed — self-heal queued: {qlog[-160:]}")
                    return {"project": project, "qa": "FAILED", "note": "dependency prewarm failed; held"}
            except Exception:
                pass
            with commit_overlay.checkout(repo, staging_sha, prefix="release-qa-overlay-") as overlay:
                tmp = overlay["path"]
                _link_shared_runtime(repo, tmp)
                prepared, prepare_log = _prepare_generated_types(tmp)
                if prepared:
                    qa = subprocess.run(["bash", "-lc", qa_cmd], cwd=tmp, capture_output=True, text=True, timeout=1800)
                    ok = qa.returncode == 0
                else:
                    qa = subprocess.CompletedProcess(qa_cmd, 1, "", "Nuxt type preparation failed:\n" + prepare_log)
                    ok = False
        except Exception as exc:
            qa = subprocess.CompletedProcess(qa_cmd, 1, "", f"QA overlay failed: {exc}")
            ok = False
        if not ok:
            qlog = (
                (qa.stdout or "")[-QA_EVIDENCE_CHARS_PER_STREAM:]
                + "\n"
                + (qa.stderr or "")[-QA_EVIDENCE_CHARS_PER_STREAM:]
            ).strip()
            if _truthy("ORCH_DIFFERENTIAL_QA", True):
                try:
                    import differential_qa
                    baseline = differential_qa.cached(repo, release_base_sha, qa_cmd)
                    if baseline is None:
                        baseline_ok, baseline_log = _qa_ref(repo, release_base_sha, qa_cmd)
                        differential_qa.store(repo, release_base_sha, qa_cmd, baseline_ok, baseline_log)
                    else:
                        baseline_ok, baseline_log = baseline.get("ok"), baseline.get("log", "")
                    comparison = differential_qa.compare(qlog, baseline_log)
                    if not baseline_ok and comparison.get("allowed"):
                        ok = True
                        qa_plan["reason"] = "differential QA: unchanged production-baseline failures"
                except Exception:
                    pass
        if not ok:
            qlog = (
                (qa.stdout or "")[-QA_EVIDENCE_CHARS_PER_STREAM:]
                + "\n"
                + (qa.stderr or "")[-QA_EVIDENCE_CHARS_PER_STREAM:]
            ).strip()
            _self_heal_qa(p, project, repo, STAGING, qlog)
            _insert_failed_release(project, "qa", ahead, release_base_sha, staging_sha,
                                   f"staging QA failed (tests required) — self-heal queued: {qlog[-160:]}")
            return {"project": project, "qa": "FAILED", "note": "staging not green; held"}
        if manifest:
            release_manifest.record_gate(manifest["id"], "qa", True, command=qa_cmd,
                                         detail=qa_plan.get("reason", ""))
        try:
            import proof_graph
            proof_graph.record_verification(repo, staging_sha, qa_cmd, "qa", True)
        except Exception:
            pass
    # BUILD GATE on the whole staging batch: the real prod build must be green before we release to
    # prod (this is what stops the Vercel deploy failures — no green build, no release).
    # FAIL-CLOSED (2026-08-02). This block used to be `try: ... except Exception: pass` with the
    # whole gate nested under `if bcmd:` — so a build_gate import error, an undetectable build
    # command, or ANY exception inside run_build silently RELEASED never-compiled code to prod.
    # That fail-open is the release-side twin of the missing merge-train build gate. Now: no
    # command => blocked; exception => blocked; red build => blocked. Never a silent pass.
    held = _hold_for_open_fix(p, project, "build")
    if held:
        return held
    if _recent_failed_gate(project, staging_sha, "build"):
        return {"project": project, "build": "HELD", "note": "unchanged staging SHA already failed build recently"}
    try:
        import build_gate
        if not bcmd:
            bcmd = build_gate.build_cmd_for(p, repo) or build_gate.detect_build_cmd(repo) or ""
        if not bcmd:
            raise RuntimeError(
                "no production build command could be determined (set projects.build_cmd, a "
                "package.json build script, vercel.json buildCommand, or DEFAULT_BUILD_CMD)")
        bok, blog = build_gate.run_build(repo, STAGING, bcmd)
    except Exception as exc:
        bok = False
        blog = f"release build gate error (fail-closed): {type(exc).__name__}: {exc}"
    if not bok:
        if manifest:
            try:
                release_manifest.record_gate(manifest["id"], "build", False, command=bcmd,
                                             detail=(blog or "")[-500:])
            except Exception:
                pass
        _self_heal_build(p, project, repo, STAGING, blog)  # queue a targeted build-fix task
        _insert_failed_release(project, "build", ahead, release_base_sha, staging_sha,
                               f"staging BUILD red — self-heal queued: {(blog or '')[-120:]}")
        return {"project": project, "build": "RED", "note": "staging build not green; build-fix task queued"}
    proof_ok, proof_note = _persist_production_build_proof(repo, staging_sha, bcmd)
    if not proof_ok:
        _insert_failed_release(project, "proof", ahead, release_base_sha, staging_sha,
                               proof_note[-500:])
        return {"project": project, "proof": "RED", "note": proof_note}
    if manifest:
        try:
            release_manifest.record_gate(manifest["id"], "build", True, command=bcmd)
        except Exception:
            pass
    # WAVE-0 OPERATOR REVIEW GATE (review-gate spec item 1): staging is green and the
    # floors are met — file/consult the kind='release' approval card instead of
    # promoting automatically. Only an approved card (or ORCH_RELEASE_AUTOPROMOTE=true)
    # lets the promotion below run.
    gated = _release_approval_gate(p, project, repo, prod, release_base_sha, staging_sha,
                                   int(ahead), qa_note=str(qa_plan.get("reason") or ""))
    if gated:
        return gated
    # release: record last-good, ff prod to staging, push (deploy_verify confirms/rolls back)
    held = _hold_for_open_fix(p, project, "refresh")
    if held:
        return held
    if _recent_failed_gate(project, staging_sha, "refresh"):
        return {"project": project, "note": "unchanged staging SHA already failed staging/prod refresh recently"}
    refreshed, refresh_note = _refresh_staging_with_prod(repo, release_base)
    if not refreshed:
        _self_heal_release_conflict(p, project, repo, prod, refresh_note)
        _insert_failed_release(project, "refresh", ahead, release_base_sha, staging_sha,
                               f"staging/prod refresh failed — self-heal queued: {refresh_note[-160:]}")
        return {"project": project, "note": "staging/prod refresh failed; relfix queued"}
    last_good = release_base_sha
    db.update("projects", {"name": project}, {"last_good_sha": last_good})
    push_on = os.environ.get("ORCH_PUSH_ON_RELEASE", os.environ.get("ORCH_PUSH_ON_MERGE", "false")).lower() == "true"
    # RELEASE WINDOWS (operator policy 2026-07-31): merging is continuous, prod
    # PROMOTION is batched. A remote prod push (which triggers a Vercel build and
    # can rotate assets under live sessions) happens only (a) inside a scheduled
    # window, (b) when the pending batch is large enough, or (c) for a P0 marker.
    # Local fast-forward bookkeeping is unaffected. Fail-open on any error.
    if push_on and not _release_window_open(project, repo, int(ahead)):
        print(f"release_train {project}: {ahead} changes staged — holding for next "
              f"release window (windows={os.environ.get('ORCH_RELEASE_WINDOWS', '09:00,13:00,18:00')} ET)")
        # REPORTED, NOT CHANGED (see release-on-capacity-not-clock-cowork-20260806):
        # this clock gate suppresses the push outside ORCH_RELEASE_WINDOWS even when the
        # batch is verified and ready. It is an independent reason a green batch does not
        # reach origin, stacked on top of the non-fast-forward bug fixed below. Removing
        # the windows is that task's call, not this one's.
        return {"project": project, "prod": prod, "released": 0,
                "release_window_suppressed_push": True,
                "note": f"windowed: {ahead} changes held for next release window"}
    to_sha = _git(repo, "rev-parse", STAGING).stdout.strip()
    if not push_on:
        ff = _git(repo, "fetch", ".", f"{STAGING}:{prod}")
        if ff.returncode != 0:
            flog = ((ff.stdout or "")[-1000:] + "\n" + (ff.stderr or "")[-1000:]).strip()
            _self_heal_release_conflict(p, project, repo, prod, flog or "prod could not fast-forward from staging")
            _insert_failed_release(project, "push", ahead, release_base_sha, staging_sha,
                                   "prod could not fast-forward from staging — self-heal queued")
            return {"project": project, "note": "prod could not fast-forward from staging; relfix queued"}
        to_sha = _git(repo, "rev-parse", prod).stdout.strip()
    # NON-FAST-FORWARD FIX (2026-08-06). STAGING used to be pushed straight onto the remote
    # prod branch with no fetch of origin/<prod> and no integration of it beforehand. Because
    # origin/<prod> advances constantly, the push was routinely rejected — which failed the
    # release AND stranded commits that tasks already claimed as MERGED on one machine's disk.
    # Now: integrate, re-gate the integrated tip, then push. The release row is written after
    # the outcome is known so it records the SHA actually shipped, not a pre-integration tip.
    pushed = None
    push_log = ""
    if push_on:
        pushed, to_sha, push_log = _integrate_regate_and_push(
            p, project, repo, prod, ahead, release_base_sha, staging_sha,
            test_cmd, require_tests, bcmd, manifest=manifest)
    ver = _next_version()
    changelog = _git(repo, "log", "--oneline", f"{last_good}..{to_sha}").stdout[:2000]
    rel = _insert_release({"project": project, "version": ver, "from_sha": last_good,
                    "to_sha": to_sha, "n_changes": int(ahead), "changelog": changelog,
                    "deploy_status": ("building" if pushed else "failed") if push_on else "pending",
                    "note": "" if (pushed or not push_on) else (push_log or "push failed")[-160:]})
    withdrawn = []
    if push_on and not pushed:
        # Nothing reached origin, so no task in this batch may keep claiming MERGED.
        withdrawn = _withdraw_unreleased_merged(p, project, repo, prod, push_log)
        if withdrawn:
            print(f"release_train {project}: withdrew MERGED from {len(withdrawn)} task(s) whose "
                  f"commits never reached origin/{prod}")
        return {"project": project, "prod": prod, "released": 0, "pushed": False,
                "merged_withdrawn": withdrawn,
                "note": f"release push failed; relfix queued: {(push_log or '')[-160:]}"}
    print(f"release_train {project}: staged {merged}, released {ahead} changes to {prod} "
          f"(push={'on' if pushed else 'off/local'})")
    return {"project": project, "prod": prod, "released": ahead, "pushed": pushed}


def run_for(project):
    """Run at most one git-mutating release train per repository.

    Gate cooldowns alone cannot stop two processes that inspect the same SHA
    before either writes its failure row. Sharing the merge-train repo lock
    makes the check/build/push sequence single-flight across processes.
    """
    # run_for() is also called directly (scheduler, ad-hoc, dependency-aware orchestration),
    # so the pause check cannot live only in run().
    ok, why = paused_host_guard.refuse("release_train", project=project)
    if not ok:
        return {"project": project, "skipped": why}
    p = (db.select("projects", {"select": "repo_path", "name": f"eq.{project}"}) or [{}])[0]
    repo = p.get("repo_path", "")
    if not repo or not os.path.isdir(repo):
        return {"project": project, "skip": "repo missing on this machine"}
    return _run_for_with_repo(project, repo)


def _run_for_with_repo(project, repo):
    import repo_lock
    timeout = float(os.environ.get("ORCH_RELEASE_LOCK_TIMEOUT_S", "1") or 1)
    with repo_lock.hold(repo, timeout=timeout) as acquired:
        if not acquired:
            return {"project": project, "note": "release busy; existing train owns repo"}
        try:
            with integration_runtime.isolated_repo(repo, "release_train") as integration_repo:
                return _run_for_unlocked(project, repo_override=integration_repo)
        except integration_runtime.IntegrationRuntimeError as exc:
            return {"project": project, "note": f"release isolation blocked: {exc}"}


def _next_version():
    v = db.select("versions", {"select": "version", "status": "eq.in_progress",
                               "order": "opened_at.desc", "limit": "1"}) or []
    return v[0]["version"] if v else "v1"


def _release_due(project):
    if RELEASE_INTERVAL_HOURS <= 0:
        return True, "release interval disabled"
    rows = db.select("releases", {"select": "created_at,project,deploy_status", "project": f"eq.{project}",
                                  "deploy_status": "in.(pending,building,success)",
                                  "order": "created_at.desc", "limit": "1"}) or []
    rows = [r for r in rows if str(r.get("deploy_status") or "").lower() not in ("failed", "rolled_back")]
    if not rows:
        return True, "first successful/pending release"
    try:
        last = datetime.datetime.fromisoformat(str(rows[0]["created_at"]).replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        hours = (now - last).total_seconds() / 3600.0
        if hours >= RELEASE_INTERVAL_HOURS:
            return True, f"release interval elapsed ({hours:.1f}h)"
        return False, f"held for bulk deploy cadence ({hours:.1f}/{RELEASE_INTERVAL_HOURS:.1f}h)"
    except Exception:
        return True, "release timestamp unreadable"


def run():
    # CROSS-HOST GUARD (2026-08-06): releases push to production branches, so exactly one live
    # host may run this — and never a host on stale code. Same election as merge_train; see
    # integration_owner for why this is a pure function of heartbeats rather than a lock.
    # HOST PAUSE (2026-08-06): checked BEFORE the owner election, because a paused host
    # must not run gates even if it would otherwise win the election. The claim guard
    # covered tasks.account only, so a paused, 40-commits-stale host went on writing
    # deploy_status='failed' rows that flipped projects RED and tripped release
    # back-pressure fleet-wide. Refused at the START of a pass only — a pass already in
    # flight is never interrupted.
    _ok, _why = paused_host_guard.refuse("release_train")
    if not _ok:
        return {"skipped": _why}
    try:
        import integration_owner
        may, why = integration_owner.decide()
        if not may:
            print(f"release_train: not the integration owner — {why}", flush=True)
            return {"skipped": f"not integration owner: {why}"}
    except Exception as _io_exc:
        print(f"release_train: integration-owner check failed ({_io_exc}); proceeding", flush=True)
    projects = [p for p in (db.select("projects", {"select": "name,auto_merge,repo_path"}) or [])
                if p.get("name") != "smoke-test" and
                (os.environ.get("ORCH_RELEASE_ALL_PROJECTS", "true").lower() == "true" or p.get("auto_merge"))]
    def worker(p):
        try:
            repo = db.localize_repo_path(p.get("repo_path", ""))
            return (_run_for_with_repo(p["name"], repo) if repo and os.path.isdir(repo)
                    else {"project": p["name"], "skip": "repo missing on this machine"})
        except Exception as exc:
            return {"project": p.get("name"), "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    workers = min(len(projects), max(1, int(os.environ.get("ORCH_RELEASE_PROJECT_WORKERS", "4"))))
    if not projects:
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers,
                                               thread_name_prefix="release-project") as pool:
        return list(pool.map(worker, projects))


# ── dependency-aware release orchestration ────────────────────────────────────
#
# When apps share a capability (e.g. a shared library, an API contract), a
# breaking change must ship to the dependency BEFORE the dependent. These
# functions take an explicit dependency graph and a set of apps with pending
# changes, then return a safe release order via topological sort.


class CyclicDependencyError(Exception):
    """Raised when the dependency graph contains a cycle."""


def _topo_sort(graph):
    """Kahn's algorithm. Returns a list in dependency-first order.

    *graph* maps each node to its list of dependencies (nodes it depends ON).
    Only nodes present as keys are considered; dependency targets that are not
    keys themselves are treated as having no dependencies of their own.

    Raises CyclicDependencyError if the graph contains a cycle.
    """
    # Build adjacency (dependency -> list of dependents) and in-degree.
    all_nodes = set(graph)
    for deps in graph.values():
        all_nodes.update(deps)
    adjacency = {n: [] for n in all_nodes}
    in_degree = {n: 0 for n in all_nodes}
    for node, deps in graph.items():
        for dep in deps:
            adjacency[dep].append(node)
            in_degree[node] += 1

    queue = sorted(n for n in all_nodes if in_degree[n] == 0)
    order = []
    while queue:
        node = queue.pop(0)
        order.append(node)
        for dependent in sorted(adjacency[node]):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(order) != len(all_nodes):
        remaining = sorted(all_nodes - set(order))
        raise CyclicDependencyError(
            f"dependency cycle among: {', '.join(remaining)}"
        )
    return order


def sequence_releases(dep_graph, changed_apps):
    """Return an ordered list of release steps for *changed_apps* respecting *dep_graph*.

    Parameters
    ----------
    dep_graph : dict[str, list[str]]
        Maps each app to the apps it depends on.  Apps not in the dict are
        assumed to have no dependencies.
    changed_apps : set[str] | list[str]
        The apps that have pending changes and need to be released.

    Returns
    -------
    list[str]
        Apps in safe deploy order (dependencies before dependents).  Only apps
        in *changed_apps* appear, but ordering respects the full graph.

    Raises
    ------
    CyclicDependencyError
        If *dep_graph* contains a cycle (even among unchanged apps).
    """
    changed = set(changed_apps)
    if not changed:
        return []

    # Ensure every changed app appears in the graph so topo_sort sees it.
    full_graph = {app: list(deps) for app, deps in dep_graph.items()}
    for app in changed:
        if app not in full_graph:
            full_graph[app] = []

    total_order = _topo_sort(full_graph)
    return [app for app in total_order if app in changed]


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
