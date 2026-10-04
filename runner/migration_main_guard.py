#!/usr/bin/env python3
"""migration_main_guard.py — the orchestrator only applies migrations that are already on main.

OWNER DECISION (Kale, 2026-10-03): "the orchestrator only applies migrations that are already
on main."

WHY. On 2026-10-03 sessions applied Supabase migrations to production (smarter
olaxnyrzoptjcntrrjgn, apparently-law cwmeqqtvmjbapjsefbfq) straight from unmerged feature
branches. The ledger recorded versions with no file on the repo's main, which broke
check:migration-ledger and the production build ~8 times, one version (20261030020000) was
used twice, and table-dropping migrations ran without the owner's OK. Every one of those is
a property of WHERE the SQL came from, so this module checks that before anything runs.

THE RULE. Before a migration is applied to a production database:

  1. the target database maps to a repo + production branch (runner/deployment_bindings.json:
     `supabase_project_ref` -> `github_repo` + `branch`); an unmapped target is refused;
  2. the target repo's production branch is fetched fresh and the file
     `<dir>/<version>_<name>.sql` exists there (default dir `supabase/migrations`);
  3. its bytes on `origin/<branch>` are identical to the bytes about to run;
  4. no other file on `origin/<branch>` uses the same Supabase version (14-digit timestamp);
  5. the production ledger (`supabase_migrations.schema_migrations`) does not already carry
     the version under a different name, nor the name under a different version;
  6. a destructive migration (DROP TABLE/SCHEMA/VIEW/TYPE/COLUMN, TRUNCATE, DELETE FROM)
     additionally needs the owner's explicit approval of that version — main-only is IN
     ADDITION to owner approval, never instead of it.

Any failure is a refusal that names the version, the branch the migration came from and the
production branch it is missing from, and is recorded the way the fleet records other gate
refusals: a reason dict back to the caller, a printed line, and a `fleet_log` warn row
(source `migration_main_guard`), fail-soft on the log write only.

The guard FAILS CLOSED: if main cannot be fetched or the ledger cannot be read, the migration
is refused. A false refusal costs one manual re-run; a false acceptance is what happened on
2026-10-03.

OWNER APPROVAL for destructive versions comes from `--owner-approved <version>` on the CLI
entry points or `MIGRATION_OWNER_APPROVED_VERSIONS` (comma-separated) in the operator's own
shell. It is deliberately NOT `ORCH_`-prefixed: ORCH_ keys are fleet-pushable, and an approval
that an agent can push fleet-wide is not the owner's approval.

ENTRY POINTS
  check_migration(...)   one migration (version, name, bytes) against one target
  check_file(...)        a migration file on disk (any git checkout of the target repo)
  check_checkout(...)    a whole checkout before `supabase db push` / `migration up`
  record_refusal(...)    log + fleet_log a refusal
  python3 runner/migration_main_guard.py claude-hook
                         Claude Code PreToolUse hook: refuses Supabase MCP `apply_migration`
                         and DDL through `execute_sql` against a mapped production project.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys

_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

BINDINGS_PATH = os.path.join(_DIR, "deployment_bindings.json")
DEFAULT_MIGRATIONS_DIR = "supabase/migrations"
SOURCE = "migration_main_guard"
OWNER_APPROVAL_ENV = "MIGRATION_OWNER_APPROVED_VERSIONS"
GIT_TIMEOUT_S = 90

#: `<version>_<name>.sql` — version is digits (14 for the Supabase CLI, short-form 0001 in
#: older trees), name is everything up to the extension.
_FILENAME = re.compile(r"^(\d+)_(.+)\.sql$")
#: A Supabase CLI ledger version: the primary key of supabase_migrations.schema_migrations.
_LEDGER_VERSION = re.compile(r"^\d{14}$")

#: Data-destroying statements. Policy/function/trigger/index drops are routine in idempotent
#: migrations (`drop policy if exists ...; create policy ...`) and destroy no rows, so they are
#: not on this list.
_DESTRUCTIVE = re.compile(
    r"\b(?:drop\s+(?:table|schema|view|materialized\s+view|type|database|sequence)\b"
    r"|alter\s+table\b[^;]*?\bdrop\s+column\b"
    r"|truncate\b"
    r"|delete\s+from\b)",
    re.I | re.S)

#: DDL shapes for the execute_sql hook. Plain DML (the cowork executors claim queue rows with
#: UPDATE through execute_sql on the control plane) is not a migration and is not refused.
_DDL = re.compile(
    r"\b(?:create|alter|drop|truncate|comment\s+on|grant|revoke|rename)\b"
    r"|\binsert\s+into\s+supabase_migrations\b|\bdelete\s+from\s+supabase_migrations\b",
    re.I)


class MainUnavailable(RuntimeError):
    """The production branch could not be fetched or read — the guard refuses."""


# ── target resolution ──────────────────────────────────────────────────────────────────

def load_bindings(path=None):
    try:
        with open(path or BINDINGS_PATH) as fh:
            return json.load(fh)
    except Exception as e:  # noqa: FAIL_SOFT_ERROR — no bindings means no target, which refuses
        print("%s: deployment bindings unreadable (%s)" % (SOURCE, str(e)[:120]))
        return {}


def resolve_target(ref=None, app=None, repo_path=None, bindings=None):
    """{app, github_repo, branch, repo_path, supabase_project_ref} for a production database,
    by Supabase ref, app name (aliases honoured) or local checkout path. None when unmapped —
    and an unmapped target is refused, never guessed."""
    b = bindings if bindings is not None else load_bindings()
    targets = [t for t in (b.get("targets") or []) if isinstance(t, dict)]
    if app:
        app = (b.get("aliases") or {}).get(app, app)
    for t in targets:
        if ref and str(t.get("supabase_project_ref") or "") == str(ref):
            return _target(t)
    for t in targets:
        if app and str(t.get("app") or "") == str(app):
            return _target(t)
    if repo_path:
        want = os.path.realpath(repo_path)
        for t in targets:
            if t.get("repo_path") and os.path.realpath(str(t["repo_path"])) == want:
                return _target(t)
    return None


def _target(t):
    return {"app": str(t.get("app") or ""), "github_repo": str(t.get("github_repo") or ""),
            "branch": str(t.get("branch") or "main"), "repo_path": str(t.get("repo_path") or ""),
            "supabase_project_ref": str(t.get("supabase_project_ref") or "")}


def production_refs(bindings=None):
    b = bindings if bindings is not None else load_bindings()
    return {str(t.get("supabase_project_ref")) for t in (b.get("targets") or [])
            if isinstance(t, dict) and t.get("supabase_project_ref")}


def repo_slug(url):
    """owner/repo from any GitHub remote URL form (ssh, https, token-in-URL). '' otherwise."""
    m = re.search(r"github\.com[:/]+([^/\s]+/[^/\s]+?)(?:\.git)?/?$", str(url or "").strip())
    return m.group(1).lower() if m else ""


def parse_filename(filename):
    m = _FILENAME.match(os.path.basename(str(filename or "")))
    return (m.group(1), m.group(2)) if m else (None, None)


def destructive_statements(sql):
    text = sql.decode("utf-8", "replace") if isinstance(sql, (bytes, bytearray)) else str(sql or "")
    text = re.sub(r"--[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"'(?:[^']|'')*'", "''", text)
    return sorted({re.sub(r"\s+", " ", m.group(0)).strip().lower()[:40] for m in _DESTRUCTIVE.finditer(text)})


def owner_approved_versions(extra=()):
    env = os.environ.get(OWNER_APPROVAL_ENV, "")
    return {v.strip() for v in env.split(",") if v.strip()} | {str(v).strip() for v in (extra or ()) if str(v).strip()}


def _sha(b):
    return hashlib.sha256(b).hexdigest()[:12]


def _bytes(sql):
    if isinstance(sql, (bytes, bytearray)):
        return bytes(sql)
    return str(sql if sql is not None else "").encode("utf-8")


# ── reading the production branch ──────────────────────────────────────────────────────

def _git(repo_dir, *args, check=True, binary=False):
    p = subprocess.run(["git", "-C", repo_dir] + list(args), capture_output=True,
                       timeout=GIT_TIMEOUT_S, text=not binary)
    if check and p.returncode != 0:
        err = p.stderr.decode("utf-8", "replace") if binary else p.stderr
        raise MainUnavailable("git %s failed: %s" % (" ".join(args[:2]), (err or "").strip()[:200]))
    return p


class GitMain:
    """The production branch as seen through a local clone of the target repo. `ensure()`
    fetches it fresh (remote-tracking ref only — the working tree is never touched) and
    checks the clone's remote really is the target repo."""

    def __init__(self, repo_dir, branch, expected_repo="", remote="origin", fetch=True):
        self.repo_dir, self.branch, self.remote = repo_dir, branch, remote
        self.expected_repo, self.fetch = (expected_repo or "").lower(), fetch
        self.ref = "%s/%s" % (remote, branch)
        self._ready = False

    def ensure(self):  # noqa: FAIL_SOFT_ERROR — an unreadable main must refuse, not pass
        if self._ready:
            return
        if not (self.repo_dir and os.path.isdir(self.repo_dir)):
            raise MainUnavailable("no local checkout at %r" % self.repo_dir)
        url = _git(self.repo_dir, "remote", "get-url", self.remote).stdout.strip()
        if self.expected_repo and repo_slug(url) and repo_slug(url) != self.expected_repo:
            raise MainUnavailable("checkout %s points at %s, not %s"
                                  % (self.repo_dir, repo_slug(url), self.expected_repo))
        if self.fetch:
            _git(self.repo_dir, "fetch", "--quiet", "--no-tags", self.remote,
                 "+refs/heads/%s:refs/remotes/%s" % (self.branch, self.ref))
        _git(self.repo_dir, "rev-parse", "--verify", "--quiet", self.ref + "^{commit}")
        self._ready = True

    def read(self, relpath):
        p = _git(self.repo_dir, "cat-file", "blob", "%s:%s" % (self.ref, relpath), check=False, binary=True)
        return p.stdout if p.returncode == 0 else None

    def list_dir(self, reldir):
        p = _git(self.repo_dir, "ls-tree", "--name-only", self.ref, reldir.rstrip("/") + "/", check=False)
        return [os.path.basename(x) for x in (p.stdout or "").splitlines() if x.strip()]

    def contains(self, sha):
        p = _git(self.repo_dir, "merge-base", "--is-ancestor", sha, self.ref, check=False)
        return p.returncode == 0


