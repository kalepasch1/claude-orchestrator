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


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
    fleet_liveness_check()
