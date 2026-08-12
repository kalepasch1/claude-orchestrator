#!/usr/bin/env python3
"""
clean_clone_gate.py - fresh-clone install verification.

build_gate.py proves the code compiles in a worktree that SHARES the main repo's warm
node_modules. That hides every "works on my machine" bug: an uncommitted lockfile, a source
file that exists on disk but was never `git add`ed, a dependency only present because someone
installed it locally, a .gitignore/.vercelignore rule that strips a build input. Vercel starts
from the COMMITTED TREE ONLY and runs the project's real install command — so does this gate.

  export the committed tree with `git archive` (no .git, no node_modules, no untracked files)
  -> run the real install command (`npm ci` when the lockfile is committed)
  -> run the real build command
  -> record a proof keyed on the TREE sha so the (expensive) run is done at most once per tree.

Entry points:
  gate(project, branch) -> (ok, log)  fail-closed for the merge/release path
  verify(repo, ref)     -> dict       one repo, cache-aware
  run(limit=N)          -> dict       periodic sweep, budgeted (this is the expensive bot)
Structured JSONL goes to .runtime/logs/clean-clone-gate.log.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import guard_tasks
import proof_graph

NAME = "clean-clone-gate"
ENABLED = os.environ.get("ORCH_CLEAN_CLONE_GATE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
BREAK_GLASS = os.environ.get("ORCH_CLEAN_CLONE_GATE_BREAK_GLASS", "false").lower() in ("1", "true", "yes", "on")
FILE_TASKS = os.environ.get("ORCH_CLEAN_CLONE_GATE_FILE_TASKS", "true").lower() in ("1", "true", "yes", "on")
INSTALL_TIMEOUT = int(os.environ.get("ORCH_CLEAN_CLONE_INSTALL_TIMEOUT", "1200"))
BUILD_TIMEOUT = int(os.environ.get("ORCH_CLEAN_CLONE_BUILD_TIMEOUT", "1800"))
PER_RUN_LIMIT = int(os.environ.get("ORCH_CLEAN_CLONE_PER_RUN_LIMIT", "2"))
MAX_TASKS_PER_RUN = int(os.environ.get("ORCH_CLEAN_CLONE_MAX_TASKS_PER_RUN", "6"))
RETRACT_STALE = os.environ.get("ORCH_CLEAN_CLONE_RETRACT_STALE", "true").lower() in ("1", "true", "yes", "on")
KIND = "clean-clone"

# A failure that is about THIS MACHINE's connectivity, not about the committed tree. These must
# never block a merge — they are inconclusive, not red.
_NETWORK = re.compile(
    r"ENOTFOUND|EAI_AGAIN|ECONNRESET|ETIMEDOUT|ECONNREFUSED|ERR_SOCKET|network timeout|"
    r"request to https?://\S+ failed|registry\.npmjs\.org.*(?:failed|timeout)|"
    r"getaddrinfo|proxy|EPROTO|self.signed certificate", re.I)

# Package managers deliberately fail frozen installs when the manifest and lockfile disagree.
# That is repairable in a pristine export: retry once non-frozen, then let the real build prove
# whether the resolved graph is deployable. This stays narrow so unrelated install failures do not
# get concealed by a broad fallback.
_LOCKFILE_DRIFT = re.compile(
    r"package-lock\.json.*(?:in sync|up to date)|"
    r"Missing:\s+\S+\s+from lock file|"
    r"ERR_PNPM_OUTDATED_LOCKFILE|pnpm-lock\.yaml.*not up to date|"
    r"lockfile would have been modified|"
    r"lockfile needs to be updated.*--frozen-lockfile|"
    r"can only install packages when your package\.json and package-lock\.json.*in sync|"
    r"npm ci` can only install|YN0028|cannot install with .frozen-lockfile.",
    re.I | re.S,
)


def unfrozen_install_command(cmd):
    """Map a known frozen package-manager install to one non-frozen retry."""
    try:
        normalized = " ".join(str(cmd or "").split())
        if not normalized:
            return ""
        if re.match(r"^npm\s+ci(?:\s|$)", normalized):
            return re.sub(r"^npm\s+ci\b", "npm install", normalized, count=1)
        if re.match(r"^pnpm\s+install(?:\s|$)", normalized):
            unfrozen = re.sub(r"(?:^|\s)--frozen-lockfile(?=\s|$)", " ", normalized)
        elif re.match(r"^yarn\s+install(?:\s|$)", normalized):
            unfrozen = re.sub(r"(?:^|\s)--(?:immutable|frozen-lockfile)(?=\s|$)",
                              " ", normalized)
        else:
            return ""
        unfrozen = " ".join(unfrozen.split())
        return unfrozen if unfrozen != normalized else ""
    except Exception:
        return ""


def _home():
    return os.environ.get("CLAUDE_ORCH_HOME",
                          os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".runtime"))


def _log_event(event):
    """Append one structured JSONL record to .runtime/logs/<name>.log (fail-soft)."""
    row = dict(event)
    row.setdefault("at", time.time())
    row.setdefault("bot", NAME)
    try:
        path = os.path.join(_home(), "logs")
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, NAME + ".log"), "a") as f:
            f.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")
    except OSError:
        pass
    return row


def _git(repo, *args, **kw):
    try:
        r = subprocess.run(["git"] + list(args), cwd=repo, capture_output=True,
                           text=True, timeout=kw.get("timeout", 60))
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except (OSError, subprocess.SubprocessError) as e:
        return -1, "", str(e)


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


def resolve_ref(repo, ref):
    """Return a ref that exists locally, preferring the caller's choice."""
    for candidate in (ref, "HEAD"):
        if not candidate:
            continue
        rc, _, _ = _git(repo, "rev-parse", "--verify", "--quiet", str(candidate) + "^{commit}")
        if rc == 0:
            return str(candidate)
    return "HEAD"


