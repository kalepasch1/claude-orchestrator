#!/usr/bin/env python3
"""improvement_verify.py — REQUIREMENTS B, C, D: ship gate, measurement window, rollback.

THE THREE THINGS THE OLD LOOP COULD NOT DO
------------------------------------------
B. SHIP GATE = DIFF EXISTS. `mark_shipped()` used to mark a proposal shipped iff a
   slug-matching task was MERGED and *any* later release succeeded. That is a
   coincidence detector, not a ship gate: 8 of 10 "shipped" proposals had
   artifact_commit NULL. Here a proposal is shipped only when
   `landed_evidence.find_evidence()` returns a real sha that (a) names the slug at a
   token boundary, (b) is not recovery scaffolding, (c) CHANGES THE TREE, and (d) is
   reachable from an integration ref. No sha -> not shipped. Ever.

C. MEASUREMENT WINDOW. Shipping records `shipped_at` and `evaluate_after`. After that
   instant the proposal's own `metric_query` is re-run and compared to the
   `baseline_value` captured at creation.

D. ROLLBACK IS CODE, NOT ADVICE. If the metric fails to beat baseline by
   `required_margin` inside the window, `git revert` the evidence sha for real and set
   status='regressed'. The predecessor "actuated" by appending advisory strings to a
   JSON file that nothing read.

Every decision goes through gate_liveness.record(), so a gate here that starts
answering the same thing for everything alarms within a day (requirement E).
"""
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import gate_liveness
import landed_evidence

DEFAULT_WINDOW_HOURS = int(os.environ.get("ORCH_IMPROVE_WINDOW_HOURS", "72"))
DEFAULT_MARGIN = float(os.environ.get("ORCH_IMPROVE_MIN_MARGIN", "1.10"))
# Guardrail: rollback pushes to the integration ref, never to a primary branch.
PUSH_TARGET = os.environ.get("ORCH_STAGING_BRANCH", "orchestrator/dev")
ROLLBACK_ENABLED = os.environ.get("ORCH_IMPROVE_ROLLBACK_PUSH", "false").lower() in (
    "1", "true", "yes", "on")

SHIP_GATE = "improvement_ship_gate"
MEASURE_GATE = "improvement_measurement_gate"
ROLLBACK_GATE = "improvement_rollback_gate"


# --------------------------------------------------------------------------- helpers
def _git(repo, *args, timeout=120):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def _repo_for(app):
    for p in (db.select("projects", {"select": "name,repo_path", "name": f"eq.{app}"}) or []):
        path = p.get("repo_path")
        try:
            path = db.localize_repo_path(path)
        except Exception:
            pass
        if path and os.path.isdir(path):
            return path
    return None


def _now():
    return datetime.now(timezone.utc)


def _parse(ts):
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def diff_is_nonempty(repo, sha):
    """True when `sha` actually changes the tree relative to its first parent.

    This is the predicate the old gate never had. A zero-diff commit — an empty merge,
    a stub, a revert-of-a-revert — is NOT a ship.
    """
    if not repo or not sha:
        return False
    p = _git(repo, "rev-list", "--parents", "-n", "1", sha)
    if p.returncode != 0 or not p.stdout.strip():
        return False
    parts = p.stdout.split()
    return landed_evidence._changes_tree(repo, parts[0], parts[1:])


def sha_reachable_from(repo, sha, ref):
    """True when `sha` is an ancestor of (or equal to) the release ref."""
    if not (repo and sha and ref):
        return False
    if _git(repo, "rev-parse", "--verify", "--quiet", ref).returncode != 0:
        return False
    return _git(repo, "merge-base", "--is-ancestor", sha, ref).returncode == 0


# ------------------------------------------------------------------- B: the ship gate
def ship_evidence(app, slug):
    """Return {'sha','ref','subject','repo'} only if real code for `slug` landed.

    Three independent conditions, all required:
      1. boundary-exact, non-scaffolding, tree-changing commit  (landed_evidence)
      2. a non-empty diff for that sha                          (diff_is_nonempty)
      3. reachability from an integration/release ref           (sha_reachable_from)
    """
    repo = _repo_for(app)
    if not repo:
        gate_liveness.record(SHIP_GATE, "no_repo", slug, f"app={app}")
        return None
    ev = landed_evidence.find_evidence(repo, slug)
    if not ev:
        gate_liveness.record(SHIP_GATE, "no_evidence", slug, f"repo={repo}")
        return None
    sha, ref, subject = ev
    if not diff_is_nonempty(repo, sha):
        gate_liveness.record(SHIP_GATE, "empty_diff", slug, sha)
        return None
    if not sha_reachable_from(repo, sha, ref):
        gate_liveness.record(SHIP_GATE, "unreachable", slug, f"{sha} not in {ref}")
        return None
    gate_liveness.record(SHIP_GATE, "shipped", slug, f"{sha[:12]} on {ref}")
    return {"sha": sha, "ref": ref, "subject": subject, "repo": repo}


