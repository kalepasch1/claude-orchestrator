#!/usr/bin/env python3
"""db_remediate.py — turn open db_findings into draft remediation PRs on the project's repo.

WHY. A finding that says "anon holds DELETE on public.gdsa_findings" already carries its fix
in the remediation text, but the fix still waits on a human or a swarm task to type it into a
migration. For the probe classes whose fix is mechanical (revoke grants, cover a foreign key
with an index, add audit columns + trigger), the migration can be generated deterministically
from the finding itself — object_schema/object_name/metrics — so the loop opens a DRAFT PR
with the SQL, the finding fingerprints, and the evidence links, and lets the merge train /
the operator decide. The judgment calls (RLS policies, query rewrites, retention) are
deliberately NOT generated: a wrong policy is worse than an open finding.

SAFETY.
  * Draft PRs only, never direct commits to a base branch; never auto-merge.
  * Hard exclusion: the Apparently engines repo and any project whose source id matches
    the engines Supabase project; swarm steering only ever READS that estate.
  * Identifiers are validated (^A-Za-z_ then word chars) and double-quoted; anything else
    is skipped with a reason, never interpolated raw.
  * Dedupe: one open draft PR per (repo, group). A group whose PR is already open is a
    no-op; the PR body carries the fingerprint list so drift is auditable.
  * Fail-soft everywhere: network off, no token, repo unresolvable -> reason string, no raise.

KNOBS (env):
  ORCH_DB_REMEDIATE           "1" enables live PR creation (default "0": plan-only, prints SQL)
  ORCH_DB_REMEDIATE_MAX_PRS   per-cycle cap across the fleet (default "3")
  ORCH_DB_REMEDIATE_REPOS     optional JSON {project: "owner/repo"} override for repo resolution
  VERCEL_TOKEN                used to resolve project -> GitHub repo via the Vercel link
  GITHUB_APP_* / GITHUB_PAT   via gh_auth for GitHub API + pushes
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402

ENABLED = os.environ.get("ORCH_DB_REMEDIATE", "0") == "1"
MAX_PRS = int(os.environ.get("ORCH_DB_REMEDIATE_MAX_PRS", "3"))
VERCEL_TOKEN = os.environ.get("VERCEL_TOKEN", "")
GITHUB_API = "https://api.github.com"
VERCEL_API = "https://api.vercel.com"

#: The Apparently engines estate is hands-off (hard rule): never open PRs there.
ENGINES_EXCLUSIONS = ("oosolxvlfyifkhjohdzq", "apparently-engines", "apparently.cc", "apparently-ai")

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

SEV_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3}


# ── SQL generation (pure) ─────────────────────────────────────────────────────

def _qi(name):
    """Quoted identifier or None when the name fails the whitelist — never interpolate raw."""
    name = str(name or "")
    return ('"%s"' % name) if _IDENT_RE.match(name) else None


#: Table names that LOOK like deliberate public-write surfaces (public intake/contact forms
#: legitimately write via the anon key). The revoke is still generated — RLS is the correct
#: mechanism — but the reviewer gets an explicit caution rather than a silent breakage risk.
PUBLIC_WRITE_HINT = re.compile(r"intake|contact|signup|subscribe|lead|form|waitlist", re.I)


def _sql_revoke_grants(f):
    """anon_or_public_grants: revoke write-ish privileges from anon and public; SELECT stays
    (RLS decides row visibility once DML is gone)."""
    schema, table = _qi(f.get("object_schema")), _qi(f.get("object_name"))
    if not (schema and table):
        return ""
    privs = ", ".join(p for p in ("insert", "update", "delete", "truncate", "references", "trigger"))
    caveat = ("-- NOTE: %s looks like a deliberate public-write surface (intake/contact form?): "
              "verify the form path still works after revoking anon INSERT.\n"
              % f.get("object_name")) if PUBLIC_WRITE_HINT.search(str(f.get("object_name") or "")) else ""
    return (caveat + f"revoke {privs} on {schema}.{table} from anon;\n"
            f"revoke {privs} on {schema}.{table} from public;")


def _sql_fk_index(f):
    """unindexed_foreign_keys: one covering index on the constrained columns, in key order."""
    schema, table = _qi(f.get("object_schema")), _qi(f.get("object_name"))
    cols = [c for c in ((f.get("metrics") or {}).get("columns") or [])]
    qcols = [_qi(c) for c in cols]
    if not (schema and table) or not cols or not all(qcols):
        return ""  # older findings predate the columns metric — skipped, not guessed
    idx = _qi("idx_dbsteer_%s_%s" % (f.get("object_name", "")[:40], cols[0][:24]))
    if not idx:
        return ""
    return ("create index concurrently if not exists %s on %s.%s (%s);"
            % (idx, schema, table, ", ".join(qcols)))


def _sql_audit_columns(f):
    """missing_audit_columns: add the columns the probe says are absent, idempotently."""
    schema, table = _qi(f.get("object_schema")), _qi(f.get("object_name"))
    missing = [m for m in ((f.get("metrics") or {}).get("missing") or []) if m in ("created_at", "updated_at")]
    if not (schema and table):
        return ""
    if not missing:
        # pre-metrics findings: conservatively only add created_at (created_at iff absent
        # is a no-op when present, and 'if not exists' keeps it idempotent)
        missing = ["created_at"]
    parts = []
    if "created_at" in missing:
        parts.append("alter table %s.%s add column if not exists created_at timestamptz not null default now();"
                     % (schema, table))
    if "updated_at" in missing:
        parts.append("alter table %s.%s add column if not exists updated_at timestamptz;" % (schema, table))
        parts.append(_sql_updated_at_trigger(f))
    return "\n".join(p for p in parts if p)


def _sql_updated_at_trigger(f):
    """updated_at_with(no)trigger: Supabase's moddatetime (extensions schema) maintains it."""
    schema, table = _qi(f.get("object_schema")), _qi(f.get("object_name"))
    if not (schema and table):
        return ""
    trig = _qi("set_updated_at_dbsteer")
    return ("drop trigger if exists %s on %s.%s;\n"
            "create trigger %s before update on %s.%s for each row execute function extensions.moddatetime('updated_at');"
            % (trig, schema, table, trig, schema, table))