def tree_sha(repo, ref):
    """The content id of the committed tree — the real cache key for this gate."""
    rc, out, _ = _git(repo, "rev-parse", "%s^{tree}" % ref)
    return out if rc == 0 else ""


def export_tree(repo, ref, dest):
    """Materialise ONLY the committed tree (git archive == what a fresh clone would give)."""
    os.makedirs(dest, exist_ok=True)
    try:
        archive = subprocess.run(["git", "archive", "--format=tar", ref], cwd=repo,
                                 capture_output=True, timeout=300)
        if archive.returncode != 0:
            return False, (archive.stderr or b"").decode("utf-8", "replace")[-800:]
        untar = subprocess.run(["tar", "-x", "-C", dest], input=archive.stdout,
                               capture_output=True, timeout=300)
        if untar.returncode != 0:
            return False, (untar.stderr or b"").decode("utf-8", "replace")[-800:]
        return True, ""
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)


def _deploy_root(repo):
    """The directory Vercel actually deploys from (holds vercel.json), relative to the tree."""
    try:
        import dependency_prewarm
        for root in (dependency_prewarm.package_roots(repo) or []):
            if os.path.isfile(os.path.join(root, "vercel.json")):
                return os.path.relpath(root, repo)
    except (ImportError, AttributeError, TypeError, ValueError):
        pass
    return "."


def build_root(repo, rel_root="."):
    """The package root the BUILD command actually targets, relative to the tree.

    `_deploy_root()` answers "where is vercel.json", but `build_command()` delegates
    to `build_gate.detect_build_cmd()`, which scans every package root and picks the
    first with a real build script. In a monorepo those are different directories,
    and nothing reconciled them — see `install_command()` for what that cost.
    """
    try:
        import build_gate
        import dependency_prewarm
        cmd = build_gate.detect_build_cmd(repo) or ""
        match = re.search(r"--prefix\s+(\S+)", cmd)
        if match:
            candidate = match.group(1).strip().strip("'\"")
            if candidate and os.path.isdir(os.path.join(repo, candidate)):
                return candidate.rstrip("/")
        # No --prefix: the command runs at the deploy root unless that root has no
        # package.json at all, in which case the sole package root is the target.
        if os.path.isfile(os.path.join(repo, rel_root, "package.json")):
            return rel_root
        roots = dependency_prewarm.package_roots(repo) or []
        if len(roots) == 1:
            return os.path.relpath(roots[0], repo)
    except Exception:  # fail-soft: an unresolvable build root must not break the gate
        pass
    return rel_root


