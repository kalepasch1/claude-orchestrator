#!/usr/bin/env python3
"""
bot_commit_verifier.py - no bot-authored commit propagates without a real parse check.

2026-07-30, hisanta/santas-secret-workshop: commit 26b414f9 "bot: auto-fix TypeScript errors
[ssw-quality-bot]" *removed* a backslash escape in a French string —

    fr: [... 'Centre d\\'aide' ...]   ->   fr: [... 'Centre d'aide' ...]

— which is an unterminated string literal. Production broke. The bot "fixed TypeScript errors"
by introducing a parse error, and nothing between that commit and prod ever parsed the file.
`tsc` finds it in 0.7s (TS1002: Unterminated string literal).

So: any commit whose author or message marks it bot-generated (`bot:`, `agent:`, `[*-bot]`,
`agent/*` branches) must pass a SYNTAX-ONLY check of the exact blobs it introduced before it can
propagate. Syntax-only is deliberate — it is seconds, not minutes, so it can sit on the merge
path, and it is exactly the failure class bots produce (mangled escapes, unbalanced brackets,
truncated files).

  node --check          .js .mjs .cjs
  tsc  (TS1xxx only)    .ts .tsx .jsx     (type errors are NOT the bot's problem; parse errors are)
  python3 -m py_compile .py
  json.loads            .json

Entry points:
  gate(project, branch, base) -> (ok, log)  fail-closed; the merge path calls this
  verify_commit(repo, sha)    -> dict       one commit
  run()                       -> dict       periodic sweep over recent history
Structured JSONL goes to .runtime/logs/bot-commit-verifier.log.
"""
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
import proof_graph

NAME = "bot-commit-verifier"
ENABLED = os.environ.get("ORCH_BOT_COMMIT_VERIFIER_ENABLED", "true").lower() in ("1", "true", "yes", "on")
BREAK_GLASS = os.environ.get("ORCH_BOT_COMMIT_VERIFIER_BREAK_GLASS", "false").lower() in ("1", "true", "yes", "on")
FILE_TASKS = os.environ.get("ORCH_BOT_COMMIT_VERIFIER_FILE_TASKS", "true").lower() in ("1", "true", "yes", "on")
SCAN_DEPTH = int(os.environ.get("ORCH_BOT_COMMIT_SCAN_DEPTH", "60"))
FILE_TIMEOUT = int(os.environ.get("ORCH_BOT_COMMIT_FILE_TIMEOUT", "90"))
MAX_FILES = int(os.environ.get("ORCH_BOT_COMMIT_MAX_FILES", "60"))
# v2: proofs recorded before the broken-tsc fail-open fix could mean "tsc never ran", so they
# must not be reused. Bump this whenever the checking semantics change.
KIND = "bot-commit-syntax-v2"

# Real conventions in this fleet, taken from `git log --oneline -200` across the repos:
#   "bot: auto-fix TypeScript errors [ssw-quality-bot]"   "bot: polish log [ssw-polish-bot]"
#   "chore: update ssw-bot-log for game-bot run ... [ssw-game-bot]"
#   "agent: remediate-weekly-lint-santas-secret-workshop-21ba53"   branch agent/<slug>
_BOT_MESSAGE = re.compile(
    r"^\s*(?:bot|agent)\s*[:/]"          # bot: ...   agent: ...
    r"|\[[A-Za-z0-9_]+(?:-[A-Za-z0-9_]+)*-bot\]"   # [ssw-quality-bot]
    r"|\bbot-authored\b|\bauto-fix\b|\[bot\]"
    r"|\bagent/[A-Za-z0-9._-]+", re.I | re.M)
_BOT_AUTHOR = re.compile(r"\[bot\]|bot@|noreply@|automation@|github-actions", re.I)

_SYNTAX_TS = re.compile(r"error TS(1\d{3})\b")
_ANY_TS_DIAG = re.compile(r"error TS\d+\b")
# TS1xxx is *mostly* the parse family, but a handful of TS1xxx codes are compiler-FLAG
# diagnostics that only appear because we parse a file standalone, outside its tsconfig
# (import.meta / top-level await / decorators / esModuleInterop). They are not defects and must
# never block a merge — they produced the only two false positives in the first fleet sweep
# (tomorrow: vitest.pure.config.ts, kalepasch-com: useSite.ts, both TS1343).
_TS_CONFIG_CODES = {
    "1192", "1202", "1203", "1205", "1206", "1207", "1208", "1219", "1259", "1286", "1287",
    "1288", "1323", "1324", "1343", "1375", "1378", "1432", "1470", "1471", "1479",
}
_TEXT_EXT = {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".py", ".json"}
_TS_EXT = {".ts", ".tsx", ".jsx"}
_NODE_EXT = {".js", ".mjs", ".cjs"}


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
        return r.returncode, r.stdout, r.stderr.strip()
    except (OSError, subprocess.SubprocessError) as e:
        return -1, "", str(e)