#: probe_id -> (group, generator). Groups become one PR each per project.
GENERATORS = {
    "anon_or_public_grants": ("access-grants", _sql_revoke_grants),
    "unindexed_foreign_keys": ("fk-indexes", _sql_fk_index),
    "missing_audit_columns": ("audit-columns", _sql_audit_columns),
    "updated_at_without_trigger": ("audit-columns", _sql_updated_at_trigger),
}

GROUP_TITLES = {
    "access-grants": "db-steering: revoke anon/public write grants flagged by the read-only review",
    "fk-indexes": "db-steering: cover unindexed foreign keys",
    "audit-columns": "db-steering: add missing audit columns and updated_at triggers",
}


def plan_migration(project, findings):
    """[(group, sql, [fingerprints], [skipped-reasons])] — pure, deterministic ordering by
    object name so regenerated migrations diff cleanly."""
    groups = {}
    for f in findings:
        gen = GENERATORS.get(f.get("probe_id"))
        if not gen or f.get("status") != "open":
            continue
        group, fn = gen
        sql = fn(f)
        if not sql:
            groups.setdefault(group, {"sql": [], "fps": [], "skipped": []})["skipped"].append(
                "%s %s.%s (missing metrics to generate safely)" % (
                    f.get("probe_id"), f.get("object_schema"), f.get("object_name")))
            continue
        g = groups.setdefault(group, {"sql": [], "fps": [], "skipped": []})
        g["sql"].append((str(f.get("object_name") or ""), f.get("fingerprint") or "", sql))
        g["fps"].append(f.get("fingerprint"))
    out = []
    for group in sorted(groups):
        g = groups[group]
        if not g["sql"]:
            if g["skipped"]:
                out.append((group, "", [], g["skipped"]))
            continue
        stmts = sorted(g["sql"], key=lambda t: t[0])
        body = "\n\n".join("-- [fp:%s] %s\n%s" % (fp[:12], name, sql) for name, fp, sql in stmts)
        header = ("-- Database Steering auto-remediation (%s) — draft, review before apply.\n"
                  "-- Project: %s · findings: %d · generated read-only-review driven\n\n"
                  "begin;\n\n" % (group, project, len(stmts)))
        out.append((group, header + body + "\n\ncommit;\n", g["fps"], g["skipped"]))
    return out


