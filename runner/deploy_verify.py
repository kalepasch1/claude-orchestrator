#!/usr/bin/env python3
"""
deploy_verify.py - confirms Vercel production deploys and rolls back bad ones.

After release_train pushes a production branch, this polls the matching Vercel
deployment for that release commit:
  * READY -> mark release deployed and record the commit as last-good.
  * ERROR/CANCELED/stuck-unconfirmed -> queue a deploy-fix task, restore git to
    last-good when possible, and file an approvals card.

Vercel keeps the previous successful deployment serving until a new one is
READY, so rollback mainly restores git to the known-good state for the next
release attempt.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

VBASE = "https://api.vercel.com"
TERMINAL_GOOD = {"READY"}
TERMINAL_BAD = {"ERROR", "CANCELED", "FAILED"}


def _ignored_build_cancel(deployment):
    """Vercel uses CANCELED for a successful Ignored Build Step decision."""
    deployment = deployment or {}
    state = deployment.get("state") or deployment.get("readyState")
    message = " ".join(str(deployment.get(key) or "")
                       for key in ("errorCode", "errorMessage"))
    return state == "CANCELED" and "ignored build step" in message.lower()


#: Phrases Vercel returns on a CANCELED deployment that NEVER STARTED A BUILD because the
#: project config disabled deploys for that ref. web/vercel.json here is exactly that
#: shape — {"*": false, "master": true} — so every release verified against a non-master
#: ref comes back CANCELED with no build events at all.
_NO_BUILD_CANCEL_PHRASES = (
    "deployments are disabled",
    "deployment is disabled",
    "deploymentenabled",
    "git deployments are disabled",
    "deployments for this branch",
    "branch is not enabled",
    "skipped",
)


def _no_build_cancel(deployment):
    """True when CANCELED means "no build was ever attempted", not "the build failed".

    WHY THIS MATTERS. TERMINAL_BAD treats every CANCELED as a failed deploy, which does
    two harmful things at once: it queues a deployfix ("fix the smallest build/deploy
    issue") whose Vercel log tail is EMPTY — because no build ran, so there are no events
    — and it force-rolls-back the production branch to last_good over a deploy that never
    touched production. Two such tasks (deployfix-beethoven-07152141 and -07160115, both
    "Release status: CANCELED", both with an empty log tail, neither with a single touched
    file) were retried to their budget cap against a build that was never broken.

    This is the same shape as _ignored_build_cancel, which already exempts the Ignored
    Build Step decision. A config-disabled ref is the other way Vercel reports "I chose
    not to build this", and it deserves the same answer.

    Deliberately narrow: it requires state CANCELED **and** an explicit provider message.
    A CANCELED deployment with a real error message still counts as bad, because an
    operator aborting a genuinely broken build should not be silently written off.
    """
    deployment = deployment or {}
    state = deployment.get("state") or deployment.get("readyState")
    if state != "CANCELED":
        return False
    raw = " ".join(str(deployment.get(key) or "")
                   for key in ("errorCode", "errorMessage", "errorLink")).lower()
    # errorCode arrives SCREAMING_SNAKE (DEPLOYMENTS_ARE_DISABLED) while errorMessage is
    # prose, so normalise every non-alphanumeric run to a single space and match once.
    message = re.sub(r"[^a-z0-9]+", " ", raw)
    return any(phrase in message for phrase in _NO_BUILD_CANCEL_PHRASES)


def _cancel_without_build(deployment):
    """Either flavour of "the provider declined to build this", as one predicate."""
    return _ignored_build_cancel(deployment) or _no_build_cancel(deployment)


class VercelAuthError(RuntimeError):
    pass


def _vget(path):
    tok = os.environ.get("VERCEL_TOKEN", "").strip()
    if not tok:
        return None
    req = urllib.request.Request(VBASE + path, headers={"Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise VercelAuthError(f"Vercel API auth failed ({e.code})")
        raise


def _deploy_health_map():
    out = {}
    try:
        for row in db.select("deploy_health", {"select": "app,vercel_project,git_branch"}) or []:
            if row.get("app"):
                out[row["app"]] = row
    except Exception:
        pass
    return out


def _vercel_project(project, project_row=None, health=None):
    """Resolve Vercel project slug/id from canonical deploy_health first."""
    project_row = project_row or {}
    health = health if health is not None else _deploy_health_map()
    h = health.get(project) or {}
    return h.get("vercel_project") or project_row.get("vercel_project") or project


def _latest_deploy(vercel_project, sha=None):
    """Return matching production deployment, preferring the release commit SHA."""
    try:
        team = os.environ.get("VERCEL_TEAM_ID", "")
        qs = {"app": vercel_project, "target": "production", "limit": "12"}
        if team:
            qs["teamId"] = team
        data = _vget("/v6/deployments?" + urllib.parse.urlencode(qs)) or {}
        deps = data.get("deployments") or []
        if not deps:
            return None
        if sha:
            short = str(sha)[:12]
            for dep in deps:
                meta = dep.get("meta") or {}
                dsha = meta.get("githubCommitSha") or meta.get("githubCommitRef")
                if dsha and (str(dsha) == str(sha) or str(dsha).startswith(short)):
                    return dep
        return deps[0]
    except VercelAuthError as e:
        return {"_auth_error": str(e), "state": "AUTH_ERROR"}
    except Exception as e:
        print(f"deploy_verify: vercel query failed ({e})")
        return None


def _latest_deploy_state(vercel_project, sha=None):
    """Compatibility helper: return (state, url)."""
    dep = _latest_deploy(vercel_project, sha=sha)
    if not dep:
        return None, None
    return dep.get("state") or dep.get("readyState"), dep.get("url")


def _deployment_events(deployment_id):
    if not deployment_id:
        return ""
    try:
        team = os.environ.get("VERCEL_TEAM_ID", "")
        path = f"/v2/deployments/{deployment_id}/events" + (f"?teamId={team}" if team else "")
        data = _vget(path) or {}
        events = data.get("events") or data.get("logs") or []
        lines = []
        for event in events[-80:]:
            payload = event.get("payload") if isinstance(event, dict) else None
            msg = payload.get("text") if isinstance(payload, dict) else None
            msg = msg or event.get("text") or event.get("message") or event.get("type")
            if msg:
                lines.append(str(msg))
        return "\n".join(lines)[-3000:]
    except Exception:
        return ""


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def _rollback(project, repo, prod, last_good):
    branch = _git(repo, "branch", "-f", prod, last_good)
    if branch.returncode != 0:
        print(f"deploy_verify: rollback branch update FAILED for {project}: {branch.stderr.strip()[:240]}")
        return False
    push_rollback = os.environ.get(
        "ORCH_PUSH_ON_ROLLBACK",
        os.environ.get("ORCH_PUSH_ON_RELEASE", "true"),
    ).lower() in ("1", "true", "yes", "on")
    if push_rollback:
        pushed = _git(repo, "push", "--force-with-lease", "origin", prod)
        if pushed.returncode != 0:
            print(f"deploy_verify: rollback push FAILED for {project}: {pushed.stderr.strip()[:240]}")
            return False
    print(f"deploy_verify: ROLLED BACK {project} {prod} -> {last_good[:8]}")
    return True


#: A deployfix prompt says "fix the smallest build/deploy issue and make the production
#: build pass". Without a build log there is nothing to fix from, so the task is
#: unactionable by construction — and CANCELED is the state that reliably has no log,
#: because a canceled deployment never emitted build events.
_LOGLESS_STATES = {"CANCELED"}


def _unactionable_deploy_fix(state, log_tail):
    """Reason this deployfix would be unactionable, or "" when it is worth queueing.

    THE EVIDENCE. deployfix-beethoven-07152141 and -07160115 both carry "Release status:
    CANCELED" and an EMPTY "# Vercel/build log tail:", and neither ever produced a single
    touched file; 07152141 was retried until "reached budget cap (4)". An executor cannot
    fix a build from an empty log, so each retry re-derived the same nothing. Filing a
    task with no evidence in it is worse than filing none: it consumes a claim slot and
    looks like queue progress.

    Narrow on purpose. Only a LOGLESS state with a genuinely empty tail is refused. An
    ERROR with no log still queues, because ERROR means a build ran and failed and the
    missing log is a fetch problem worth a human look — not proof there is nothing wrong.
    """
    if str(state or "").upper() not in _LOGLESS_STATES:
        return ""
    if (log_tail or "").strip():
        return ""
    return ("state=%s with an empty build log: a canceled deployment emits no build "
            "events, so a build-fix task would have nothing to act on" % (state or "?"))


def _queue_deploy_fix(project_row, release, state, vercel_project, log_tail=""):
    try:
        if not project_row.get("id"):
            return
        unactionable = _unactionable_deploy_fix(state, log_tail)
        if unactionable:
            print("deploy_verify: NOT queueing deployfix for %s — %s"
                  % (release.get("project"), unactionable))
            return
        existing = db.select("tasks", {"select": "slug", "project_id": f"eq.{project_row.get('id')}",
                                       "state": "in.(QUEUED,RUNNING,RETRY,BLOCKED)"}) or []
        if any(str(e.get("slug") or "").startswith("deployfix-") for e in existing):
            return
        slug = f"deployfix-{release['project']}-{datetime.datetime.utcnow().strftime('%m%d%H%M')}"
        prompt = (
            "The Vercel production deploy for this app failed or could not be confirmed. "
            "Fix the smallest build/deploy issue and make the production build pass. "
            "Do not add product features. Preserve existing behavior.\n\n"
            f"Vercel project: {vercel_project}\n"
            f"Release status: {state or 'unconfirmed'}\n"
            f"Release commit: {release.get('to_sha') or ''}\n\n"
            "# Vercel/build log tail:\n" + (log_tail or release.get("note") or "")[-3000:]
        )
        try:
            import pipeline_contract
            prompt = pipeline_contract.wrap_prompt(prompt, project=release["project"], kind="bugfix",
                                                   source="vercel-deploy-verify", slug=slug, material=False)
        except Exception:
            pass
        db.insert("tasks", {"project_id": project_row.get("id"), "slug": slug, "prompt": prompt,
                  "base_branch": project_row.get("default_base") or project_row.get("prod_branch") or "main",
                  "kind": "bugfix", "state": "QUEUED", "deps": [], "material": False,
                  "note": "auto-queued by deploy_verify Vercel failure"})
    except Exception as e:
        print(f"deploy_verify: queue deploy-fix failed for {release.get('project')}: {e}")


def _file_auth_issue(project, vercel_project, error):
    try:
        title = "Vercel auth blocked deploy verification"
        ex = db.select("approvals", {"select": "id", "project": f"eq.{project}",
                                    "status": "eq.pending", "title": f"eq.{title}"}) or []
        if ex:
            return
        db.insert("approvals", {"project": project, "kind": "operator", "title": title,
                  "why": f"Vercel project `{vercel_project}` cannot be queried: {error}. "
                         "The current VERCEL_TOKEN is rejected before project lookup.",
                  "value": "Set a valid Vercel token, and VERCEL_TEAM_ID if these projects live under a team, so deploy verification and rollback can operate.",
                  "risk": "Deploy status is unknown; no rollback was attempted because this is an auth failure, not a confirmed bad deploy.",
                  "command": "Set VERCEL_TOKEN in runner/.env; optionally set VERCEL_TEAM_ID, then rerun deploy_watch/deploy_verify."})
    except Exception:
        pass


def _age_minutes(row):
    """Age of a release row in minutes, or None when `created_at` is unusable.

    This returned 0 on any parse failure, which reads as "brand new". The only
    consumer is the stuck-deploy check `state is None and age_min > stuck_min`, so a
    release whose created_at was NULL or malformed could never exceed the threshold —
    it was permanently pinned at zero minutes old and a genuinely wedged deploy was
    never detected, silently, for as long as the row existed. Unknown is not zero:
    None makes the caller decide, and the caller now says so out loud instead of
    quietly treating the release as healthy.
    """
    raw = row.get("created_at") if hasattr(row, "get") else None
    if raw in (None, ""):
        return None
    try:
        created = datetime.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None
    if created.tzinfo is None:                      # naive timestamps are UTC here
        created = created.replace(tzinfo=datetime.timezone.utc)
    return (datetime.datetime.now(datetime.timezone.utc) - created).total_seconds() / 60


def _release_journey(release, url):
    """Run the release's declared production journey AFTER the deploy is READY.

    Returns the receipt (always — a release that declares nothing gets an explicit
    MISSING receipt so the absence is recorded, not inferred). Fail-soft on import.
    """
    try:
        import production_journey
    except Exception as e:
        print(f"deploy_verify: production_journey unavailable ({e}); "
              f"release {release.get('id')} has no journey receipt")
        return None
    sha = str(release.get("to_sha") or "")
    base = url if not url or str(url).startswith("http") else "https://" + str(url)
    return production_journey.verify_task(
        {"slug": f"release-{release.get('project')}-{sha[:12]}",
         "journey": release.get("journey")},
        base_url=base or "", sha=sha, environment="production")


def _attribute_deploy_to_outcomes(project, journey_receipt=None):
    """Mark integrated outcomes for this project as deployed after a confirmed prod deploy.

    JOURNEY GATE: a READY deployment returning HTTP 200 is release health, not delivery.
    Outcomes are attributed only when the release's production journey passed. A missing
    or failed journey leaves them un-attributed rather than silently certified.

    Fail-soft: if the columns don't exist yet (migration pending) the update
    will raise and we silently skip — the columns being NULL is the pre-migration state.
    """
    try:
        import production_journey
        ok, why = production_journey.gate(
            journey_receipt, required=(journey_receipt or {}).get("required", True))
    except Exception:
        ok, why = True, "journey gate unavailable"
    if not ok:
        print(f"deploy_verify: NOT attributing outcomes for {project} — {why}")
        return
    try:
        rows = db.select("outcomes", {
            "select": "slug",
            "project": f"eq.{project}",
            "integrated": "eq.true",
            "deployed": "is.false",
            "limit": "500",
        }) or []
        for r in rows:
            slug = r.get("slug")
            if not slug:
                continue
            try:
                db.update("outcomes", {"slug": slug, "project": project},
                          {"deployed": True, "deploy_status": "success"})
            except Exception:
                pass
    except Exception:
        pass


def run():
    pend = db.select("releases", {"select": "*", "deploy_status": "in.(building,pending,verification_blocked)",
                                  "order": "created_at.desc", "limit": "20"}) or []
    projs = {p["name"]: p for p in (db.select("projects", {"select": "*"}) or [])}
    health = _deploy_health_map()
    stuck_min = int(os.environ.get("DEPLOY_STUCK_MIN", "15"))
    for release in pend:
        project = release["project"]
        p = projs.get(project, {})
        vproj = _vercel_project(project, p, health)
        dep = _latest_deploy(vproj, sha=release.get("to_sha"))
        if (dep or {}).get("_auth_error"):
            _file_auth_issue(project, vproj, dep["_auth_error"])
            db.update("releases", {"id": release["id"]},
                      {"deploy_status": "verification_blocked",
                       "note": f"vercel auth blocked verification; no rollback attempted: {dep['_auth_error']}"})
            continue
        state = (dep or {}).get("state") or (dep or {}).get("readyState")
        url = (dep or {}).get("url")

        ignored_build = _cancel_without_build(dep)
        if state in TERMINAL_GOOD or ignored_build:
            note = (("provider declined to build: deploys disabled for this ref"
                     if _no_build_cancel(dep)
                     else "provider ignored build: release contains no deployable-root changes")
                    if ignored_build else release.get("note") or "")
            # POST-DEPLOY JOURNEY: the deployment being READY is when the journey becomes
            # meaningful, so it runs here, against the live release SHA. A failed required
            # journey is a bad release — it is rolled back exactly like a failed build.
            receipt = None if ignored_build else _release_journey(release, url)
            try:
                import production_journey
                roll = production_journey.should_roll_back(receipt)
            except Exception:
                roll = False
            if roll:
                repo = p.get("repo_path") or ""
                last_good = p.get("last_good_sha") or release.get("from_sha")
                rolled = bool(repo and last_good and os.path.isdir(repo)
                              and _rollback(project, repo, p.get("prod_branch") or "main", last_good))
                failed = (receipt.get("failed_assertions") or [{}])[0]
                db.update("releases", {"id": release["id"]},
                          {"deploy_status": "rolled_back" if rolled else "journey_failed",
                           "vercel_url": url,
                           "note": (f"production journey FAILED at {failed.get('step')}/"
                                    f"{failed.get('assertion')} (receipt {receipt.get('id')}); "
                                    f"{'rolled back' if rolled else 'rollback unavailable'}")[:500]})
                _queue_deploy_fix(p, release, "journey_failed", vproj,
                                  log_tail=json.dumps(receipt.get("failed_assertions") or [],
                                                      indent=2)[:3000])
                print(f"deploy_verify: {project} deploy READY but production journey FAILED "
                      f"(receipt {receipt.get('id')})")
                continue
            journey_note = ""
            if receipt:
                journey_note = f" | journey={receipt.get('verdict')} receipt={receipt.get('id')}"
            db.update("releases", {"id": release["id"]},
                      {"deploy_status": "success", "vercel_url": url,
                       "deployed_at": "now()", "note": (note + journey_note)[:500]})
            db.update("projects", {"name": project}, {"last_good_sha": release["to_sha"],
                      "vercel_project": vproj})
            _attribute_deploy_to_outcomes(project, journey_receipt=receipt)
            print(f"deploy_verify: {project} deploy OK ({url}){journey_note}")
            continue

        age_min = _age_minutes(release)
        if state is None and age_min is None:
            # Unknown state AND unknown age: this used to look like a 0-minute-old
            # release and fall through as healthy forever. Surface it instead — an
            # unreadable created_at is a data bug, not a passing deploy. No rollback:
            # we have not confirmed a bad deploy, only that we cannot judge this one.
            print(f"deploy_verify: {project} release {release.get('id')} has an unusable "
                  f"created_at ({release.get('created_at')!r}); cannot age-out a stuck "
                  f"deploy — skipping (not treating as healthy)")
            continue
        if state in TERMINAL_BAD or (state is None and age_min > stuck_min):
            log_tail = _deployment_events((dep or {}).get("uid") or (dep or {}).get("id"))
            _queue_deploy_fix(p, release, state, vproj, log_tail=log_tail)
            repo = p.get("repo_path") or ""
            last_good = p.get("last_good_sha") or release.get("from_sha")
            rollback_ok = False
            if repo and last_good and os.path.isdir(repo):
                rollback_ok = _rollback(project, repo, p.get("prod_branch") or "main", last_good)
            rollback_status = "rolled_back" if rollback_ok else "verification_blocked"
            rollback_note = "auto-rollback" if rollback_ok else "auto-rollback failed"
            db.update("releases", {"id": release["id"]}, {"deploy_status": rollback_status,
                      "note": f"{rollback_note}: state={state or 'unconfirmed'} age={age_min:.0f}m -> {(last_good or '')[:8]}"})
            db.insert("approvals", {"project": project, "kind": "self",
                      "title": f"Prod deploy {'reverted' if rollback_ok else 'rollback blocked'}: {project}",
                      "why": f"Deploy {state or 'unconfirmed'} after {age_min:.0f}m; "
                             f"{'restored last-good' if rollback_ok else 'the last-good push did not complete'}.",
                      "value": "Failing change is out of prod; a deploy-fix task was queued." if rollback_ok
                               else "Release state is explicit; operator remediation is required.",
                      "risk": "Low — Vercel keeps the previous good deployment serving." if rollback_ok
                              else "Elevated — the repository branch may still point at the rejected candidate.",
                      "command": ""})
    return len(pend)


if __name__ == "__main__":
    print("checked releases:", run())