def is_bot_commit(message, author=""):
    """True when a commit is marked bot-generated by this fleet's conventions."""
    return bool(_BOT_MESSAGE.search(message or "") or _BOT_AUTHOR.search(author or ""))


def bot_commits(repo, ref="HEAD", base=None, depth=None):
    """Bot-authored commits on <ref> (optionally only those not already in <base>)."""
    args = ["log", "--format=%H%x1f%an <%ae>%x1f%s%x1e", "-n", str(depth or SCAN_DEPTH)]
    if base:
        rc, _, _ = _git(repo, "rev-parse", "--verify", "--quiet", str(base) + "^{commit}")
        if rc == 0:
            args = ["log", "--format=%H%x1f%an <%ae>%x1f%s%x1e", "%s..%s" % (base, ref)]
        else:
            args.append(ref)
    else:
        args.append(ref)
    rc, out, _ = _git(repo, *args)
    if rc != 0:
        return []
    found = []
    for record in out.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        parts = record.split("\x1f")
        if len(parts) < 3:
            continue
        sha, author, subject = parts[0].strip(), parts[1], parts[2]
        if is_bot_commit(subject, author):
            found.append({"sha": sha, "author": author, "subject": subject})
    return found


def _changed_files(repo, sha):
    """Files this commit ADDED or MODIFIED (deletions cannot contain a parse error)."""
    rc, out, _ = _git(repo, "show", "--pretty=format:", "--name-only", "--diff-filter=AM", sha)
    if rc != 0:
        return []
    files = [line.strip() for line in out.splitlines() if line.strip()]
    return [f for f in files if os.path.splitext(f)[1].lower() in _TEXT_EXT][:MAX_FILES]


_TSC_CACHE = {}


def _tsc_in(root):
    """A WORKING tsc under <root>, or "".

    Existence is not enough. The fleet's node_modules trees are constantly being relinked by
    dependency-prewarm, so `.bin/tsc` is regularly a symlink loop (hisanta) or a live symlink
    whose target module is gone (tomorrow: "Cannot find module .../typescript/bin/tsc"). A tsc
    that cannot start emits no diagnostics, which would silently turn this gate into a no-op —
    exactly the fail-open behaviour this bot exists to prevent. So: prove it runs.
    """
    for rel in (("node_modules", ".bin", "tsc"), ("node_modules", "typescript", "bin", "tsc")):
        candidate = os.path.join(root, *rel)
        try:
            if not (os.path.isfile(candidate) and os.access(candidate, os.X_OK)):
                continue
        except OSError:
            continue
        rc, out = _run([candidate, "--version"], timeout=30)
        if rc == 0 and "Version" in out:
            return candidate
    return ""


def _tsc_binary(repo):
    """Find a tsc for a parse-only check: the repo's own, then any package root's, then ANY
    project's in the fleet, then PATH. TS1xxx syntax codes are stable across versions, and a
    cold/broken node_modules must not silently disable the exact check that catches bot damage."""
    if repo in _TSC_CACHE:
        return _TSC_CACHE[repo]
    found = _tsc_in(repo)
    if not found:
        try:
            import dependency_prewarm
            for root in (dependency_prewarm.package_roots(repo) or []):
                found = found or _tsc_in(root)
        except (ImportError, AttributeError, TypeError, OSError):
            pass
    if not found:
        try:
            for row in (db.select("projects", {"select": "repo_path"}) or []):
                other = row.get("repo_path") or ""
                if other and other != repo and os.path.isdir(other):
                    found = _tsc_in(other)
                    if found:
                        break
        except (OSError, TypeError, ValueError):
            pass
    found = found or shutil.which("tsc") or ""
    _TSC_CACHE[repo] = found
    return found