class GitHubMain:
    """Fallback when no local clone exists: the GitHub contents API at the production
    branch. Same interface as GitMain."""

    def __init__(self, github_repo, branch, gh=None):
        self.repo, self.branch, self.ref = github_repo, branch, "origin/%s" % branch
        self._gh = gh

    def _call(self, path):
        gh = self._gh
        if gh is None:
            import db_remediate
            gh = db_remediate._gh
        return gh("GET", "/repos/%s/contents/%s?ref=%s" % (self.repo, path, self.branch))

    def ensure(self):  # noqa: FAIL_SOFT_ERROR — an unreadable main must refuse, not pass
        res = self._call(DEFAULT_MIGRATIONS_DIR)
        if not isinstance(res, list):
            raise MainUnavailable("GitHub contents API unavailable for %s@%s: %s"
                                  % (self.repo, self.branch, str((res or {}).get("_http_error") if isinstance(res, dict) else res)[:80]))

    def read(self, relpath):
        res = self._call(relpath)
        if isinstance(res, dict) and res.get("content") is not None and not res.get("_http_error"):
            return base64.b64decode(res["content"])
        return None

    def list_dir(self, reldir):
        res = self._call(reldir.rstrip("/"))
        return [str(r.get("name")) for r in res] if isinstance(res, list) else []

    def contains(self, sha):
        return False