# ── HTTP (fail-soft, injectable in tests) ─────────────────────────────────────

def _http(method, url, token, body=None, timeout=20):
    req = urllib.request.Request(url, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "claude-orchestrator-db-steering")
    if token:
        req.add_header("Authorization", "Bearer %s" % token)
    data = json.dumps(body).encode() if body is not None else None
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read() or b"{}")
        except Exception:
            detail = {}
        return {"_http_error": e.code, "_message": str(detail.get("message") or "")[:200]}
    except Exception as e:
        return {"_http_error": -1, "_message": "%s: %s" % (type(e).__name__, str(e)[:120])}


def _gh_token():
    try:
        import gh_auth
        return gh_auth.gh_token() or ""
    except Exception as e:
        print("db_remediate: gh token unavailable: %s" % str(e)[:120])
        return ""


def _gh(method, path, body=None):
    return _http(method, GITHUB_API + path, _gh_token(), body)


def repo_for_project(project_row):
    """owner/repo for a fleet project: explicit override map, then the Vercel project link.
    Fail-soft '' when unresolvable."""
    name = str(project_row.get("name") or "")
    try:
        override = json.loads(os.environ.get("ORCH_DB_REMEDIATE_REPOS") or "{}")
        if override.get(name):
            return str(override[name])
    except Exception as e:  # noqa: FAIL_SOFT_ERROR — malformed override map falls through to Vercel-link resolution
        print("db_remediate: ORCH_DB_REMEDIATE_REPOS unreadable (%s); using Vercel link" % str(e)[:80])
    vp = str(project_row.get("vercel_project") or "")
    if vp and VERCEL_TOKEN:
        res = _http("GET", "%s/v9/projects/%s" % (VERCEL_API, vp), VERCEL_TOKEN)
        link = (res or {}).get("link") or {}
        org, repo = str(link.get("org") or ""), str(link.get("repo") or link.get("repoName") or "")
        if repo:
            return "%s/%s" % (org, repo) if org else repo
    return ""


def _is_excluded(project_row, source_ids=()):
    name = str(project_row.get("name") or "").lower()
    repo_path = str(project_row.get("repo_path") or "").lower()
    if any(x in name or x in repo_path for x in ("engines", "apparently.cc")):
        return True
    return any(str(s) in ENGINES_EXCLUSIONS for s in (source_ids or ()))


# ── PR lifecycle ──────────────────────────────────────────────────────────────