def install_command(root_dir, repo, ref, rel_root, install_root=None):
    """The project's REAL install command, exactly as the deploy platform would run it.

    `install_root` is where the dependencies must LAND. It defaults to `rel_root`
    (the deploy root) but is the build's package root when the two differ.

    That divergence is the bug this parameter exists for. beethoven commits a
    lockfile at the repo root next to a package.json with **no dependencies at
    all** — the deployable app is `web/`. The gate resolved the install against
    the deploy root, so it ran a bare `npm ci` that reported "up to date in 2s"
    while installing nothing, then ran `npm --prefix web run build` against a
    `web/` that had no node_modules. The failure surfaced as
    `sh: nuxt: command not found`, which reads like a missing dependency and sent
    repair passes looking for one, when nothing had been installed for that
    package in the first place. Warm repos hide it completely: `web/node_modules`
    is already on disk locally, so this only ever failed from a pristine export —
    the works-on-my-machine drift class the gate exists to catch.
    """
    install_root = install_root or rel_root
    cfg = _load_json(os.path.join(root_dir, "vercel.json"))
    configured = str(cfg.get("installCommand") or "").strip()
    if configured:
        return configured
    prefix = "" if install_root == "." else install_root.rstrip("/") + "/"
    npm_prefix = "" if install_root == "." else " --prefix %s" % install_root.rstrip("/")
    for lock, cmd in (("package-lock.json", "npm ci%s --no-audit --no-fund" % npm_prefix),
                      ("pnpm-lock.yaml", "pnpm install --frozen-lockfile"),
                      ("yarn.lock", "yarn install --immutable")):
        rc, out, _ = _git(repo, "ls-tree", "-r", "--name-only", ref, "--", prefix + lock)
        if rc == 0 and out.strip():
            if lock != "package-lock.json" and install_root != ".":
                # pnpm/yarn have no --prefix; run them in the package directory.
                return "cd %s && %s" % (install_root.rstrip("/"), cmd)
            return cmd
    if os.path.isfile(os.path.join(repo, install_root, "package.json")):
        return "npm install%s --no-audit --no-fund" % npm_prefix
    return ""


def build_command(root_dir, repo):
    """The project's REAL build command (Vercel's buildCommand wins, as in build_gate)."""
    cfg = _load_json(os.path.join(root_dir, "vercel.json"))
    configured = str(cfg.get("buildCommand") or "").strip()
    if configured:
        return configured
    try:
        import build_gate
        detected = build_gate.detect_build_cmd(repo)
        if detected:
            return detected
    except (ImportError, AttributeError, TypeError):
        pass
    scripts = (_load_json(os.path.join(root_dir, "package.json")).get("scripts") or {})
    return "npm run build" if "build" in scripts else ""


def _step(cmd, cwd, timeout, env):
    try:
        r = subprocess.run(["bash", "-lc", cmd], cwd=cwd, capture_output=True,
                           text=True, timeout=timeout, env=env)
        return r.returncode, ((r.stdout or "")[-4000:] + "\n" + (r.stderr or "")[-4000:]).strip()
    except subprocess.TimeoutExpired:
        return 124, "timed out after %ss: %s" % (timeout, cmd)
    except (OSError, subprocess.SubprocessError) as e:
        return -1, "could not run `%s`: %s" % (cmd, e)