def main_for(target, repo_dir=None, fetch=True):
    """The production-branch reader for a target: a local clone when one exists, else the
    GitHub API."""
    repo_dir = repo_dir or target.get("repo_path")
    if repo_dir and os.path.isdir(repo_dir):
        return GitMain(repo_dir, target["branch"], expected_repo=target.get("github_repo"), fetch=fetch)
    return GitHubMain(target.get("github_repo"), target["branch"])


# ── the ledger ─────────────────────────────────────────────────────────────────────────

LEDGER_SQL = "select version, name from supabase_migrations.schema_migrations order by version"


def read_ledger(ref, query=None):
    """[{version, name}] from production, read-only. None when unreadable (the guard then
    refuses); [] when the database has no Supabase ledger at all."""
    try:
        if query is None:
            import db_adapters
            rows = db_adapters.query({"provider": "supabase", "ref": ref}, LEDGER_SQL)
        else:
            rows = query(LEDGER_SQL)
        if isinstance(rows, dict):
            rows = rows.get("result") or []
        return [{"version": str(r.get("version") or ""), "name": str(r.get("name") or "")}
                for r in (rows or []) if isinstance(r, dict)]
    except Exception as e:  # noqa: FAIL_SOFT_ERROR — None is the refusal signal to the caller
        msg = str(e)
        if "does not exist" in msg and "schema_migrations" in msg:
            return []
        print("%s: ledger for %s unreadable: %s" % (SOURCE, ref, msg[:200]))
        return None


