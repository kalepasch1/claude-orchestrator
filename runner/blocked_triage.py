#!/usr/bin/env python3
"""blocked_triage.py — auto-remediate BLOCKED task shards without operator prompting.

WHY THIS EXISTS (operator directive 2026-07-30): tonight's blocked shards were all resolvable by
pattern — but they sat BLOCKED until the operator manually asked, was told, and approved the same
four fixes a bot could have applied. This module codifies that exact triage as a standing loop:

  CLASS 1  verify rejected: secret-SHAPED data (types/template IDs/digest fields pattern-matching
           the secrets scanner) -> requeue with placeholder rules (env-var names only, no literal
           long hex/base64 in types/migrations/fixtures, obvious placeholders in comments).
  CLASS 2  verify rejected: permissive allowlist -> requeue with deny-by-default allowlist rule.
  CLASS 3  verify PASSED but integrate=BLOCKED (local lock/branch contention) -> requeue to retry
           integration; if contention persists, leave the branch for merge-train pickup per the
           worktree convention rather than forcing.
  CLASS 4  exhausted retries -> requeue SHARDED SMALLER with an escalated model tier (big changes
           that keep failing land as three independent pieces, not one large one).
  CLASS 5  missing test coverage -> requeue with the test requirement made explicit.

SAFETY RAILS (what keeps auto-requeue from becoming an infinite loop):
  * Max ORCH_TRIAGE_MAX_REQUEUES per task (default 2), tracked via a [triage:N] marker in note —
    a shard that fails again after two targeted requeues gets ESCALATED (coordination event +
    stays BLOCKED for a human), because a third identical retry is just burning tokens.
  * Only tasks BLOCKED > ORCH_TRIAGE_MIN_AGE_MIN minutes (default 10) — never race a live verdict.
  * Deterministic classification only (note-pattern matching, no LLM) — the triage itself can
    never hallucinate a fix; unknown blocker classes are left alone and surfaced in the digest.
  * Every action is logged + a digest persists to the coordination KV so the progress console
    (and the operator) can see what was auto-remediated and why.
"""
from __future__ import annotations
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MAX_REQUEUES = int(os.environ.get("ORCH_TRIAGE_MAX_REQUEUES", "2"))
MIN_AGE_MIN  = int(os.environ.get("ORCH_TRIAGE_MIN_AGE_MIN", "10"))
BATCH        = int(os.environ.get("ORCH_TRIAGE_BATCH", "12"))

CLASSES = [
    ("secret_shaped", re.compile(r"secret[- ]?(like|shaped)|added secret|introduced a secret", re.I),
     "Prior attempt rejected by verify for secret-SHAPED data. REWORK RULES: credentials/IDs go in "
     "env vars referenced by NAME only (documented empty in .env.example); no literal long "
     "hex/base64 strings in types, migrations, or fixtures — use obvious placeholders "
     "('sha256-of-artifact', ''); public metadata fields (digests, as_of, basis) must not carry "
     "example values that pattern-match secrets."),
    ("permissive_allowlist", re.compile(r"allowlist that seems permissive|permissive allowlist|without proper authorization or allowlist", re.I),
     "Prior attempt rejected by verify for a permissive allowlist. REWORK RULES: allowlists are "
     "explicit and deny-by-default; every entry justified in a comment; no wildcard grants."),
    ("integrate_contention", re.compile(r"integrate=BLOCKED.*local|index\.lock|branch.*(held|locked)|worktree.*(held|locked)", re.I),
     "Verify PASSED; integration hit local lock/branch contention. Retry integration now; if "
     "contention persists, push the branch and leave it for merge-train pickup per the worktree "
     "convention — never force, never touch the main checkout."),
    ("exhausted_retries", re.compile(r"exhausted retries|max retries|retry budget", re.I),
     "Prior attempts exhausted retries. ESCALATE + SHARD: use a stronger model tier for this "
     "attempt, and split the work into 2-3 independently-mergeable pieces (module+tests, wiring, "
     "surface) — land each separately instead of one large change."),
    ("model_misroute_404", re.compile(r"model '.+' (does not exist|not found)|404.*model|invalid model", re.I),
     "Prior attempt hit a vendor model-404 (a model name sent to the wrong vendor, or a retired "
     "model id). The dispatch-level misroute guard now reroutes coherently; requeue and let "
     "routing re-resolve. If it recurs, the model id itself is stale — update the tranche/config."),
    ("missing_tests", re.compile(r"missing test|no test coverage|without tests", re.I),
     "Prior attempt rejected for missing test coverage. Every new module ships with tests "
     "(vitest/pytest per repo convention); the verify gate requires them."),
]