def verify(repo, ref=None, project=None, force=False, cache_only=False):
    """Install + build a PRISTINE export of the committed tree. Cache-aware; never raises."""
    result = {"project": project, "repo": repo, "ref": ref, "tree": "", "ok": None,
              "cached": False, "skipped": None, "install_cmd": "", "build_cmd": "", "log": ""}
    if not ENABLED:
        result["skipped"] = "disabled"
        return result
    if not repo or not os.path.isdir(repo):
        result["skipped"] = "repo not on this machine"
        return result
    ref = resolve_ref(repo, ref)
    result["ref"] = ref
    tree = tree_sha(repo, ref)
    result["tree"] = tree
    if not tree:
        result["skipped"] = "could not resolve tree for %s" % ref
        return result

    rel_root = _deploy_root(repo)
    root_dir = repo if rel_root == "." else os.path.join(repo, rel_root)
    # Install where the BUILD will look, not merely where vercel.json lives. When the
    # two diverge the gate used to install one package and build another, and reported
    # the resulting `command not found` as a dependency problem.
    inst_root = build_root(repo, rel_root)
    result["install_root"] = inst_root
    icmd = install_command(root_dir, repo, ref, rel_root, install_root=inst_root)
    bcmd = build_command(root_dir, repo)
    result["install_cmd"], result["build_cmd"] = icmd, bcmd
    if not bcmd and not icmd:
        result["skipped"] = "no install/build command (nothing to verify)"
        return result

    # The install root is part of the signature: the same tree installed into a
    # different package is a different proof, and reusing the old green one would
    # re-hide exactly this failure.
    signature = "clean-clone[%s->%s] install=%s && build=%s" % (
        rel_root, inst_root, icmd or "-", bcmd or "-")
    if not force:
        try:
            cached = proof_graph.reusable_verification(repo, tree, signature, KIND)
        except (OSError, ValueError, TypeError):
            cached = None
        if cached:
            result.update({"ok": True, "cached": True,
                           "log": "reused green clean-clone proof for tree %s" % tree[:12]})
            return result
    if cache_only:
        result["skipped"] = "no cached proof for tree %s (deferred: per-run budget)" % tree[:12]
        return result

    tmp = tempfile.mkdtemp(prefix="clean-clone-")
    try:
        exported, err = export_tree(repo, ref, tmp)
        if not exported:
            result["skipped"] = "git archive failed: %s" % err
            return result
        work = tmp if rel_root == "." else os.path.join(tmp, rel_root)
        env = os.environ.copy()
        # Inherited NODE_ENV=production makes npm omit devDependencies and every build that needs
        # a devDependency then fails for the wrong reason (same bug periodic.py strips at the top).
        env.pop("NODE_ENV", None)
        env["CI"] = "1"
        parts = []
        if icmd:
            rc, out = _step(icmd, work, INSTALL_TIMEOUT, env)
            parts.append("$ %s\n%s" % (icmd, out))
            if rc != 0 and not _NETWORK.search(out) and _LOCKFILE_DRIFT.search(out):
                fallback = unfrozen_install_command(icmd)
                if fallback:
                    result["install_fallback"] = fallback
                    rc, out = _step(fallback, work, INSTALL_TIMEOUT, env)
                    parts.append("$ %s   # lockfile drift: retried unfrozen\n%s" % (fallback, out))
                    if rc == 0:
                        result["install_cmd"] = fallback
            if rc != 0:
                if _NETWORK.search(out):
                    result["log"] = "\n\n".join(parts)
                    result["skipped"] = "install could not reach the registry (inconclusive)"
                    return result
                fallback = (unfrozen_install_command(icmd)
                            if _LOCKFILE_DRIFT.search(out) else "")
                if fallback:
                    retry_rc, retry_out = _step(fallback, work, INSTALL_TIMEOUT, env)
                    parts.append("$ %s  # one lockfile-drift recovery retry\n%s"
                                 % (fallback, retry_out))
                    rc, out = retry_rc, retry_out
                if rc != 0:
                    result["log"] = "\n\n".join(parts)
                    if _NETWORK.search(out):
                        result["skipped"] = "install could not reach the registry (inconclusive)"
                        return result
                    result["ok"] = False
                    result["failed_step"] = "install"
                    return result
        if bcmd:
            rc, out = _step(bcmd, work, BUILD_TIMEOUT, env)
            parts.append("$ %s\n%s" % (bcmd, out))
            if rc != 0:
                result["log"] = "\n\n".join(parts)
                if _NETWORK.search(out):
                    result["skipped"] = "build could not reach the network (inconclusive)"
                    return result
                result["ok"] = False
                result["failed_step"] = "build"
                return result
        result["ok"] = True
        result["log"] = "\n\n".join(parts)[-6000:]
        try:
            proof_graph.record_verification(repo, tree, signature, KIND, True)
        except (OSError, ValueError, TypeError):
            pass
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def gate(project_name, branch=None, force=False):
    """Merge-path gate. FAIL-CLOSED on a red clean-clone; inconclusive runs never block."""
    if not ENABLED:
        return True, "clean_clone_gate disabled"
    rows = db.select("projects", {"select": "*", "name": "eq.%s" % project_name}) or [{}]
    p = rows[0]
    repo = p.get("repo_path") or ""
    ref = branch or p.get("prod_branch") or p.get("default_base")
    result = verify(repo, ref, project_name, force=force)
    _log_event({"event": "gate", "project": project_name, "ref": result.get("ref"),
                "tree": result.get("tree"), "ok": result.get("ok"),
                "cached": result.get("cached"), "skipped": result.get("skipped")})
    if result.get("skipped"):
        return True, "clean_clone_gate: %s" % result["skipped"]
    if result.get("ok"):
        return True, ("clean_clone_gate GREEN%s (tree %s)"
                      % (" [cached]" if result["cached"] else "", (result["tree"] or "")[:12]))
    log = ("A pristine export of the committed tree FAILS at the %s step. Either the build is "
           "broken outright, or something it needs is not committed (missing lockfile, untracked "
           "source file, ignore rule stripping a build input) — compare against a warm local run.\n"
           "  install: %s\n  build:   %s\n\n%s"
           % (result.get("failed_step"), result["install_cmd"], result["build_cmd"],
              (result.get("log") or "")[-4000:]))
    if BREAK_GLASS:
        return True, "BREAK-GLASS override (ORCH_CLEAN_CLONE_GATE_BREAK_GLASS):\n" + log
    return False, log