# ── decisions ──────────────────────────────────────────────────────────────────────────

def _refuse(base, code, reason):
    out = dict(base)
    out.update({"ok": False, "code": code, "reason": reason})
    return out


def check_migration(target, version, name, sql, *, main=None, ledger=None, source_branch="",
                    owner_approved=(), migrations_dir=DEFAULT_MIGRATIONS_DIR):
    """Decide whether one migration may be applied to `target`'s production database.

    `sql` is exactly what is about to run. `ledger` is the production ledger rows
    ([{version, name}]); None means it could not be read, which refuses. Returns
    {ok, code, reason, version, name, branch, repo, source_branch, file, ...}; never raises.
    """
    filename = "%s_%s.sql" % (version, name)
    relpath = "%s/%s" % (migrations_dir.rstrip("/"), filename)
    src = source_branch or "an unmerged branch"
    base = {"ok": False, "version": str(version), "name": str(name), "file": relpath,
            "source_branch": source_branch or "", "repo": (target or {}).get("github_repo", ""),
            "branch": (target or {}).get("branch", ""), "app": (target or {}).get("app", "")}
    if not target or not target.get("github_repo"):
        return _refuse(base, "no_target",
                       "refused %s (from %s): the target database has no production repo/branch "
                       "mapping in runner/deployment_bindings.json" % (filename, src))
    prod = "origin/%s of %s" % (target["branch"], target["github_repo"])
    try:
        main = main or main_for(target)
        main.ensure()
        on_main = main.read(relpath)
    except Exception as e:
        return _refuse(base, "main_unreadable",
                       "refused %s (from %s): could not read %s to verify it (%s)"
                       % (filename, src, prod, str(e)[:160]))
    if on_main is None:
        return _refuse(base, "not_on_main",
                       "refused migration %s (from %s): %s does not exist on %s. Merge it to "
                       "consolidation/main, promote to %s, then apply."
                       % (version, src, relpath, prod, target["branch"]))
    data = _bytes(sql)
    base.update({"sha_main": _sha(on_main), "sha_run": _sha(data)})
    if on_main != data:
        return _refuse(base, "content_drift",
                       "refused migration %s (from %s): the SQL about to run (sha %s) differs from "
                       "%s on %s (sha %s). Only the bytes on %s may be applied."
                       % (version, src, _sha(data), relpath, prod, _sha(on_main), target["branch"]))
    if _LEDGER_VERSION.match(str(version)):
        try:
            same = sorted(f for f in main.list_dir(migrations_dir)
                          if f.startswith("%s_" % version) and f.endswith(".sql"))
        except Exception:
            same = [filename]
        if len(same) > 1:
            return _refuse(base, "duplicate_version_on_main",
                           "refused migration %s: version %s is used by %d files on %s (%s); the "
                           "ledger keys on version, so only one can ever be recorded"
                           % (filename, version, len(same), prod, ", ".join(same[:4])))
    if ledger is None:
        return _refuse(base, "ledger_unreadable",
                       "refused migration %s (from %s): the production ledger could not be read, so "
                       "a version collision cannot be ruled out" % (version, src))
    already = False
    for row in ledger:
        v, n = str(row.get("version") or ""), str(row.get("name") or "")
        if v == str(version):
            if n and n != str(name):
                return _refuse(base, "ledger_collision",
                               "refused migration %s (from %s): version %s is already in the production "
                               "ledger as %r — one version, two migrations" % (filename, src, version, n))
            already = True
        elif n and n == str(name):
            return _refuse(base, "ledger_name_collision",
                           "refused migration %s (from %s): %r is already in the production ledger under "
                           "version %s — applying it again under %s would double-apply it"
                           % (filename, src, name, v, version))
    destructive = destructive_statements(data)
    base["destructive"] = destructive
    if destructive and not already and str(version) not in owner_approved_versions(owner_approved):
        return _refuse(base, "destructive_unapproved",
                       "refused migration %s: it contains %s and the owner has not approved version "
                       "%s (--owner-approved %s or %s). Being on %s is required IN ADDITION to the "
                       "owner's OK, not instead of it."
                       % (filename, ", ".join(destructive), version, version, OWNER_APPROVAL_ENV, target["branch"]))
    out = dict(base)
    out.update({"ok": True, "code": "already_applied" if already else "ok", "already_applied": already,
                "reason": "%s is on %s byte-identical%s" % (filename, prod,
                                                            " and already in the ledger" if already else "")})
    return out