def ensure_draft_pr(project, repo, group, sql, fingerprints, base=""):
    """Create (or skip, if one exists) a draft PR carrying one migration file. Returns a
    summary dict; every failure path is a reason string, never an exception."""
    branch = "fix/db-steer-%s" % group
    head = "%s:%s" % (repo.split("/")[0], branch)
    existing = _gh("GET", "/repos/%s/pulls?head=%s&state=open&per_page=5" % (repo, head))
    if isinstance(existing, list) and existing:
        return {"ok": True, "skipped": "open PR exists", "pr": existing[0].get("html_url")}
    repo_meta = _gh("GET", "/repos/%s" % repo)
    if not isinstance(repo_meta, dict) or repo_meta.get("_http_error"):
        return {"ok": False, "reason": "repo lookup failed: %s" % repo_meta.get("_message", "?")}
    base = base or str(repo_meta.get("default_branch") or "main")
    base_ref = _gh("GET", "/repos/%s/git/ref/heads/%s" % (repo, base))
    sha = str((base_ref or {}).get("object", {}).get("sha") or "")
    if not sha:
        return {"ok": False, "reason": "base ref unreadable: %s" % (base_ref or {}).get("_message", "?")}
    made = _gh("POST", "/repos/%s/git/refs" % repo,
               {"ref": "refs/heads/%s" % branch, "sha": sha})
    if (made or {}).get("_http_error") and "already exists" not in str(made.get("_message", "")):
        return {"ok": False, "reason": "branch create failed: %s" % made.get("_message")}
    path = "supabase/migrations/%s_db_steering_%s.sql" % (time.strftime("%Y%m%d%H%M%S"), group.replace("-", "_"))
    put = _gh("PUT", "/repos/%s/contents/%s" % (repo, path), {
        "message": "db-steering: %s remediation (%d findings)" % (group, len(fingerprints)),
        "content": base64.b64encode(sql.encode()).decode(), "branch": branch,
        "committer": {"name": "kalepasch1", "email": "kalepasch@gmail.com"}})
    if (put or {}).get("_http_error"):
        return {"ok": False, "reason": "file commit failed: %s" % put.get("_message")}
    body = ("\n".join(["## What this does",
                       "Generated by the read-only Database Steering review from open findings. "
                       "Each statement is preceded by its finding fingerprint (`fp:…`), joinable to "
                       "`db_findings.fingerprint` in the control plane.",
                       "", "### Findings covered", ""] +
                      ["- [fp:%s]" % str(fp)[:12] for fp in fingerprints] +
                      ["", "**Draft on purpose** — review the SQL, run it against a staging branch, "
                          "then mark ready. The orchestrator never auto-merges remediation."]))
    pr = _gh("POST", "/repos/%s/pulls" % repo, {
        "title": GROUP_TITLES.get(group, "db-steering: %s" % group), "head": branch,
        "base": base, "body": body, "draft": True})
    if (pr or {}).get("_http_error"):
        return {"ok": False, "reason": "PR create failed: %s" % pr.get("_message")}
    return {"ok": True, "pr": pr.get("html_url"), "branch": branch, "path": path}


# ── repo-local brief (steering without the fleet) ─────────────────────────────

BRIEF_BRANCH = "steering/briefs"
BRIEF_PATH = ".claude/db-steering-brief.md"
BRIEF_RE = re.compile(r"<!--\s*db-steering:([0-9a-f]{8,24})\s*-->")


def push_brief(project_row, brief_text, findings_hash):
    """Commit `.claude/db-steering-brief.md` to the `steering/briefs` branch of the project's
    own repo when the findings hash changed. A Claude Code session opened DIRECTLY in the
    project (no fleet prompt assembly, no orchestrator) picks the brief up from the repo
    itself; the fleet never enters that loop. Fail-soft summary dict."""
    name = str(project_row.get("name") or "")
    text = str(brief_text or "").strip()
    if not text or not findings_hash:
        return {"project": name, "ok": True, "skipped": "no brief"}
    if _is_excluded(project_row):
        return {"project": name, "ok": True, "skipped": "excluded"}
    repo = repo_for_project(project_row)
    if not repo:
        return {"project": name, "ok": True, "skipped": "no repo"}
    marker = "<!-- db-steering:%s -->" % str(findings_hash)
    cur = _gh("GET", "/repos/%s/contents/%s?ref=%s" % (repo, BRIEF_PATH, BRIEF_BRANCH))
    cur_sha = ""
    if isinstance(cur, dict) and not cur.get("_http_error"):
        cur_sha = str(cur.get("sha") or "")
        try:
            existing = base64.b64decode(str(cur.get("content") or "").replace("\n", "")).decode("utf-8", "replace")
            if marker in existing:
                return {"project": name, "ok": True, "skipped": "unchanged"}
        except Exception as e:  # noqa: FAIL_SOFT_ERROR — an unreadable blob is simply rewritten below
            print("db_remediate: brief blob for %s unreadable (%s); rewriting" % (name, str(e)[:80]))
    repo_meta = _gh("GET", "/repos/%s" % repo)
    base = str(((repo_meta or {}).get("default_branch")) or "main")
    if _gh("GET", "/repos/%s/git/ref/heads/%s" % (repo, BRIEF_BRANCH)).get("_http_error"):
        base_sha = str((_gh("GET", "/repos/%s/git/ref/heads/%s" % (repo, base)) or {}).get("object", {}).get("sha") or "")
        if not base_sha:
            return {"project": name, "ok": False, "reason": "base ref unreadable"}
        made = _gh("POST", "/repos/%s/git/refs" % repo, {"ref": "refs/heads/%s" % BRIEF_BRANCH, "sha": base_sha})
        if (made or {}).get("_http_error") and "already exists" not in str(made.get("_message", "")):
            return {"project": name, "ok": False, "reason": "branch create failed: %s" % made.get("_message")}
    body = text + "\n\n%s\n" % marker
    put_body = {"message": "db-steering: refresh brief (hash %s)" % str(findings_hash)[:12],
                "content": base64.b64encode(body.encode()).decode(), "branch": BRIEF_BRANCH,
                "committer": {"name": "kalepasch1", "email": "kalepasch@gmail.com"}}
    if cur_sha:
        put_body["sha"] = cur_sha
    put = _gh("PUT", "/repos/%s/contents/%s" % (repo, BRIEF_PATH), put_body)
    if (put or {}).get("_http_error"):
        return {"project": name, "ok": False, "reason": "brief commit failed: %s" % put.get("_message")}
    return {"project": name, "ok": True, "repo": repo, "branch": BRIEF_BRANCH, "path": BRIEF_PATH}