_SIG_NOISE = re.compile(r"0x[0-9a-fA-F]+|\b[0-9a-f]{7,40}\b|/[^\s'\"]+|\d+")


def failure_signature(result):
    """A stable id for WHAT IS BROKEN, independent of which commit exposed it.

    The slug used to be keyed on the TREE sha, so pareto-2080's unchanged root cause (missing
    DATABASE_URL, DIRECT_URL, SUPABASE_KEY, CRON_SECRET, AGENT_SIGNING_SECRET, APP_URL,
    RESEND_API_KEY for check-runtime-config) filed a brand-new task on every single commit —
    four open duplicates for one problem, and beethoven three more. Key on the normalised
    failure text instead: the same breakage refiles nothing, a different breakage still does.
    """
    body = "%s|%s" % (result.get("failed_step") or "?", (result.get("log") or "")[-2500:])
    return hashlib.sha256(_SIG_NOISE.sub("N", body).encode("utf-8", "replace")).hexdigest()[:10]


def _file_task(project_row, result, filer):
    """A red clean-clone must produce work, not just a log line."""
    if not FILE_TASKS:
        return "disabled"
    slug = guard_tasks.stable_slug("cleanclone", project_row.get("name", "app"),
                                   failure_signature(result))
    return filer.file(
        project_row.get("id"), slug,
        ("A pristine export of the committed tree (`git archive %s`) fails to %s.\n\n"
                       "FIRST establish which of these it is:\n"
                       "  (a) the build is simply broken — the same command fails in the warm repo too;\n"
                       "  (b) works-on-my-machine drift — it passes warm and only fails from the\n"
                       "      committed tree (missing lockfile, untracked source file, or a\n"
                       "      .gitignore/.vercelignore rule stripping a build input).\n"
                       "Case (b) is invisible to build_gate and is what breaks Vercel.\n\n"
                       "install: %s\nbuild: %s\n\nLog tail:\n%s\n\n"
                       "Reproduce with: python3 runner/clean_clone_gate.py %s"
                       % (result.get("ref"), result.get("failed_step"), result.get("install_cmd"),
                          result.get("build_cmd"), (result.get("log") or "")[-2500:],
                          project_row.get("name", ""))),
        severity=guard_tasks.HIGH, project_name=project_row.get("name", ""),
        title="%s: clean clone fails at the %s step" % (project_row.get("name", ""),
                                                        result.get("failed_step")),
        escalate_why=(result.get("log") or "")[-800:])


def retract_stale(project_row, live_slugs):
    """Withdraw open clean-clone tasks whose failure no longer reproduces.

    A project that now verifies GREEN — or that fails a DIFFERENT way — must not keep its old
    claims open, otherwise the queue accumulates one dead task per commit forever.
    """
    if not RETRACT_STALE or not project_row.get("id"):
        return 0
    prefix = guard_tasks.stable_slug("cleanclone", project_row.get("name", "app"), limit=200)
    try:
        rows = db.select("tasks", {"select": "id,slug", "project_id": "eq.%s" % project_row["id"],
                                   "slug": "like.%s-*" % prefix, "state": "eq.QUEUED",
                                   "limit": "200"}) or []
    except Exception:                                   # noqa: BLE001
        return 0
    closed = 0
    for row in rows:
        if row.get("slug") in live_slugs:
            continue
        try:
            db.update("tasks", {"id": row["id"]},
                      {"state": "CLOSED",
                       "note": "clean_clone_gate: retracted — this failure no longer reproduces "
                               "for %s" % project_row.get("name", "")})
            closed += 1
            _log_event({"event": "task_retracted", "slug": row.get("slug"),
                        "project": project_row.get("name")})
        except Exception as exc:                        # noqa: BLE001
            _log_event({"event": "retract_error", "slug": row.get("slug"), "error": str(exc)[:300]})
    return closed