def mark_shipped(limit=500):
    """Promote proposals to 'shipped' ONLY with diff evidence, and open the window."""
    rows = db.select("improvement_proposals", {
        "select": "id,app,task_slug,status,evaluate_after,shipped_at",
        "status": "in.(queued,merged)", "limit": str(limit)}) or []
    shipped = rejected = 0
    for p in rows:
        slug = p.get("task_slug")
        if not slug:
            continue
        ev = ship_evidence(p.get("app"), slug)
        if not ev:
            rejected += 1
            if p.get("status") != "merged":
                db.update("improvement_proposals", {"id": p["id"]}, {"status": "merged"})
            continue
        now = _now()
        db.update("improvement_proposals", {"id": p["id"]}, {
            "status": "shipped",
            "shipped_at": now.isoformat(),
            "artifact_commit": ev["sha"],
            "artifact_ref": ev["ref"],
            "artifact_repo": ev["repo"],
            "evaluate_after": (p.get("evaluate_after")
                               or (now + timedelta(hours=DEFAULT_WINDOW_HOURS)).isoformat()),
        })
        shipped += 1
    print(f"improvement_verify.mark_shipped: {shipped} shipped with diff evidence, "
          f"{rejected} rejected for missing/empty/unreachable diff")
    return {"shipped": shipped, "rejected": rejected}


# ------------------------------------------------- C: re-measure after the window closes
def _metric_value(p, injected=None):
    """Re-run the proposal's own metric. `injected` is for tests / simulated windows."""
    if injected is not None:
        return float(injected)
    import bottleneck_detector
    if p.get("metric_query"):
        return bottleneck_detector.scalar(p["metric_query"])
    key = p.get("metric_collector")
    if key in bottleneck_detector.COLLECTORS:
        return bottleneck_detector.scalar(bottleneck_detector.COLLECTORS[key][4])
    return None


def realized_multiplier(baseline, realized, comparator):
    """How many times better the metric actually got. <1.0 means it got worse."""
    if baseline is None or realized is None:
        return None
    if comparator == "lt":
        if realized <= 0:
            return None
        return round(baseline / realized, 4)
    if baseline <= 0:
        return None
    return round(realized / baseline, 4)


def evaluate(p, injected=None, now=None):
    """Judge one shipped proposal against its own baseline. Pure decision, no writes."""
    now = now or _now()
    due = _parse(p.get("evaluate_after"))
    if due and now < due:
        return {"verdict": "pending", "reason": f"window open until {due.isoformat()}"}
    baseline = p.get("baseline_value")
    if baseline is None:
        return {"verdict": "unmeasurable", "reason": "no baseline_value captured at creation"}
    baseline = float(baseline)
    comparator = p.get("comparator") or "lt"
    margin = float(p.get("required_margin") or DEFAULT_MARGIN)
    realized = _metric_value(p, injected)
    if realized is None:
        return {"verdict": "unmeasurable", "reason": "metric_query returned no value"}
    mult = realized_multiplier(baseline, realized, comparator)
    if mult is None:
        return {"verdict": "unmeasurable", "reason": "multiplier undefined at these values"}
    ok = mult >= margin
    return {"verdict": "validated" if ok else "regressed", "realized": realized,
            "baseline": baseline, "multiplier": mult, "margin": margin,
            "comparator": comparator,
            "reason": f"{mult}x vs required {margin}x (baseline {baseline} -> {realized})"}