_TRIAGE_MARK = re.compile(r"\[triage:(\d+)\]")


def _requeue_count(note):
    m = _TRIAGE_MARK.search(note or "")
    return int(m.group(1)) if m else 0


def _classify(note):
    for name, rx, fix in CLASSES:
        if rx.search(note or ""):
            return name, fix
    return None, None


def _emit(kind, **kw):
    try:
        import coordination  # optional seam; fall back to print
        coordination.emit(kind, **kw)
    except Exception:
        print(f"blocked_triage: {kind}: {json.dumps(kw)[:300]}")


def run(limit=BATCH):
    try:
        rows = db.select("tasks", {
            "select": "id,slug,note,updated_at,state",
            "state": "eq.BLOCKED", "order": "updated_at.asc", "limit": str(limit * 3)}) or []
    except Exception:
        rows = []
    out = {"scanned": len(rows), "requeued": 0, "escalated": 0, "unknown": 0, "too_fresh": 0}
    now = time.time()
    acted = 0
    digest = []
    for t in rows:
        if acted >= limit:
            break
        note = t.get("note") or ""
        # age gate
        try:
            import datetime
            upd = datetime.datetime.fromisoformat(str(t.get("updated_at")).replace("Z", "+00:00"))
            if (now - upd.timestamp()) < MIN_AGE_MIN * 60:
                out["too_fresh"] += 1
                continue
        except Exception:
            pass
        cls, fix = _classify(note)
        if not cls:
            out["unknown"] += 1
            digest.append({"id": t["id"], "slug": (t.get("slug") or "")[:60],
                           "action": "left_alone", "reason": "unknown blocker class"})
            continue
        n = _requeue_count(note)
        if n >= MAX_REQUEUES:
            out["escalated"] += 1
            _emit("triage-escalation", task=t["id"], slug=t.get("slug"), cls=cls, attempts=n)
            digest.append({"id": t["id"], "slug": (t.get("slug") or "")[:60],
                           "action": "escalated_to_human", "class": cls, "attempts": n})
            continue
        # read-then-write: append the targeted fix to the prompt, then flip to QUEUED atomically
        try:
            cur = db.select("tasks", {"select": "prompt", "id": f"eq.{t['id']}"}) or [{}]
            newp = (cur[0].get("prompt") or "") + (
                f"\n\n## AUTO-TRIAGE REQUEUE #{n + 1} ({time.strftime('%Y-%m-%d %H:%MZ', time.gmtime())}, class: {cls})\n{fix}")
            db.update("tasks", {"id": t["id"]}, {
                "prompt": newp,
                "note": (note + f" | [triage:{n + 1}] auto-requeued ({cls})")[:2000],
                "state": "QUEUED"})
            out["requeued"] += 1
            acted += 1
            digest.append({"id": t["id"], "slug": (t.get("slug") or "")[:60],
                           "action": "requeued", "class": cls, "attempt": n + 1})
        except Exception as e:
            print(f"blocked_triage: requeue failed for {t['id']}: {type(e).__name__}: {str(e)[:120]}")
    # persist the digest so the progress console shows WHAT was auto-remediated and WHY
    try:
        db.insert("coordination_tasks", {
            "task_type": "triage_digest",
            "payload": json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                   **out, "actions": digest[:40]})[:16000]}, upsert=False)
    except Exception:
        pass
    print("blocked_triage: " + json.dumps(out))
    try:
        fleet_liveness_check()
    except Exception:
        pass
    try:
        release_currency_check()
    except Exception:
        pass
    try:
        infra_failure_recovery()
    except Exception:
        pass
    try:
        fleet_config_secret_audit()
    except Exception:
        pass
    try:
        env_permission_sweep()
    except Exception:
        pass
    return out