def run(limit=None):
    """Budgeted periodic sweep — expensive, so cached trees are free and only N misses run."""
    if not ENABLED:
        print("clean_clone_gate: disabled")
        return {"enabled": False}
    budget = PER_RUN_LIMIT if limit is None else int(limit)
    projects = db.select("projects", {"select": "*"}) or []
    filer = guard_tasks.Filer(NAME, max_per_run=MAX_TASKS_PER_RUN)
    summary = {"checked": 0, "cached": 0, "green": 0, "red": 0, "skipped": 0, "tasks_retracted": 0}
    for p in projects:
        repo = p.get("repo_path") or ""
        if not repo or not os.path.isdir(repo):
            continue
        ref = p.get("prod_branch") or p.get("default_base")
        # Cached trees are free, so every project is reported every cycle; only `budget` cache
        # MISSES actually pay for an install+build this run. The rest are deferred, not dropped.
        peek = verify(repo, ref, p.get("name"), cache_only=budget <= 0)
        if not peek.get("cached") and peek.get("ok") is not None:
            budget -= 1
        summary["checked"] += 1
        if peek.get("cached"):
            summary["cached"] += 1
        if peek.get("skipped"):
            summary["skipped"] += 1
            print("  %-14s SKIP %s" % (p.get("name"), peek["skipped"])[:170], flush=True)
        elif peek.get("ok"):
            summary["green"] += 1
            print("  %-14s GREEN%s tree=%s" % (p.get("name"), " [cached]" if peek["cached"] else "",
                                               (peek.get("tree") or "")[:12]), flush=True)
        else:
            summary["red"] += 1
            print("  %-14s RED at %s step: %s" % (p.get("name"), peek.get("failed_step"),
                                                  (peek.get("log") or "")[-300:]), flush=True)
            _file_task(p, peek, filer)
        # A conclusive verdict (green or red) supersedes every earlier claim about this project.
        # An inconclusive SKIP proves nothing, so it must not retract anything.
        if peek.get("ok") is not None:
            live = set()
            if peek.get("ok") is False:
                live.add(guard_tasks.stable_slug("cleanclone", p.get("name", "app"),
                                                 failure_signature(peek)))
            summary["tasks_retracted"] += retract_stale(p, live)
        _log_event({"event": "verify", "project": p.get("name"), "ref": peek.get("ref"),
                    "tree": peek.get("tree"), "ok": peek.get("ok"), "cached": peek.get("cached"),
                    "skipped": peek.get("skipped"), "failed_step": peek.get("failed_step")})
    summary.update(filer.counters())
    _log_event({"event": "sweep", **summary})
    print("clean_clone_gate: %(checked)d checked (%(cached)d cached), %(green)d green, "
          "%(red)d red, %(skipped)d skipped, %(tasks_retracted)d retracted" % summary)
    print("clean_clone_gate: " + filer.summary_line())
    return summary


def stats():
    """Module statistics for the dashboard."""
    try:
        rows = proof_graph.stats() or {}
        return {"enabled": ENABLED, "per_run_limit": PER_RUN_LIMIT,
                "proof_rows": rows.get("proofs", 0)}
    except (OSError, TypeError, ValueError):
        return {"enabled": ENABLED, "per_run_limit": PER_RUN_LIMIT, "proof_rows": 0}


if __name__ == "__main__":
    argv = sys.argv[1:]
    forced = "--force" in argv
    args = [a for a in argv if not a.startswith("-")]
    if args and os.path.isdir(args[0]):
        res = verify(args[0], args[1] if len(args) > 1 else None,
                     os.path.basename(args[0]), force=forced)
        print(json.dumps({k: v for k, v in res.items() if k != "log"}, indent=2, default=str))
        print((res.get("log") or "")[-3000:])
    elif args:
        ok, log = gate(args[0], args[1] if len(args) > 1 else None, force=forced)
        print("CLEAN-CLONE", "GREEN" if ok else "RED")
        print(log[:4000])
    else:
        run()
