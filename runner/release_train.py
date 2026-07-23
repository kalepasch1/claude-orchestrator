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

# BATCH-DEV defaults: ship agent work to the unified staging branch quickly, but promote
# prod in QA'd batches. This avoids improvement-by-improvement Vercel churn while keeping
# the queue draining. Hotfix lanes can still override these envs explicitly.
# Cost-control floors: ordinary releases cannot silently regress to one-change/hourly
# production deploys through stale process or machine-local environment overrides.
# The explicit AUTOPILOT_RELEASE_BLOCKER_FLUSH hot lane may still set these module
# values to 1/0 temporarily for a genuine production blocker.
MIN_BATCH = max(10, int(os.environ.get("RELEASE_MIN_BATCH", os.environ.get("ORCH_RELEASE_BATCH_MIN", "10"))))
RELEASE_INTERVAL_HOURS = max(6.0, float(os.environ.get("RELEASE_INTERVAL_HOURS", os.environ.get("ORCH_RELEASE_INTERVAL_HOURS", "6"))))
STAGING = os.environ.get("ORCH_STAGING_BRANCH", "orchestrator/dev")
RELEASE_FIX_PREFIXES = ("relfix-", "buildfix-", "deployfix-")
QA_FIX_PREFIXES = ("qafix-",)
RED_GATE_COOLDOWN_MIN = float(os.environ.get("ORCH_RELEASE_RED_GATE_COOLDOWN_MIN", "180"))
QA_EVIDENCE_CHARS_PER_STREAM = 12000

# release_kpi writes this: the set of apps whose recent prod deploys keep failing, so we promote their
# tests to a HARD release gate until they recover (self-tuning loop). Read fail-soft.
_GATE_FILE = os.path.join(tempfile.gettempdir(), "orch-release-gate.json")
_FLOW_LOCK = threading.Lock()


def _truthy(name, default=False):
    val = os.environ.get(name)
    if val is None:
        return bool(default)
    return str(val).lower() in ("1", "true", "yes", "on")


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
    if gate == "qa":
        prefixes = QA_FIX_PREFIXES
    elif gate in ("build", "refresh", "push"):
        prefixes = RELEASE_FIX_PREFIXES
    else:
        prefixes = QA_FIX_PREFIXES + RELEASE_FIX_PREFIXES
    out = []
    for row in rows:
        slug = str(row.get("slug") or "")
        note = str(row.get("note") or "").lower()
        if slug.startswith(prefixes) or "release_train" in note or "vercel" in note:
            out.append(row)
    return out


def _hold_for_open_fix(p, project, gate):
    if not _truthy("ORCH_RELEASE_HOLD_WHILE_FIX_OPEN", True):
        return None
    fixes = _open_release_fix_tasks(p, gate=gate)
    if not fixes:
        return None
    hot = fixes[0]
    return {"project": project, "gate": gate, "note": "held for open release-fix task",
            "fix": hot.get("slug"), "fix_state": hot.get("state")}


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


def _insert_failed_release(project, gate, ahead, from_sha, to_sha, note):
    """Insert one failed gate row per gate/SHA/cooldown window."""
    if _recent_failed_gate(project, to_sha, gate):
        return None
    return db.insert("releases", {"project": project, "from_sha": from_sha or "",
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
            subprocess.run(["git", "merge", "--abort"], cwd=tmp, capture_output=True)
            log = ((r.stdout or "")[-1500:] + "\n" + (r.stderr or "")[-1500:]).strip()
            return False, log or "staging/prod merge conflict"
        return True, "staging refreshed from prod"
    except subprocess.TimeoutExpired:
        return False, "staging refresh merge timed out"
    except Exception as e:
        return False, f"staging refresh error: {e}"
    finally:
        _git(repo, "worktree", "remove", "--force", tmp)
        shutil.rmtree(tmp, ignore_errors=True)


def _merge_into_staging(repo, branch):
    """Merge an agent branch into staging via an ephemeral worktree (no checkout of the main tree)."""
    import tempfile, shutil
    tmp = tempfile.mkdtemp(prefix="stg-")
    try:
        if _git(repo, "worktree", "add", "-f", tmp, STAGING).returncode != 0:
            return False
        r = subprocess.run(["git", "merge", "--no-ff", "-m", f"train: {branch}", branch],
                           cwd=tmp, capture_output=True, text=True)
        if r.returncode != 0:
            subprocess.run(["git", "merge", "--abort"], cwd=tmp, capture_output=True)
            return False
        return True
    finally:
        _git(repo, "worktree", "unlock", tmp)  # locked worktrees survive remove --force (see above)
        _git(repo, "worktree", "remove", "--force", tmp)
        shutil.rmtree(tmp, ignore_errors=True)
        _git(repo, "worktree", "prune")


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
    try:
        import build_gate
        if bcmd:
            held = _hold_for_open_fix(p, project, "build")
            if held:
                return held
            if _recent_failed_gate(project, staging_sha, "build"):
                return {"project": project, "build": "HELD", "note": "unchanged staging SHA already failed build recently"}
            bok, blog = build_gate.run_build(repo, STAGING, bcmd)
            if not bok:
                _self_heal_build(p, project, repo, STAGING, blog)  # queue a targeted build-fix task
                _insert_failed_release(project, "build", ahead, release_base_sha, staging_sha,
                                       f"staging BUILD red — self-heal queued: {blog[-120:]}")
                return {"project": project, "build": "RED", "note": "staging build not green; build-fix task queued"}
    except Exception:
        pass
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
    ver = _next_version()
    changelog = _git(repo, "log", "--oneline", f"{last_good}..{to_sha}").stdout[:2000]
    rel = db.insert("releases", {"project": project, "version": ver, "from_sha": last_good, "to_sha": to_sha,
                    "n_changes": int(ahead), "changelog": changelog, "deploy_status": "pending"})
    pushed = None
    if push_on:
        pr = _git(repo, "push", "origin", f"{STAGING}:{prod}", timeout=300)
        pushed = pr.returncode == 0
        if pushed:
            # Keep local prod fresh when possible, but do not fail a good remote
            # release just because the operator has prod checked out with edits.
            _git(repo, "fetch", "origin", prod)
            _git(repo, "fetch", ".", f"{STAGING}:{prod}")
        else:
            plog = ((pr.stdout or "")[-1000:] + "\n" + (pr.stderr or "")[-1000:]).strip()
            _self_heal_release_conflict(p, project, repo, prod, plog or "push staging to prod failed")
        db.update("releases", {"project": project, "to_sha": to_sha},
                  {"deploy_status": "building" if pushed else "failed",
                   "note": "" if pushed else ((pr.stderr or pr.stdout)[-160:] if (pr.stderr or pr.stdout) else "push failed")})
    print(f"release_train {project}: staged {merged}, released {ahead} changes to {prod} "
          f"(push={'on' if pushed else 'off/local'})")
    return {"project": project, "prod": prod, "released": ahead, "pushed": pushed}


def run_for(project):
    """Run at most one git-mutating release train per repository.

    Gate cooldowns alone cannot stop two processes that inspect the same SHA
    before either writes its failure row. Sharing the merge-train repo lock
    makes the check/build/push sequence single-flight across processes.
    """
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
    import json
    print(json.dumps(run(), indent=2, default=str))

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