def env_permission_sweep(root=None):
    """Keep every .env on this machine owner-only (0600).

    A one-time chmod does not hold: agent worktrees under {repo}-wt/ are created and
    destroyed continuously, and each new tree's .env lands with the default 0644 umask.
    The 2026-08-02 sweep hardened 45 files, and 28 more had already appeared minutes
    later. Permissions therefore have to be maintained, not fixed.

    Templates (.env.example / .env.sample) are deliberately left alone — they hold no
    secrets and are meant to be readable.
    """
    import stat as _stat
    root = root or os.path.expanduser("~/Documents")
    max_depth = int(os.environ.get("ORCH_ENV_SWEEP_DEPTH", "5"))
    fixed, scanned = [], 0
    root_depth = root.rstrip("/").count("/")

    for dirpath, dirnames, filenames in os.walk(root):
        if dirpath.count("/") - root_depth >= max_depth:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames
                       if d not in ("node_modules", ".git", "Library", ".venv", "venv")]
        for fn in filenames:
            if not fn.startswith(".env") or fn.endswith((".example", ".sample")):
                continue
            p = os.path.join(dirpath, fn)
            try:
                mode = os.stat(p).st_mode
                scanned += 1
                if mode & (_stat.S_IRGRP | _stat.S_IROTH | _stat.S_IWGRP | _stat.S_IWOTH):
                    os.chmod(p, 0o600)
                    fixed.append(p.replace(os.path.expanduser("~"), "~"))
            except OSError:
                continue

    result = {"scanned": scanned, "hardened": len(fixed)}
    if fixed:
        print(f"blocked_triage.env_sweep: hardened {len(fixed)} readable .env file(s) to 0600")
        try:
            db.insert("coordination_tasks", {
                "task_type": "env_permission_sweep",
                "payload": json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                       **result, "paths": fixed[:40]})[:16000]}, upsert=False)
        except Exception:
            pass
    return result


def fleet_config_secret_audit():
    """Standing check that no credential is sitting in fleet_config.

    The db-layer guard blocks NEW writes, but a row planted before the guard existed —
    or by a future path that bypasses db.py (raw SQL, a psql session, the Supabase
    dashboard) — would sit there indefinitely. On 2026-08-02 five did, including a
    GITHUB_PAT with push access to every repo, and nothing ever said so.

    Reports keys and value LENGTHS only; never the material.
    """
    try:
        import fleet_config_guard
        rows = db.select("fleet_config", {"select": "key,value"}) or []
    except Exception as e:
        print(f"blocked_triage: fleet_config audit could not run: {str(e)[:120]}")
        return {"error": "unreadable"}

    hits = fleet_config_guard.scan_rows(rows)
    result = {"scanned": len(rows), "credentials_found": len(hits),
              "keys": [h["key"] for h in hits]}
    if hits:
        print(f"blocked_triage: SECRET IN FLEET_CONFIG — {result['keys']}")
        try:
            db.insert("approvals", {
                "project": "ORCHESTRATOR", "kind": "self",
                "title": "Credential stored in fleet_config",
                "why": (f"{len(hits)} fleet_config row(s) hold credential material: "
                        f"{', '.join(h['key'] for h in hits)}. fleet_config is replicated "
                        f"fleet-wide, echoed into drift reports and config diffs, and has no "
                        f"row-level protection."),
                "value": "Rotate the credential at its provider, put the new value in the host "
                         "env/secret store only, then delete the fleet_config row.",
                "risk": "Any process that can read fleet config can read the secret.",
                "command": ""})
        except Exception:
            pass  # unique index on (kind,title) rejects duplicates — fine
    return result


# ---------------------------------------------------------------------------
# Infrastructure-failure recovery (throughput class, added 2026-08-02)
# ---------------------------------------------------------------------------
# A task that burned its 4 attempts because the OAuth session expired, the API
# rate-limited us, or the DB blipped is NOT a bad task — but the attempt counter
# cannot tell the difference, so it lands in QUARANTINED and its work is lost.
# A quarantine audit found 48 tasks in that pool, several with
# "OAuth session expired and could not be refreshed" as the last log line and 22
# with no log tail at all (a silent failure — the class this fleet keeps paying
# for). Those are recoverable; a genuine code failure is not.
_INFRA_PATTERNS = re.compile(
    r"oauth|session expired|could not be refreshed|not authenticated|401|403|"
    r"rate.?limit|usage limit|429|quota|"
    r"timed? ?out|timeout|connection (reset|refused|aborted)|"
    r"temporarily unavailable|50[0234] |bad gateway|"
    r"circuit ?open|call cap|db=down|database is down",
    re.I)
_INFRA_MARK = re.compile(r"\[infra-recover:(\d+)\]")
MAX_INFRA_RECOVERIES = int(os.environ.get("ORCH_MAX_INFRA_RECOVERIES", "2"))


def _is_infra_failure(log_tail):
    """True when the evidence says the platform failed, not the work.

    An EMPTY log tail counts as infrastructure: a task that produced no output at
    all did not fail code review, it never ran. Treating silence as a real failure
    is what quietly discarded 22 tasks.
    """
    lt = (log_tail or "").strip()
    if not lt or lt in ("{}", "[]", "null"):
        return True, "no output — the task never actually ran"
    m = _INFRA_PATTERNS.search(lt)
    return (True, m.group(0)[:60]) if m else (False, "")