def _run(cmd, cwd=None, timeout=None):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout or FILE_TIMEOUT)
        return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        return 124, "syntax check timed out after %ss" % (timeout or FILE_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as e:
        return -1, str(e)


def syntax_check_paths(paths, tsc="", cwd=None):
    """Parse-only check of real files on disk. Returns a list of {path, checker, error}.

    Pass <cwd> plus repo-relative <paths> so every checker reports repo-relative locations.
    """
    problems = []
    ts_batch = []
    for path in paths:
        ext = os.path.splitext(path)[1].lower()
        full = os.path.join(cwd, path) if cwd else path
        if ext in _NODE_EXT:
            rc, out = _run(["node", "--check", path], cwd=cwd)
            if rc != 0:
                problems.append({"path": path, "checker": "node --check", "error": out[-1200:]})
        elif ext in _TS_EXT:
            ts_batch.append(path)
        elif ext == ".py":
            rc, out = _run([sys.executable, "-m", "py_compile", path], cwd=cwd)
            if rc != 0:
                problems.append({"path": path, "checker": "py_compile", "error": out[-1200:]})
        elif ext == ".json":
            try:
                with open(full, encoding="utf-8") as f:
                    json.load(f)
            except (OSError, ValueError) as e:
                problems.append({"path": path, "checker": "json.loads", "error": str(e)[:1200]})
    if ts_batch:
        if not tsc:
            for path in ts_batch:
                problems.append({"path": path, "checker": "tsc", "error": "",
                                 "skipped": "no local typescript; parse check unavailable"})
        else:
            rc, out = _run([tsc, "--noEmit", "--skipLibCheck", "--allowJs", "--jsx", "preserve",
                            "--target", "esnext", "--module", "esnext",
                            "--moduleResolution", "node", "--experimentalDecorators"] + ts_batch,
                           cwd=cwd, timeout=FILE_TIMEOUT * 2)
            # Only TS1xxx (syntax family) counts, minus the compiler-flag codes above. TS2xxx
            # type/import errors are expected when a file is parsed out of its project context
            # and must never block a merge.
            syntax_lines = []
            for ln in out.splitlines():
                hit = _SYNTAX_TS.search(ln)
                if hit and hit.group(1) not in _TS_CONFIG_CODES:
                    syntax_lines.append(ln)
            if rc != 0 and not _ANY_TS_DIAG.search(out):
                # tsc failed to even start (missing module, bad flag). Silence here would mean
                # "clean", so report UNCHECKED instead of pretending the file parsed.
                for path in ts_batch:
                    problems.append({"path": path, "checker": "tsc", "error": out[-600:],
                                     "skipped": "tsc could not run; parse check unavailable"})
            elif syntax_lines:
                for path in ts_batch:
                    hits = [ln for ln in syntax_lines if os.path.basename(path) in ln]
                    if hits:
                        problems.append({"path": path, "checker": "tsc (TS1xxx)",
                                         "error": "\n".join(hits)[:1200]})
                if not any(p["checker"].startswith("tsc") for p in problems):
                    problems.append({"path": ",".join(ts_batch)[:200], "checker": "tsc (TS1xxx)",
                                     "error": "\n".join(syntax_lines)[:1200]})
    return problems


def check_paths_at(repo, ref, rel_paths):
    """Materialise <rel_paths> exactly as they exist at <ref> and parse them.

    Working from `git show <ref>:<path>` (not the working tree) is the whole point: the check
    must see what would be pushed, not what happens to be on this machine right now.
    """
    tmp = tempfile.mkdtemp(prefix="botcommit-")
    try:
        materialised = []
        for rel in rel_paths:
            dest = os.path.join(tmp, rel)
            try:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                rc, out, _ = _git(repo, "show", "%s:%s" % (ref, rel))
                if rc != 0:
                    continue
                with open(dest, "w", encoding="utf-8") as f:
                    f.write(out)
                materialised.append(rel)
            except OSError:
                continue
        problems = syntax_check_paths(materialised, _tsc_binary(repo), cwd=tmp)
        for p in problems:
            p["error"] = (p.get("error") or "").replace(tmp + os.sep, "").replace(tmp, "")
        return problems
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def verify_commit(repo, sha, force=False):
    """Parse the exact blobs a bot commit introduced. Never raises."""
    result = {"repo": repo, "sha": sha, "ok": True, "cached": False, "checked": 0,
              "skipped": None, "problems": [], "files": [], "unchecked": 0}
    if not ENABLED:
        result["skipped"] = "disabled"
        return result
    files = _changed_files(repo, sha)
    result["checked"] = len(files)
    result["files"] = files
    if not files:
        result["skipped"] = "no checkable source files in this commit"
        return result
    if not force:
        try:
            if proof_graph.reusable_verification(repo, sha, KIND, KIND):
                result["cached"] = True
                return result
        except (OSError, ValueError, TypeError):
            pass
    result["problems"] = check_paths_at(repo, sha, files)
    real = [p for p in result["problems"] if not p.get("skipped")]
    result["unchecked"] = len([p for p in result["problems"] if p.get("skipped")])
    result["ok"] = not real
    # Only a COMPLETE clean check earns a cached proof. Recording one while files went unchecked
    # would permanently freeze a fail-open result for that commit.
    if result["ok"] and not result["unchecked"]:
        try:
            proof_graph.record_verification(repo, sha, KIND, KIND, True)
        except (OSError, ValueError, TypeError):
            pass
    return result


def gate(project_name, branch, base=None, repo=None):
    """Merge-path gate. FAIL-CLOSED: a bot commit that does not parse cannot propagate."""
    if not ENABLED:
        return True, "bot_commit_verifier disabled"
    if not repo:
        rows = db.select("projects", {"select": "*", "name": "eq.%s" % project_name}) or [{}]
        p = rows[0]
        repo = p.get("repo_path") or ""
        base = base or p.get("prod_branch") or p.get("default_base")
    if not repo or not os.path.isdir(repo):
        return True, "repo not on this machine (skipped)"
    commits = bot_commits(repo, branch, base)
    if not commits:
        return True, "bot_commit_verifier: no bot-authored commits on %s" % branch
    bad, unchecked = [], 0
    for c in commits:
        res = verify_commit(repo, c["sha"])
        unchecked += int(res.get("unchecked") or 0)
        if not res["ok"]:
            bad.append((c, res))
    _log_event({"event": "gate", "project": project_name, "branch": branch, "base": base,
                "bot_commits": len(commits), "bad": len(bad), "unchecked": unchecked})
    if not bad:
        return True, ("bot_commit_verifier: %d bot commit(s) parse clean%s"
                      % (len(commits),
                         "" if not unchecked else
                         " (%d file(s) UNCHECKED — no working tsc on this machine)" % unchecked))
    log = "\n".join(
        "%s %s\n" % (c["sha"][:12], c["subject"]) +
        "\n".join("    %s [%s]\n      %s" % (p["path"], p["checker"], p["error"].replace("\n", "\n      "))
                  for p in res["problems"] if not p.get("skipped"))
        for c, res in bad)
    if BREAK_GLASS:
        return True, "BREAK-GLASS override (ORCH_BOT_COMMIT_VERIFIER_BREAK_GLASS):\n" + log
    return False, "bot-authored commit(s) do NOT parse — this is the hisanta failure mode:\n" + log


def _file_task(project_row, commit, result):
    """A broken bot commit becomes real remediation work, not a log line."""
    if not FILE_TASKS or not project_row.get("id"):
        return None
    slug = ("botfix-%s-%s" % (project_row.get("name", "app"), commit["sha"][:8]))[:60]
    detail = "\n".join("%s [%s]\n%s" % (p["path"], p["checker"], p["error"])
                       for p in result["problems"] if not p.get("skipped"))
    try:
        existing = db.select("tasks", {"select": "id,state", "slug": "eq.%s" % slug, "limit": "1"}) or []
        if existing and existing[0].get("state") not in ("DONE", "MERGED", "SHIPPED", "CLOSED", "SHELVED"):
            return None
        return db.insert("tasks", {
            "project_id": project_row["id"], "slug": slug, "state": "QUEUED", "kind": "build",
            "prompt": ("A BOT-AUTHORED commit introduced a file that does not parse. Fix the syntax "
                       "error without reverting the commit's intent, then confirm with "
                       "`python3 runner/bot_commit_verifier.py %s %s`.\n\n"
                       "commit: %s\nsubject: %s\nauthor: %s\n\n%s"
                       % (project_row.get("name", ""), commit["sha"], commit["sha"],
                          commit["subject"], commit.get("author", ""), detail))[:12000],
        })
    except (KeyError, TypeError, ValueError) as e:
        _log_event({"event": "task_error", "slug": slug, "error": str(e)})
        return None


def run(depth=None, project=None):
    """Periodic sweep: parse-check every recent bot commit on each project's prod branch."""
    if not ENABLED:
        print("bot_commit_verifier: disabled")
        return {"enabled": False}
    params = {"select": "*"}
    if project:
        params["name"] = "eq.%s" % project
    projects = db.select("projects", params) or []
    summary = {"projects": 0, "bot_commits": 0, "verified": 0, "cached": 0,
               "broken": 0, "live": 0, "already_fixed": 0, "tasks_filed": 0}
    for p in projects:
        repo = p.get("repo_path") or ""
        if not repo or not os.path.isdir(repo):
            continue
        summary["projects"] += 1
        ref = p.get("prod_branch") or p.get("default_base") or "HEAD"
        rc, _, _ = _git(repo, "rev-parse", "--verify", "--quiet", str(ref) + "^{commit}")
        if rc != 0:
            ref = "HEAD"
        commits = bot_commits(repo, ref, depth=depth or SCAN_DEPTH)
        summary["bot_commits"] += len(commits)
        broken_here = 0
        for c in commits:
            res = verify_commit(repo, c["sha"])
            if res.get("cached"):
                summary["cached"] += 1
                continue
            if res.get("skipped"):
                continue
            summary["verified"] += 1
            if res["ok"]:
                continue
            summary["broken"] += 1
            broken_here += 1
            # A broken commit deeper in history may already have been repaired by a later
            # commit. Only LIVE damage becomes remediation work; historical damage is logged.
            bad_paths = [prob["path"] for prob in res["problems"] if not prob.get("skipped")]
            live = [prob for prob in check_paths_at(repo, ref, bad_paths) if not prob.get("skipped")]
            _log_event({"event": "broken_bot_commit", "project": p.get("name"), "sha": c["sha"],
                        "subject": c["subject"], "problems": res["problems"],
                        "still_broken_at_tip": bool(live)})
            print("  %-14s BROKEN %s %s%s" % (p.get("name"), c["sha"][:12], c["subject"][:60],
                                              "" if live else "  (already remediated at %s)" % ref),
                  flush=True)
            for prob in res["problems"]:
                if not prob.get("skipped"):
                    print("      %s [%s] %s" % (prob["path"], prob["checker"],
                                                prob["error"].splitlines()[0][:120] if prob["error"] else ""),
                          flush=True)
            if not live:
                summary["already_fixed"] += 1
                continue
            summary["live"] += 1
            if _file_task(p, c, res):
                summary["tasks_filed"] += 1
            try:
                import notify
                notify.send("bot_commit_verifier: %s %s does not parse (%s)"
                            % (p.get("name"), c["sha"][:12], c["subject"][:80]))
            except (ImportError, OSError, TypeError):
                pass
        print("  %-14s %d bot commit(s) on %s, %d broken" % (p.get("name"), len(commits), ref, broken_here),
              flush=True)
    _log_event({"event": "sweep", **summary})
    print("bot_commit_verifier: %(projects)d project(s), %(bot_commits)d bot commit(s), "
          "%(verified)d newly verified, %(cached)d cached, %(broken)d broken "
          "(%(live)d still live, %(already_fixed)d already remediated), "
          "%(tasks_filed)d task(s) filed" % summary)
    return summary


def stats():
    """Module statistics for the dashboard."""
    try:
        projects = db.select("projects", {"select": "name,repo_path,prod_branch,default_base"}) or []
        total = 0
        for p in projects:
            repo = p.get("repo_path") or ""
            if repo and os.path.isdir(repo):
                total += len(bot_commits(repo, p.get("prod_branch") or p.get("default_base") or "HEAD"))
        return {"enabled": ENABLED, "scan_depth": SCAN_DEPTH, "recent_bot_commits": total}
    except (OSError, TypeError, ValueError):
        return {"enabled": ENABLED, "scan_depth": SCAN_DEPTH, "recent_bot_commits": 0}


if __name__ == "__main__":
    argv = sys.argv[1:]
    forced = "--force" in argv
    args = [a for a in argv if not a.startswith("-")]
    if len(args) >= 2 and os.path.isdir(args[0]):
        print(json.dumps(verify_commit(args[0], args[1], force=forced), indent=2, default=str))
    elif len(args) >= 2:
        rows = db.select("projects", {"select": "repo_path", "name": "eq.%s" % args[0]}) or [{}]
        print(json.dumps(verify_commit(rows[0].get("repo_path") or "", args[1], force=forced),
                         indent=2, default=str))
    elif args:
        run(project=args[0])
    else:
        run()