# ── fleet wiring ──────────────────────────────────────────────────────────────

def remediate_project(project_row, *, budget):
    """Plan (and, when enabled, open) draft PRs for one project's mechanical findings."""
    if budget <= 0:
        return {"project": project_row.get("name"), "ok": False, "reason": "budget exhausted"}
    name = str(project_row.get("name") or "")
    if not name or project_row.get("superseded_by") or _is_excluded(project_row):
        return {"project": name, "ok": False, "reason": "excluded"}
    rows = db.select_all("db_findings", {
        "select": "probe_id,severity,status,fingerprint,object_schema,object_name,metrics,title",
        "project": "eq.%s" % name, "status": "eq.open",
        "probe_id": "in.(%s)" % ",".join(sorted(GENERATORS))}, order="id.asc") or []
    findings = sorted(rows, key=lambda r: (-SEV_RANK.get(r.get("severity"), 0),
                                           str(r.get("object_name") or "")))
    plans = plan_migration(name, findings)
    plans = [p for p in plans if p[1] and p[2]]
    if not plans:
        return {"project": name, "ok": True, "reason": "nothing mechanical open"}
    if not ENABLED:
        return {"project": name, "ok": True, "planned": [
            {"group": g, "findings": len(fps), "skipped": skipped} for g, _s, fps, skipped in plans],
            "reason": "plan-only (ORCH_DB_REMEDIATE=0)"}
    repo = repo_for_project(project_row)
    if not repo:
        return {"project": name, "ok": False, "reason": "no GitHub repo resolvable (vercel link / override)"}
    results, spent = [], 0
    for group, sql, fps, skipped in plans:
        if spent >= budget:
            results.append({"group": group, "ok": False, "reason": "budget exhausted"})
            continue
        spent += 1
        res = ensure_draft_pr(name, repo, group, sql, fps)
        res["group"] = group
        if skipped:
            res["skipped"] = skipped
        results.append(res)
    return {"project": name, "ok": all(r["ok"] for r in results), "pr_results": results}


def run_cycle(projects=None, *, budget=None):
    """One remediation pass over the fleet (or the projects the steering cycle just scanned).
    Returns a summary; never raises."""
    budget = MAX_PRS if budget is None else budget
    out = {"enabled": ENABLED, "budget": budget, "results": []}
    try:
        if projects is None:
            projects = db.select("projects", {"select": "name,repo_path,vercel_project,superseded_by"}) or []
        for p in projects:
            if budget <= 0:
                break
            try:
                res = remediate_project(p, budget=budget)
            except Exception as e:
                res = {"project": p.get("name"), "ok": False,
                       "reason": "%s: %s" % (type(e).__name__, str(e)[:120])}
            out["results"].append(res)
            made = sum(1 for r in (res.get("pr_results") or []) if r.get("ok") and not r.get("skipped"))
            budget -= min(made, budget)
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, str(e)[:120])
    return out


if __name__ == "__main__":
    print(json.dumps(run_cycle(), indent=2, default=str))
