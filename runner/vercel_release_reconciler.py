#!/usr/bin/env python3
"""
vercel_release_reconciler.py — make `releases` describe what is actually deployed.

WHY THIS EXISTS
---------------
The `releases` table is written in exactly one place: by the orchestrator, when the
orchestrator itself cuts a deploy with the Vercel CLI. Every other route to
production — a push to main picked up by Vercel's GitHub integration, a promotion
from the dashboard, a rollback — lands in production and is never recorded.

What that looks like in the data, measured 2026-08-23:

    smarter   70 releases, deploy_status=failed, since 2026-07-15
              0 successes in five weeks
    Vercel    production deployments READY throughout, the newest 90 minutes old,
              serving apparently.cc

So the ledger said smarter had shipped nothing since mid-July while the site was
live and being updated daily. canonical_proof_ledger asks `_live_release_for()`
for a release naming a task's artifact commit; for smarter there were none to
find, and every MERGED task stopped at LEVEL_MERGED with "no release names this
artifact commit as its head". The projection was correct. Its evidence was absent.

THE OTHER HALF: THE URL
-----------------------
Every row the orchestrator DID write stores `dep["url"]` — the
`*.vercel.app` deployment URL. The `web` project has

    ssoProtection: { enabled: true, deploymentType: "all_except_custom_domains" }

so every one of those URLs answers 302 to a Vercel SSO login for any caller
without a session, including the fleet's own journey runner. Verification against
the URL the release row carries could not have succeeded at any point.

Custom domains are exempt from that protection by the same setting. So the URL a
release records must be the project's public production domain — apparently.cc,
not smarter-bij5tbxvp-kalepasch1s-projects.vercel.app. This module resolves it,
and says so explicitly when only an SSO-gated URL is available, rather than
storing one that looks fine and cannot be probed.

WHAT IT DOES NOT DO
-------------------
It never marks anything verified, and it never invents a release. It records
deployments Vercel reports as READY on the production target, keyed by the commit
sha Vercel attributes to them. Promotion still requires a passing journey receipt.

Env: VERCEL_TOKEN (required), VERCEL_TEAM_ID (team-scoped projects). Fail-soft
without either — an unreconciled ledger is wrong; a crashed runner is worse.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERCEL_API = "https://api.vercel.com"

#: Vercel serves these from its own SSO-protected namespace when a project has
#: deployment protection on. A journey cannot probe one anonymously.
SSO_GATED_SUFFIXES = (".vercel.app",)

#: How far back to look. A reconciler that walks all history re-reads thousands of
#: dead deployments on every run to learn nothing.
DEFAULT_LOOKBACK = int(os.environ.get("ORCH_RECONCILE_DEPLOY_LIMIT", "40"))

LIVE_STATES = {"READY"}
#: `target` is "production" for a production deploy and null for a preview. A
#: preview that happens to be READY is not a release.
PRODUCTION_TARGET = "production"


class VercelAuthError(RuntimeError):
    """The token is missing, expired, or lacks access to the team."""


# --------------------------------------------------------------- URL selection

def is_sso_gated(host):
    host = str(host or "").strip().lower()
    return any(host.endswith(suffix) for suffix in SSO_GATED_SUFFIXES)


def public_production_url(domains, deployment_url=""):
    """The URL a journey can actually reach, and why.

    Returns (url, gated, reason). `gated` is True when the only thing available is
    an SSO-protected deployment URL, which callers must not treat as verifiable.

    `domains` is Vercel's project-domains payload: dicts with `name`, optionally
    `verified` and `redirect`. A domain that redirects elsewhere is a forwarding
    entry, not the place the app is served.
    """
    candidates = []
    for entry in domains or []:
        if not isinstance(entry, dict):
            entry = {"name": str(entry)}
        name = str(entry.get("name") or "").strip().lower()
        if not name or is_sso_gated(name):
            continue
        if entry.get("redirect"):
            continue
        # `verified` absent means the API did not report on it; only an explicit
        # False is a reason to skip. Treating unknown as unverified would drop
        # every domain on payloads that omit the field.
        if entry.get("verified") is False:
            continue
        candidates.append(name)

    if candidates:
        # Apex before www before anything longer: the apex is what a person types
        # and what the site canonicalises to.
        best = sorted(candidates, key=lambda n: (n.startswith("www."), n.count("."), len(n), n))[0]
        return f"https://{best}", False, ""

    host = str(deployment_url or "").strip().lower().replace("https://", "").rstrip("/")
    if not host:
        return "", True, "no domain and no deployment url"
    return (f"https://{host}", True,
            "only an SSO-gated *.vercel.app URL is available; a journey cannot "
            "probe it anonymously (deployment protection excludes custom domains only)")


def deployment_id(deployment):
    """Vercel's id for a deployment.

    /v6/deployments returns it as `uid`; /v13 and the dashboard call it `id`. The
    first real run wrote "deployment None" into every reconciled note because only
    `id` was read.
    """
    d = deployment or {}
    return str(d.get("uid") or d.get("id") or "")


def deployment_sha(deployment):
    meta = (deployment or {}).get("meta") or {}
    return str(meta.get("githubCommitSha") or "").strip().lower()


def is_live_production(deployment):
    d = deployment or {}
    state = str(d.get("state") or d.get("readyState") or "").strip().upper()
    return state in LIVE_STATES and str(d.get("target") or "") == PRODUCTION_TARGET


# ------------------------------------------------------------------ Vercel API

def _vget(path, token=None):
    token = token or os.environ.get("VERCEL_TOKEN", "").strip()
    if not token:
        raise VercelAuthError("VERCEL_TOKEN unset")
    req = urllib.request.Request(VERCEL_API + path,
                                 headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise VercelAuthError(f"Vercel API auth failed ({e.code})")
        raise


def _team_qs(extra=None):
    qs = dict(extra or {})
    team = os.environ.get("VERCEL_TEAM_ID", "").strip()
    if team:
        qs["teamId"] = team
    return qs


def fetch_production_deployments(vercel_project, limit=DEFAULT_LOOKBACK, vget=None):
    vget = vget or _vget
    qs = _team_qs({"app": vercel_project, "target": PRODUCTION_TARGET, "limit": str(limit)})
    data = vget("/v6/deployments?" + urllib.parse.urlencode(qs)) or {}
    return [d for d in (data.get("deployments") or []) if is_live_production(d)]


def fetch_project_domains(vercel_project, vget=None):
    vget = vget or _vget
    qs = _team_qs({"limit": "50"})
    path = f"/v9/projects/{urllib.parse.quote(str(vercel_project))}/domains?"
    data = vget(path + urllib.parse.urlencode(qs)) or {}
    return data.get("domains") or []


# ---------------------------------------------------------------- the reconcile

def missing_releases(deployments, known_shas):
    """Production deployments with no live release row, oldest first.

    `known_shas` is the set of shas already recorded live for this project. Keyed on
    sha rather than deployment id because that is what the ledger joins on, and
    because a redeploy of the same commit is the same release.
    """
    seen, out = set(known_shas or ()), []
    for dep in sorted(deployments or [], key=lambda d: d.get("created") or 0):
        sha = deployment_sha(dep)
        if not sha or sha in seen:
            continue
        seen.add(sha)
        out.append(dep)
    return out


def release_row(project, deployment, url, gated, reason, now_iso=None):
    """The row this deployment would add. Pure — callers decide whether to write it."""
    created = deployment.get("created")
    iso = None
    if created:
        from datetime import datetime, timezone
        iso = datetime.fromtimestamp(float(created) / 1000.0, timezone.utc).isoformat()
    note = (f"reconciled from Vercel: deployment {deployment_id(deployment)} "
            f"state={deployment.get('state')} target=production")
    if gated:
        note += f" — WARNING: {reason}"
    return {
        "project": project,
        "version": deployment_id(deployment),
        "to_sha": deployment_sha(deployment),
        "deploy_status": "success",
        "vercel_url": url.replace("https://", "") or None,
        "host": "vercel-reconciler",
        "created_at": iso or now_iso,
        "deployed_at": iso or now_iso,
        "note": note,
    }


def reconcile_project(project, vercel_project, select_fn, insert_fn, vget=None,
                      limit=DEFAULT_LOOKBACK, now_iso=None, dry_run=False):
    """Add a release row for every live production deployment that has none.

    Returns {"project", "checked", "added", "rows", "gated", "error"}.
    """
    result = {"project": project, "checked": 0, "added": 0, "rows": [],
              "gated": False, "error": None}
    try:
        deployments = fetch_production_deployments(vercel_project, limit=limit, vget=vget)
        domains = fetch_project_domains(vercel_project, vget=vget)
    except VercelAuthError as e:
        result["error"] = str(e)
        return result
    except Exception as e:
        result["error"] = f"vercel query failed: {e}"
        return result

    result["checked"] = len(deployments)
    if not deployments:
        return result

    known = set()
    try:
        for row in select_fn("releases", {"select": "to_sha,deploy_status",
                                          "project": f"eq.{project}"}) or []:
            if str((row or {}).get("deploy_status") or "").lower() == "success":
                sha = str((row or {}).get("to_sha") or "").strip().lower()
                if sha:
                    known.add(sha)
    except Exception as e:
        # Not knowing what is already recorded means every run would duplicate
        # every row. Refuse rather than write.
        result["error"] = f"could not read existing releases: {e}"
        return result

    for dep in missing_releases(deployments, known):
        url, gated, reason = public_production_url(domains, dep.get("url"))
        result["gated"] = result["gated"] or gated
        row = release_row(project, dep, url, gated, reason, now_iso=now_iso)
        result["rows"].append(row)
        if not dry_run:
            insert_fn("releases", row)
        result["added"] += 1
    return result


def run(dry_run=False):
    """Reconcile every project the fleet has a Vercel mapping for."""
    try:
        import db
        import deploy_verify
    except Exception as e:
        print(f"vercel_release_reconciler: unavailable ({e})")
        return []

    if not os.environ.get("VERCEL_TOKEN", "").strip():
        print("vercel_release_reconciler: VERCEL_TOKEN unset; skipping")
        return []

    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()

    health = deploy_verify._deploy_health_map()
    projects = sorted({row.get("app") for row in health.values() if row.get("app")})
    results = []
    for project in projects:
        vercel_project = deploy_verify._vercel_project(project, health=health)
        out = reconcile_project(project, vercel_project, db.select, db.insert,
                                now_iso=now_iso, dry_run=dry_run)
        results.append(out)
        if out["error"]:
            print(f"vercel_release_reconciler: {project}: {out['error']}")
        elif out["added"]:
            flag = " (SSO-gated url)" if out["gated"] else ""
            print(f"vercel_release_reconciler: {project}: +{out['added']} "
                  f"of {out['checked']} production deployments{flag}")
    return results


if __name__ == "__main__":
    print(json.dumps(run(dry_run="--dry-run" in sys.argv), indent=2, default=str))