def infra_failure_recovery(limit=None):
    """Requeue quarantined tasks whose failure was infrastructure, not code.

    Coverage doctrine: the digest NAMES what was recovered AND what was left
    behind with the reason, so a zero here is never mistaken for a clean pool.
    """
    limit = int(limit or os.environ.get("ORCH_INFRA_RECOVERY_BATCH", "40"))
    try:
        rows = db.select("tasks", {
            "select": "id,slug,note,reason,log_tail,attempt,state",
            "state": "eq.QUARANTINED", "limit": "400"}) or []
    except Exception as e:
        print(f"blocked_triage: infra recovery could not read the queue: {str(e)[:120]}")
        return {"error": "queue_unreadable"}

    out = {"scanned": len(rows), "recovered": 0, "left": 0}
    recovered, left = [], []
    for t in rows:
        blob = f"{t.get('reason') or ''} {t.get('note') or ''}"
        # Only the attempt-exhaustion pool. Dedupe/supersede quarantines are correct
        # and must stay quarantined — re-running them would resurrect duplicate work.
        if "exhausted" not in blob.lower():
            continue
        n = int((_INFRA_MARK.search(blob).group(1)) if _INFRA_MARK.search(blob) else 0)
        if n >= MAX_INFRA_RECOVERIES:
            left.append({"slug": (t.get("slug") or "")[:60],
                         "why": f"already recovered {n}x — needs a human"})
            out["left"] += 1
            continue
        is_infra, evidence = _is_infra_failure(t.get("log_tail"))
        if not is_infra:
            left.append({"slug": (t.get("slug") or "")[:60], "why": "real code failure"})
            out["left"] += 1
            continue
        if len(recovered) >= limit:
            left.append({"slug": (t.get("slug") or "")[:60], "why": "batch limit — next sweep"})
            out["left"] += 1
            continue
        try:
            db.update("tasks", {"id": t["id"]}, {
                "state": "QUEUED",
                "attempt": 0,   # the attempts were spent on the platform, not the work
                "note": (f"{t.get('note') or ''} | [infra-recover:{n + 1}] requeued: "
                         f"{evidence}")[:2000]})
            recovered.append({"slug": (t.get("slug") or "")[:60], "evidence": evidence})
            out["recovered"] += 1
        except Exception as e:
            left.append({"slug": (t.get("slug") or "")[:60],
                         "why": f"update failed: {type(e).__name__}"})
            out["left"] += 1

    try:
        db.insert("coordination_tasks", {
            "task_type": "infra_recovery_digest",
            "payload": json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                   **out, "recovered": recovered[:40],
                                   "left_behind": left[:40]})[:16000]}, upsert=False)
    except Exception:
        pass
    print("blocked_triage.infra_recovery: " + json.dumps(out))
    return out


def fleet_liveness_check():
    """Stale-process / silent-heartbeat sentinel (2026-07-31 incident class).

    Catches the two invisible outage modes autonomously:
      1. Heartbeats empty/stale WHILE tasks are actively being touched — means the
         heartbeat publisher is silently failing (schema drift, swallowed errors).
      2. A live host's code_sha differs from the repo HEAD known to this process —
         means a runner is executing stale in-memory code (Python doesn't hot-reload).
    Emits a CRITICAL coordination event; the code-drift self-restart in
    fleet_control handles remediation locally, this is the belt to that suspenders.
    """
    findings = []
    try:
        hb = db.select("runner_heartbeats", {"select": "runner_id,hostname,code_sha,last_seen",
                                             "order": "last_seen.desc", "limit": "10"}) or []
        recent = db.select("tasks", {"select": "id",
                                     "updated_at": f"gt.{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() - 600))}",
                                     "limit": "1"}) or []
        if recent and not hb:
            findings.append("CRITICAL: tasks active in last 10m but ZERO heartbeats — "
                            "heartbeat publisher silently failing (schema drift?)")
        try:
            import subprocess as _sp
            head = _sp.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                           cwd=os.path.dirname(os.path.abspath(__file__))).stdout.strip()
            for h in hb:
                sha = (h.get("code_sha") or "")[:8]
                if head and sha and not head.startswith(sha) and not sha.startswith(head[:8]):
                    findings.append(f"code-drift: {h.get('hostname')} running {sha}, "
                                    f"disk HEAD {head[:8]} — self-restart should fire within 90s")
        except Exception:
            pass
        if findings:
            db.insert("coordination_tasks", {
                "task_type": "fleet_liveness_alert",
                "payload": json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                       "findings": findings})[:8000]}, upsert=False)
            for f in findings:
                print(f"blocked_triage[liveness]: {f}", flush=True)
    except Exception as e:
        print(f"blocked_triage: liveness check failed ({type(e).__name__})")
    # Undefined-name static gate (NameError class, 2026-07-31)
    try:
        import static_sanity
        sf = static_sanity.check()
        if sf:
            findings.append("CRITICAL undefined names: " + "; ".join(sf[:5]))
            db.insert("coordination_tasks", {
                "task_type": "static_sanity_alert",
                "payload": json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                       "findings": sf[:20]})[:8000]}, upsert=False)
            for f_ in findings[-1:]:
                print(f"blocked_triage[static]: {f_}", flush=True)
    except Exception:
        pass
    return findings