def _checkout_info(path):
    """(toplevel, relpath, branch) of a file inside a git checkout; Nones outside one."""
    d = os.path.dirname(os.path.abspath(path))
    p = subprocess.run(["git", "-C", d, "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                       timeout=GIT_TIMEOUT_S)
    if p.returncode != 0:
        return None, None, ""
    top = p.stdout.strip()
    rel = os.path.relpath(os.path.realpath(os.path.abspath(path)), os.path.realpath(top))
    b = subprocess.run(["git", "-C", top, "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True,
                       text=True, timeout=GIT_TIMEOUT_S)
    return top, rel.replace(os.sep, "/"), (b.stdout.strip() if b.returncode == 0 else "")


def check_file(path, target, *, ledger=None, owner_approved=(), main=None):
    """check_migration for a file on disk. The production branch is read through the git
    checkout the file lives in (whose remote must be the target repo) — so a file in a
    feature-branch worktree is compared against main, never against its own branch. On ok
    the result carries `sql`: the verified bytes, which is what the caller must run."""
    version, name = parse_filename(path)
    if not version:
        return {"ok": False, "code": "bad_filename", "file": str(path), "version": "", "name": "",
                "reason": "refused %s: not a <version>_<name>.sql migration file" % os.path.basename(str(path))}
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as e:
        return {"ok": False, "code": "unreadable", "file": str(path), "version": version, "name": name,
                "reason": "refused %s: %s" % (os.path.basename(str(path)), str(e)[:120])}
    top, rel, branch = _checkout_info(path)
    mig_dir = os.path.dirname(rel) if rel else DEFAULT_MIGRATIONS_DIR
    if main is None and target and top:
        main = GitMain(top, target["branch"], expected_repo=target.get("github_repo"))
    d = check_migration(target, version, name, data, main=main, ledger=ledger, source_branch=branch,
                        owner_approved=owner_approved, migrations_dir=mig_dir or DEFAULT_MIGRATIONS_DIR)
    if d.get("ok"):
        d["sql"] = data
    return d


def check_checkout(repo_dir, target, *, ledger=None, owner_approved=(), main=None,
                   migrations_dir=DEFAULT_MIGRATIONS_DIR):
    """Gate for commands that apply a whole checkout's migrations (`supabase db push`,
    `supabase migration up`, `prisma migrate deploy`, `npm run migrate`).

    Refuses unless: the checkout is clean, its HEAD is contained in the production branch,
    and every migration file in it passes check_migration. Returns {ok, reason, refusals[],
    pending[]}; never raises."""
    out = {"ok": False, "repo_dir": repo_dir, "refusals": [], "pending": [],
           "branch": (target or {}).get("branch", ""), "repo": (target or {}).get("github_repo", "")}
    if not target:
        out.update(code="no_target", reason="refused: %s has no production repo/branch mapping in "
                                            "runner/deployment_bindings.json" % repo_dir)
        return out
    try:
        main = main or GitMain(repo_dir, target["branch"], expected_repo=target.get("github_repo"))
        main.ensure()
        head_branch = _git(repo_dir, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        head = _git(repo_dir, "rev-parse", "HEAD").stdout.strip()
        dirty = _git(repo_dir, "status", "--porcelain", "--untracked-files=all").stdout.strip()
    except Exception as e:
        out.update(code="main_unreadable", reason="refused: could not verify %s against origin/%s (%s)"
                   % (repo_dir, target["branch"], str(e)[:160]))
        return out
    out["source_branch"] = head_branch
    if dirty:
        out.update(code="dirty_checkout",
                   reason="refused: %s has uncommitted changes; migrations are applied only from a clean "
                          "checkout of origin/%s" % (repo_dir, target["branch"]))
        return out
    if not main.contains(head):
        out.update(code="not_on_main",
                   reason="refused: %s is on %s (%s), which is not contained in origin/%s of %s. Merge to "
                          "consolidation/main, promote to %s, then apply from a checkout of origin/%s."
                          % (repo_dir, head_branch, head[:10], target["branch"], target["github_repo"],
                             target["branch"], target["branch"]))
        return out
    mdir = os.path.join(repo_dir, migrations_dir)
    files = sorted(f for f in (os.listdir(mdir) if os.path.isdir(mdir) else []) if f.endswith(".sql"))
    for f in files:
        version, name = parse_filename(f)
        if not version:
            continue
        with open(os.path.join(mdir, f), "rb") as fh:
            data = fh.read()
        d = check_migration(target, version, name, data, main=main, ledger=ledger, source_branch=head_branch,
                            owner_approved=owner_approved, migrations_dir=migrations_dir)
        if not d["ok"]:
            out["refusals"].append(d)
        elif not d.get("already_applied"):
            out["pending"].append(f)
    if out["refusals"]:
        out.update(code=out["refusals"][0]["code"],
                   reason="; ".join(r["reason"] for r in out["refusals"][:3])[:1500])
        return out
    out.update(ok=True, code="ok", reason="%d pending migration(s), all on origin/%s byte-identical"
               % (len(out["pending"]), target["branch"]))
    return out


def record_refusal(decision, via=""):
    """Record a refusal the way the fleet's gates do: printed reason + fleet_log warn row.
    Fail-soft on the log write only — the refusal itself already happened."""
    reason = str(decision.get("reason") or "refused")
    print("%s%s: %s" % (SOURCE, (" (%s)" % via) if via else "", reason))
    try:
        import db
        meta = {k: v for k, v in decision.items() if k not in ("sql", "refusals")}
        meta["via"] = via
        db.insert("fleet_log", {"level": "warn", "source": SOURCE,
                                "message": ("refused migration: %s" % reason)[:900],
                                "meta": json.dumps(meta, default=str)[:4000]})
    except Exception as e:  # noqa: FAIL_SOFT_ERROR — an unwritable log must not turn a refusal into an apply
        print("%s: fleet_log write failed (%s)" % (SOURCE, str(e)[:80]))
    return decision


# ── Claude Code PreToolUse hook ────────────────────────────────────────────────────────

def hook_decision(payload, bindings=None):
    """(allow: bool, message) for a PreToolUse payload. Supabase MCP `apply_migration` on a
    mapped production project is always refused: it applies SQL from wherever the session
    is standing and records a FRESH version that has no file on main — the exact failure of
    2026-10-03. `execute_sql` carrying DDL on a production project is refused for the same
    reason. Everything else (reads, DML, non-production/preview projects) passes."""
    tool = str((payload or {}).get("tool_name") or "")
    args = (payload or {}).get("tool_input") or {}
    ref = str(args.get("project_id") or args.get("project_ref") or "")
    if not ref or ref not in production_refs(bindings):
        return True, ""
    target = resolve_target(ref=ref, bindings=bindings) or {}
    where = "%s (%s, production branch origin/%s of %s)" % (
        target.get("app") or ref, ref, target.get("branch") or "main", target.get("github_repo") or "?")
    how = ("The orchestrator only applies migrations that are already on main: merge the migration "
           "to consolidation/main, promote it to %s, then apply it from a clean checkout of origin/%s "
           "(`supabase db push`, gated by runner/migration_main_guard.py)." % (
               target.get("branch") or "main", target.get("branch") or "main"))
    if tool.endswith("apply_migration"):
        return False, "refused: apply_migration against production %s. %s" % (where, how)
    if tool.endswith("execute_sql"):
        q = str(args.get("query") or "")
        stripped = re.sub(r"'(?:[^']|'')*'", "''", re.sub(r"--[^\n]*", "", q))
        if _DDL.search(stripped):
            return False, "refused: DDL through execute_sql against production %s. %s" % (where, how)
    return True, ""


def _claude_hook(stdin=None):
    try:
        payload = json.loads((stdin or sys.stdin).read() or "{}")
    except Exception:
        return 0  # not a payload we understand; never wedge the session
    allow, msg = hook_decision(payload)
    if allow:
        return 0
    record_refusal({"ok": False, "code": "mcp_refused", "reason": msg,
                    "tool": payload.get("tool_name")}, via="claude-hook")
    sys.stderr.write(msg + "\n")
    return 2  # PreToolUse: exit 2 blocks the tool call and shows stderr to the agent


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "claude-hook":
        sys.exit(_claude_hook())
    print(__doc__)