# ------------------------------------------------------------------ D: the real rollback
def revert_commit(repo, sha, dry_run=None):
    """ACTUALLY revert `sha`. Returns {'ok','revert_sha','detail'}.

    dry_run defaults to "not ORCH_IMPROVE_ROLLBACK_PUSH": the revert commit is always
    created locally on a scratch branch so the operation is proven executable, and is
    only pushed to the integration ref when the operator has enabled pushing.
    """
    if dry_run is None:
        dry_run = not ROLLBACK_ENABLED
    if not repo or not os.path.isdir(repo):
        return {"ok": False, "detail": f"repo not available: {repo}"}
    if _git(repo, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
        return {"ok": False, "detail": f"sha not found in {repo}: {sha}"}
    branch = f"revert/auto-{sha[:12]}-{int(time.time())}"
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    wt = os.path.join(repo, ".runtime", "revert-wt", branch.replace("/", "_"))
    os.makedirs(os.path.dirname(wt), exist_ok=True)
    add = _git(repo, "worktree", "add", "-b", branch, wt, base)
    if add.returncode != 0:
        return {"ok": False, "detail": f"worktree add failed: {add.stderr.strip()[:300]}"}
    try:
        parents = _git(repo, "rev-list", "--parents", "-n", "1", sha).stdout.split()
        args = ["revert", "--no-edit", sha]
        if len(parents) > 2:                       # a merge commit needs a mainline
            args = ["revert", "--no-edit", "-m", "1", sha]
        r = _git(wt, *args)
        if r.returncode != 0:
            _git(wt, "revert", "--abort")
            return {"ok": False, "detail": f"revert failed: {r.stderr.strip()[:300]}"}
        revert_sha = _git(wt, "rev-parse", "HEAD").stdout.strip()
        if not diff_is_nonempty(wt, revert_sha):
            return {"ok": False, "revert_sha": revert_sha,
                    "detail": "revert produced an empty diff — refusing to call it a rollback"}
        if dry_run:
            return {"ok": True, "revert_sha": revert_sha, "pushed": False,
                    "detail": f"revert commit {revert_sha[:12]} created on {branch} "
                              f"(push disabled; set ORCH_IMPROVE_ROLLBACK_PUSH=1)"}
        push = _git(wt, "push", "origin", f"HEAD:{PUSH_TARGET}")
        return {"ok": push.returncode == 0, "revert_sha": revert_sha,
                "pushed": push.returncode == 0,
                "detail": (push.stderr or push.stdout).strip()[:300]}
    finally:
        _git(repo, "worktree", "remove", "--force", wt)
        _git(repo, "branch", "-D", branch)


def _record_calibration(p, res, outcome):
    """F: predicted multiplier vs realized — the prediction is now scored."""
    try:
        db.insert("improvement_calibration", {
            "proposal_id": p.get("id"), "task_slug": p.get("task_slug"),
            "surface": p.get("surface"), "metric_name": p.get("metric_name"),
            "predicted_multiplier": p.get("predicted_multiplier"),
            "realized_multiplier": res.get("multiplier"),
            "baseline_value": res.get("baseline"), "realized_value": res.get("realized"),
            "outcome": outcome})
    except Exception as exc:
        print(f"[improvement_verify] calibration insert failed: {exc}")


def settle(p, injected=None, now=None, dry_run=None):
    """Evaluate one shipped proposal and ACT: validate, or revert and mark regressed."""
    res = evaluate(p, injected=injected, now=now)
    gate_liveness.record(MEASURE_GATE, res["verdict"], p.get("task_slug"), res.get("reason"))
    if res["verdict"] in ("pending", "unmeasurable"):
        return dict(res, acted=False)
    patch = {"realized_value": res.get("realized"),
             "realized_multiplier": res.get("multiplier"),
             "evaluated_at": (now or _now()).isoformat()}
    if res["verdict"] == "validated":
        patch["status"] = "validated"
        db.update("improvement_proposals", {"id": p["id"]}, patch)
        _record_calibration(p, res, "validated")
        gate_liveness.record(ROLLBACK_GATE, "not_needed", p.get("task_slug"), res["reason"])
        return dict(res, acted=True, rolled_back=False)
    rb = revert_commit(p.get("artifact_repo") or _repo_for(p.get("app")),
                       p.get("artifact_commit"), dry_run=dry_run)
    gate_liveness.record(ROLLBACK_GATE, "reverted" if rb.get("ok") else "revert_failed",
                         p.get("task_slug"), rb.get("detail"))
    patch["status"] = "regressed"
    if rb.get("ok"):
        patch["rollback_sha"] = rb.get("revert_sha")
        patch["rollback_at"] = (now or _now()).isoformat()
    db.update("improvement_proposals", {"id": p["id"]}, patch)
    _record_calibration(p, res, "regressed")
    return dict(res, acted=True, rolled_back=bool(rb.get("ok")), rollback=rb)


def settle_due(limit=100, dry_run=None):
    """Settle every shipped proposal whose measurement window has closed."""
    rows = db.select("improvement_proposals", {
        "select": "*", "status": "eq.shipped",
        "evaluate_after": f"lte.{_now().isoformat()}", "limit": str(limit)}) or []
    out = [dict(settle(p, dry_run=dry_run), slug=p.get("task_slug")) for p in rows]
    v = sum(1 for r in out if r.get("verdict") == "validated")
    g = sum(1 for r in out if r.get("verdict") == "regressed")
    print(f"improvement_verify.settle_due: {len(out)} due; {v} validated, {g} regressed")
    return out


def run():
    ms = mark_shipped()
    settled = settle_due()
    return {"mark_shipped": ms, "settled": settled}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