RELEASE_CURRENCY_MAX_BRANCHES = int(os.environ.get("ORCH_RELEASE_CURRENCY_MAX_BRANCHES", "25"))
RELEASE_CURRENCY_MAX_MASTER_AGE_H = int(os.environ.get("ORCH_RELEASE_CURRENCY_MAX_MASTER_AGE_H", "48"))


def release_currency_check():
    """NEW SCOPE (operator directive 2026-07-31): the prod-behind-built-work class.

    244 unmerged agent branches sat on apparently (1,174 on tomorrow) while prod
    served weeks-old masters — and NOTHING alerted, because every monitor watched
    process health, not OUTCOME currency. This check watches the outcome:

      For each project: count unmerged origin agent/* heads and the age of
      origin/<base>. If branches exceed the threshold AND base hasn't advanced
      within the window, prod is falling behind the built work — file a CRITICAL
      release_currency_alert naming the project, counts, and age, so the
      catch-up drive / operator acts the same day, not weeks later.

    Read-only + fail-soft; runs in the triage cycle (10 min) but self-limits to
    one full scan per 6h via a KV timestamp.
    """
    import subprocess
    findings = []
    try:
        gate = db.select("coordination_tasks", {
            "select": "created_at", "task_type": "eq.release_currency_scan",
            "order": "created_at.desc", "limit": "1"}) or []
        if gate:
            import datetime
            last = datetime.datetime.fromisoformat(
                str(gate[0]["created_at"]).replace("Z", "+00:00"))
            if (time.time() - last.timestamp()) < 6 * 3600:
                return []
    except Exception:
        pass
    try:
        projects = db.select("projects", {"select": "name,repo_path,default_base"}) or []
    except Exception:
        return []
    for p in projects:
        try:
            repo = db.localize_repo_path(p.get("repo_path") or "")
            if not repo or not os.path.isdir(repo):
                continue
            base = p.get("default_base") or "master"
            heads = subprocess.run(["git", "ls-remote", "--heads", "origin"],
                                   cwd=repo, capture_output=True, text=True, timeout=60)
            n_branches = sum(1 for l in (heads.stdout or "").splitlines()
                             if "refs/heads/agent/" in l)
            age = subprocess.run(["git", "log", f"origin/{base}", "-1", "--format=%ct"],
                                 cwd=repo, capture_output=True, text=True, timeout=30)
            try:
                age_h = (time.time() - float((age.stdout or "0").strip())) / 3600
            except ValueError:
                age_h = -1
            if n_branches > RELEASE_CURRENCY_MAX_BRANCHES and age_h > RELEASE_CURRENCY_MAX_MASTER_AGE_H:
                findings.append({"project": p.get("name"), "unmerged_agent_branches": n_branches,
                                 "base_age_hours": round(age_h, 1)})
        except Exception:
            continue
    try:
        db.insert("coordination_tasks", {"task_type": "release_currency_scan",
                                         "payload": json.dumps({"at": time.strftime(
                                             "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                             "flagged": len(findings)})[:2000]}, upsert=False)
        if findings:
            db.insert("coordination_tasks", {
                "task_type": "release_currency_alert",
                "payload": json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                       "findings": findings,
                                       "action": "run runner/catchup_drive.sh or inspect the "
                                                 "merge train — prod is falling behind built work"})[:8000]},
                      upsert=False)
            for f in findings:
                print(f"blocked_triage[release-currency]: CRITICAL {f['project']}: "
                      f"{f['unmerged_agent_branches']} unmerged agent branches, base "
                      f"{f['base_age_hours']}h stale", flush=True)
    except Exception:
        pass
    return findings


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
    fleet_liveness_check()
