#!/usr/bin/env python3
"""
canonical_proof_ledger.py — ONE projection of "is this actually shipped?".

Before this module the answer was assembled independently in at least four places
(task_artifacts readers, release_manifest gates, deployment_terminal's promotion scan,
and the snapshot API the proof UI renders). Each had its own idea of what counted, so
the same task could read MERGED-and-done in the UI, unverified in the promotion scan,
and absent from the manifest. This module is the single source those consumers project
from.

THE RULES, which are the whole point:

1. Every PASS links to its receipt. A verdict with no `receipt` is a bug, not a pass —
   `project_task()` will not emit PASS without one, and `audit()` asserts it.
2. Unknown evidence displays UNKNOWN or PENDING. It NEVER displays PASS. The failure
   this replaces was silence being rendered as success.
3. MERGED proves integration reachability and nothing else. It does not prove the code
   ran, deployed, or worked. `MERGED` maps to level MERGED, verdict PENDING.
4. DEPLOYED_AND_VERIFIED requires BOTH an exact live release SHA that contains the
   task's artifact commit AND a task-defined production journey receipt. Either alone
   is PENDING.
5. Every ledger read is paginated. PostgREST caps an unbounded response at 1000 rows and
   returns them without complaint, so an un-paginated read silently reports "no evidence"
   for everything past row 1000. See `paginate()`.

Fail-soft throughout, per CLAUDE.md: a read that cannot be performed yields UNKNOWN, it
does not raise and it does not yield PASS.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# Verdicts and levels
# ---------------------------------------------------------------------------

#: A claim we can stand behind, with a receipt attached.
PASS = "PASS"
#: Evidence is expected and has not arrived. Work is in flight, not proven.
PENDING = "PENDING"
#: We cannot see the evidence at all — read failed, row absent, table missing.
UNKNOWN = "UNKNOWN"
#: Evidence exists and contradicts the claim (e.g. a release that failed to deploy).
FAIL = "FAIL"

VERDICTS = (PASS, PENDING, UNKNOWN, FAIL)

#: Ordered weakest -> strongest. Ordering matters: `audit()` checks monotonicity.
LEVEL_NO_EVIDENCE = "NO_EVIDENCE"
LEVEL_ARTIFACT = "ARTIFACT"
LEVEL_MERGED = "MERGED"
LEVEL_RELEASED = "RELEASED"
LEVEL_DEPLOYED_AND_VERIFIED = "DEPLOYED_AND_VERIFIED"

LEVELS = (
    LEVEL_NO_EVIDENCE,
    LEVEL_ARTIFACT,
    LEVEL_MERGED,
    LEVEL_RELEASED,
    LEVEL_DEPLOYED_AND_VERIFIED,
)

#: Release deploy_status values that mean the release is actually live.
LIVE_RELEASE_STATES = {"success", "deployed", "ready", "deployed_and_verified"}
#: Release deploy_status values that positively disprove liveness.
DEAD_RELEASE_STATES = {"error", "failed", "canceled", "cancelled", "blocked"}

#: PostgREST's implicit response cap. Reads that ignore it silently truncate.
POSTGREST_IMPLICIT_LIMIT = 1000
PAGE_SIZE = int(os.environ.get("ORCH_PROOF_LEDGER_PAGE_SIZE", "1000") or 1000)
#: Hard ceiling so a pathological table cannot spin the projection forever.
MAX_ROWS = int(os.environ.get("ORCH_PROOF_LEDGER_MAX_ROWS", "200000") or 200000)

#: A release older than this is stale: it may be live, but it cannot certify a task
#: whose artifact landed after it was cut.
STALE_RELEASE_NOTE = "release predates the artifact it would certify"


def level_rank(level):
    """Position of `level` in LEVELS; -1 if unrecognised. Never raises."""
    try:
        return LEVELS.index(level)
    except (ValueError, TypeError):
        return -1


# ---------------------------------------------------------------------------
# Paginated reads
# ---------------------------------------------------------------------------

def paginate_checked(select_fn, table, params=None, page_size=PAGE_SIZE, max_rows=MAX_ROWS,
                     order="id.asc"):
    """paginate(), but returns (rows, ok) so callers can tell empty from unreadable.

    This distinction is load-bearing and was worth a second function: a table that read
    cleanly and holds nothing means "we checked, there is no evidence"; a table that
    could not be read means "we do not know". Collapsing them is how an outage starts
    rendering as an absence of work.
    """
    query = dict(params or {})
    query.setdefault("select", "*")
    if order:
        query.setdefault("order", order)
    query.pop("limit", None)
    query.pop("offset", None)

    try:
        page_size = max(1, min(int(page_size), POSTGREST_IMPLICIT_LIMIT))
    except (TypeError, ValueError):
        page_size = POSTGREST_IMPLICIT_LIMIT
    try:
        cap = int(max_rows)
    except (TypeError, ValueError):
        cap = MAX_ROWS
    if cap <= 0:
        return [], True

    rows, offset = [], 0
    while True:
        want = min(page_size, cap - len(rows))
        if want <= 0:
            break
        try:
            page = select_fn(table, dict(query, limit=str(want), offset=str(offset))) or []
        except Exception as exc:
            # Fail-soft: a partial read is reported as what it is. `ok=False` makes the
            # caller turn this into UNKNOWN, never into PASS.
            print(f"[canonical_proof_ledger] paginate({table}) failed at offset "
                  f"{offset} ({exc}); returning {len(rows)} rows read so far", flush=True)
            return rows, False
        rows.extend(page)
        if len(page) < want:
            break
        offset += want
    return rows, True


def paginate(select_fn, table, params=None, page_size=PAGE_SIZE, max_rows=MAX_ROWS,
             order="id.asc"):
    """Read every matching row, in pages. Never raises; returns a list.

    `select_fn` is injected rather than imported so the projection is testable without a
    database — the regression fixtures drive it with a stub.

    Offset paging over an unordered relation may repeat or skip rows between pages, so an
    `order` is always sent. Callers that genuinely have no ordering column pass order=None
    and accept the risk explicitly.

    The reason this exists rather than a bare select(): PostgREST answers an unbounded
    request with its first 1000 rows and a 200, so evidence at row 1001 reads as "no
    evidence" — indistinguishable from a task that was never worked on. That is precisely
    the shape of silence this ledger refuses to render as a pass.
    """
    rows, _ok = paginate_checked(select_fn, table, params, page_size, max_rows, order)
    return rows


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------

def receipt(kind, ref, detail=""):
    """Build a receipt. A verdict of PASS is only legal when one of these is attached.

    `ref` is the thing an auditor can go look at: a commit sha, a release id, a URL.
    A receipt with a blank ref is not a receipt — `project_task()` treats it as absent,
    which downgrades the verdict rather than passing on an empty promise.
    """
    ref = (str(ref) if ref is not None else "").strip()
    if not ref:
        return None
    return {"kind": str(kind), "ref": ref, "detail": str(detail or "")}


def _sha(value):
    """Normalise a commit sha for comparison. Never raises."""
    return (str(value) if value is not None else "").strip().lower()


def _sha_matches(left, right):
    """True when two shas name the same commit, allowing an abbreviated form.

    Abbreviation is accepted in one direction only and only at >= 7 characters, which is
    git's own minimum for an unambiguous short sha. Below that a prefix match is noise.
    """
    left, right = _sha(left), _sha(right)
    if not left or not right:
        return False
    if left == right:
        return True
    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    return len(shorter) >= 7 and longer.startswith(shorter)


# ---------------------------------------------------------------------------
# Evidence gathering
# ---------------------------------------------------------------------------

def gather_evidence(select_fn, project=None, slugs=None):
    """Read every table this projection depends on, paginated, into one bundle.

    Returns {"artifacts": {slug: row}, "releases": [row], "journeys": {sha: [row]},
             "read_errors": [table]}.

    A table that cannot be read lands in `read_errors` and its evidence is treated as
    UNKNOWN — not as absent, and certainly not as passing. The distinction is the entire
    difference between "we checked and there is nothing" and "we could not check".
    """
    evidence = {"artifacts": {}, "releases": [], "journeys": {}, "read_errors": []}

    artifact_params = {"select": "slug,branch,commit_sha,touched_files,test_log,captured_at"}
    if slugs:
        wanted = [s for s in slugs if s]
        if wanted:
            artifact_params["slug"] = "in.(" + ",".join(f'"{s}"' for s in wanted) + ")"
    artifacts, ok = paginate_checked(select_fn, "task_artifacts", artifact_params,
                                     order="slug.asc")
    if not ok:
        evidence["read_errors"].append("task_artifacts")
    for row in artifacts:
        slug = (row or {}).get("slug")
        if slug:
            evidence["artifacts"][slug] = row

    release_params = {"select": "id,project,to_sha,deploy_status,vercel_url,created_at,deployed_at,note"}
    if project:
        release_params["project"] = f"eq.{project}"
    evidence["releases"], ok = paginate_checked(select_fn, "releases", release_params,
                                                order="created_at.asc")
    if not ok:
        evidence["read_errors"].append("releases")

    # shipped_metrics carries the production journey receipts. It is optional: not every
    # deployment has one yet. An unreadable table is an error; an empty one is not.
    journeys, ok = paginate_checked(select_fn, "shipped_metrics",
                                    {"select": "release_sha,journey,ok,url,recorded_at"},
                                    order="recorded_at.asc")
    if not ok:
        evidence["read_errors"].append("shipped_metrics")
    for row in journeys:
        key = _sha((row or {}).get("release_sha"))
        if key:
            evidence["journeys"].setdefault(key, []).append(row)

    return evidence


# ---------------------------------------------------------------------------
# The projection
# ---------------------------------------------------------------------------

def _live_release_for(artifact_sha, releases, artifact_at=None):
    """Find the live release that contains `artifact_sha`, or explain why there is none.

    Returns (release_row_or_None, reason). `reason` is only meaningful when the row is
    None, and names the specific defect: no release, stale release, dead release.
    """
    if not _sha(artifact_sha):
        return None, "task has no artifact commit to look for"

    matching = [r for r in releases if _sha_matches((r or {}).get("to_sha"), artifact_sha)]
    if not matching:
        return None, "no release names this artifact commit as its head"

    for rel in matching:
        status = str((rel or {}).get("deploy_status") or "").strip().lower()
        if status in DEAD_RELEASE_STATES:
            continue
        if status not in LIVE_RELEASE_STATES:
            continue
        # A release cut BEFORE the artifact was captured cannot certify it, even though
        # the shas match — that combination means the sha was back-filled onto an older
        # release row, which is the "stale release" defect this ledger has to catch.
        created = str((rel or {}).get("created_at") or "")
        if artifact_at and created and created < str(artifact_at):
            continue
        return rel, ""

    stale = any(str((r or {}).get("created_at") or "") < str(artifact_at or "")
                for r in matching if artifact_at and r.get("created_at"))
    if stale:
        return None, STALE_RELEASE_NOTE
    dead = [r for r in matching
            if str((r or {}).get("deploy_status") or "").strip().lower() in DEAD_RELEASE_STATES]
    if dead:
        return None, f"release {dead[0].get('id')} did not deploy " \
                     f"(deploy_status={dead[0].get('deploy_status')})"
    return None, "release exists but its deploy_status does not say it is live"


def _journey_receipt(release_sha, journeys, required_journey=None):
    """Production journey receipt for a release sha, or (None, reason).

    `required_journey` is the task-defined journey. When a task names one, a receipt for
    some OTHER journey does not satisfy it — that substitution is how a generic health
    check ends up certifying a feature nobody exercised.
    """
    rows = journeys.get(_sha(release_sha)) or []
    if not rows:
        return None, "no production journey receipt for this release sha"

    candidates = rows
    if required_journey:
        candidates = [r for r in rows if str((r or {}).get("journey") or "") == str(required_journey)]
        if not candidates:
            return None, f"no receipt for the task-defined journey {required_journey!r}"

    # The CURRENT verdict, not the best one ever recorded. Selecting any passing row
    # meant a release that passed at 10:00 and failed the same journey at 11:00 still
    # certified as verified: the newer evidence was simply skipped over. A journey is
    # re-run precisely because production changes, so the latest run is the only one
    # that describes production now.
    #
    # Sorted here rather than trusted from the caller: gather_evidence() reads
    # recorded_at.asc today, and a projection this load-bearing must not depend on a
    # read order declared three functions away.
    latest = max(candidates, key=lambda r: str((r or {}).get("recorded_at") or ""))
    if (latest or {}).get("ok") is not True:
        superseded = sum(1 for r in candidates if (r or {}).get("ok") is True)
        detail = (f" (an earlier receipt passed; {superseded} superseded)" if superseded
                  else "")
        return None, ("the most recent production journey receipt for this release "
                      f"did not pass{detail}")

    row = latest
    return receipt("production_journey", row.get("url") or release_sha,
                   f"journey={row.get('journey')} recorded_at={row.get('recorded_at')}"), ""


def project_task(task, evidence, required_journey=None):
    """Project ONE task into a proof verdict. Never raises.

    Returns:
        {"slug", "state", "level", "verdict", "receipt", "reasons": [str]}

    `verdict` is never PASS without `receipt`. That is enforced here, not merely
    documented: the PASS branch is only reachable with a receipt in hand, and `audit()`
    re-checks it over a whole ledger.
    """
    try:
        task = task if isinstance(task, dict) else {}
        slug = task.get("slug") or task.get("id") or ""
        state = str(task.get("state") or "").strip()
        reasons = []

        artifact = (evidence.get("artifacts") or {}).get(slug)
        artifact_sha = _sha((artifact or {}).get("commit_sha") or task.get("artifact_commit"))

        # --- No artifact at all -------------------------------------------------
        if not artifact_sha:
            if "task_artifacts" in (evidence.get("read_errors") or []):
                reasons.append("task_artifacts could not be read; evidence is unknown, not absent")
                verdict = UNKNOWN
            else:
                reasons.append("no artifact commit recorded for this task")
                verdict = UNKNOWN if state in ("MERGED", "DEPLOYED_AND_VERIFIED") else PENDING
            # A task claiming MERGED with no artifact is the phantom-merge defect. It is
            # reported at NO_EVIDENCE regardless of what the state column says, because
            # the state column is the claim, not the proof.
            if state == "MERGED":
                reasons.append("state says MERGED but there is no artifact — phantom merge")
            return {"slug": slug, "state": state, "level": LEVEL_NO_EVIDENCE,
                    "verdict": verdict, "receipt": None, "reasons": reasons}

        artifact_receipt = receipt("artifact_commit", artifact_sha,
                                   f"branch={(artifact or {}).get('branch') or task.get('artifact_branch') or ''}")

        # --- Artifact exists, not merged ---------------------------------------
        if state != "MERGED" and state != "DEPLOYED_AND_VERIFIED":
            reasons.append(f"artifact exists; task state is {state or 'unset'}, not merged")
            return {"slug": slug, "state": state, "level": LEVEL_ARTIFACT,
                    "verdict": PENDING, "receipt": artifact_receipt, "reasons": reasons}

        # --- MERGED: integration reachability ONLY ------------------------------
        # This is rule 3. MERGED is a real, receipted fact about the repository, so the
        # verdict at level MERGED is a PASS *of the MERGED claim* — but the level stops
        # here. It says nothing about production, and nothing downstream may read it as
        # though it did.
        release, why = _live_release_for(artifact_sha, evidence.get("releases") or [],
                                         (artifact or {}).get("captured_at"))
        if release is None:
            reasons.append("MERGED proves integration reachability only")
            reasons.append(why)
            if "releases" in (evidence.get("read_errors") or []):
                reasons.append("releases could not be read; deployment evidence is unknown")
                verdict = UNKNOWN
            else:
                verdict = PENDING
            return {"slug": slug, "state": state, "level": LEVEL_MERGED,
                    "verdict": verdict, "receipt": artifact_receipt, "reasons": reasons}

        release_receipt = receipt("release", release.get("id"),
                                  f"to_sha={release.get('to_sha')} status={release.get('deploy_status')} "
                                  f"url={release.get('vercel_url') or ''}")

        # --- RELEASED: live release with the exact sha -------------------------
        journey, why = _journey_receipt(release.get("to_sha"), evidence.get("journeys") or {},
                                        required_journey)
        if journey is None:
            reasons.append("live release contains the artifact commit")
            reasons.append(why)
            return {"slug": slug, "state": state, "level": LEVEL_RELEASED,
                    "verdict": PENDING, "receipt": release_receipt, "reasons": reasons}

        # --- DEPLOYED_AND_VERIFIED: both halves present ------------------------
        reasons.append("exact live release sha plus a passing production journey receipt")
        return {"slug": slug, "state": state, "level": LEVEL_DEPLOYED_AND_VERIFIED,
                "verdict": PASS, "receipt": journey,
                "reasons": reasons}
    except Exception as exc:
        # Fail-soft, and deliberately UNKNOWN rather than PENDING: a crash in the
        # projection means we do not know, and "we do not know" must never look like
        # progress.
        return {"slug": (task or {}).get("slug", ""), "state": "", "level": LEVEL_NO_EVIDENCE,
                "verdict": UNKNOWN, "receipt": None,
                "reasons": [f"projection failed: {exc}"]}


def build_ledger(select_fn, project=None, tasks=None, required_journeys=None):
    """Project a set of tasks. Returns {"project", "entries", "summary", "read_errors"}.

    `tasks` may be omitted, in which case the task rows are read (paginated) for the
    project. `required_journeys` maps slug -> journey name for tasks that define one.
    """
    required_journeys = required_journeys or {}
    if tasks is None:
        params = {"select": "id,slug,state,artifact_commit,artifact_branch"}
        if project:
            params["project"] = f"eq.{project}"
        tasks = paginate(select_fn, "tasks", params, order="slug.asc")

    slugs = [t.get("slug") for t in tasks if isinstance(t, dict) and t.get("slug")]
    evidence = gather_evidence(select_fn, project=project, slugs=slugs)

    entries = [project_task(t, evidence, required_journeys.get((t or {}).get("slug")))
               for t in tasks]

    summary = {v: 0 for v in VERDICTS}
    by_level = {lvl: 0 for lvl in LEVELS}
    for entry in entries:
        summary[entry["verdict"]] = summary.get(entry["verdict"], 0) + 1
        by_level[entry["level"]] = by_level.get(entry["level"], 0) + 1

    return {
        "project": project or "",
        "entries": entries,
        "summary": summary,
        "by_level": by_level,
        "read_errors": evidence.get("read_errors") or [],
    }


def audit(ledger):
    """Assert the ledger's own invariants. Returns a list of violations (empty == clean).

    Used by the regression fixtures and safe to call in production: it reads, it does not
    write. Catching a violation here is the point — an invariant that is only in a
    docstring is an invariant that drifts.
    """
    violations = []
    for entry in (ledger or {}).get("entries", []) or []:
        slug = entry.get("slug")
        if entry.get("verdict") == PASS and not entry.get("receipt"):
            violations.append(f"{slug}: PASS without a receipt")
        if entry.get("verdict") == PASS and entry.get("level") != LEVEL_DEPLOYED_AND_VERIFIED:
            violations.append(f"{slug}: PASS at level {entry.get('level')}, "
                              f"only {LEVEL_DEPLOYED_AND_VERIFIED} may pass")
        if entry.get("level") == LEVEL_MERGED and entry.get("verdict") == PASS:
            violations.append(f"{slug}: MERGED rendered as PASS — MERGED proves reachability only")
        if entry.get("verdict") not in VERDICTS:
            violations.append(f"{slug}: unrecognised verdict {entry.get('verdict')!r}")
        if level_rank(entry.get("level")) < 0:
            violations.append(f"{slug}: unrecognised level {entry.get('level')!r}")
        if entry.get("receipt") and not (entry["receipt"] or {}).get("ref"):
            violations.append(f"{slug}: receipt with a blank ref")
    return violations


def snapshot(ledger):
    """Shape the ledger for the snapshot API / proof UI.

    Deliberately lossy in one direction only: it drops internal fields, never a reason.
    The UI's job is to show why something is not proven, so the reasons are the payload.
    """
    ledger = ledger or {}
    return {
        "project": ledger.get("project", ""),
        "summary": ledger.get("summary", {}),
        "by_level": ledger.get("by_level", {}),
        "read_errors": ledger.get("read_errors", []),
        "entries": [
            {
                "slug": e.get("slug"),
                "level": e.get("level"),
                "verdict": e.get("verdict"),
                "receipt": e.get("receipt"),
                "reasons": e.get("reasons", []),
            }
            for e in ledger.get("entries", []) or []
        ],
    }


if __name__ == "__main__":
    import json
    import db
    print(json.dumps(snapshot(build_ledger(db.select, project=os.environ.get("ORCH_PROOF_PROJECT"))),
                     indent=2, default=str))
