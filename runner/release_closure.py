#!/usr/bin/env python3
"""release_closure.py — a task is not done until the user can SEE it.

WHY THIS MODULE EXISTS
----------------------
The observed symptom, stated by the operator: queued improvements never appeared on
landing or logged-in pages despite internal merge activity. That is a gap between two
things the fleet already measures well and one it does not measure at all.

PRIOR ART, SURVEYED BEFORE WRITING (nothing below is reimplemented):
  * runner/landed_evidence.py     — the ONE sound answer to "did this task's code land
                                    in the repo?" (token-boundary slug match, not
                                    recovery scaffolding, actually changes the tree).
                                    Consumed here as the MERGE stage. Not re-derived.
  * runner/improvement_verify.py  — ship gate + measurement window + real rollback for
                                    self-improvement proposals. Its `ship_evidence()` is
                                    the same landed-evidence predicate. Left alone.
  * runner/release_attribution.py — commit -> release attribution from git evidence.
                                    Supplies the PROMOTION stage input.
  * runner/done_evidence_gate.py  — blocks a NON-merge terminal state with no evidence.
                                    Complementary: that gate asks "is there any
                                    evidence?", this one asks "did it reach production
                                    and render?".

WHAT NONE OF THEM DO, AND WHAT THIS ADDS
    A merge commit reachable from an integration ref proves the code is in the REPO.
    It does not prove a release train promoted it, does not prove the promoted release
    is the deployment currently serving production, and proves nothing whatsoever about
    whether a route renders the change to a signed-out visitor or a signed-in user.
    Every one of those three can fail silently while `landed_evidence` says yes — which
    is precisely the reported symptom.

THE GOVERNING RULE: **MERGED IS NOT DONE.** `closure.closed` is true only when all
seven stages carry evidence. A task that stops at MERGED is reported as
`stage='merge_commit'`, not as complete.

CONVENTIONS (per CLAUDE.md)
  * fail-soft: every public function returns a sensible default rather than raising —
    an over-eager closure gate that blocks real work is worse than the gap it closes
  * all thresholds are ORCH_-prefixed env vars, so they are fleet-pushable via
    fleet_control.py rather than needing a deploy
  * module-level singleton for the dedupe ledger; module functions delegate to it
  * no secrets: `redact()` runs over every stored evidence string and assertion
"""
import hashlib
import os
import re
import threading
import time

# ─── Configuration ──────────────────────────────────────────────────────────
# ORCH_-prefixed so fleet_control.py can push these fleet-wide. No secrets here.

def _int_env(name, default):
    """Fail-soft env read. A malformed override must not wedge the gate."""
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


def deploy_slo_minutes():
    """How long a merge may sit unshipped before it is a release-fix candidate."""
    return _int_env("ORCH_RELEASE_DEPLOY_SLO_MIN", 90)


def assertion_slo_minutes():
    """How long after deployment a route may fail its assertion before alerting."""
    return _int_env("ORCH_RELEASE_ASSERT_SLO_MIN", 30)


# ─── The seven stages ───────────────────────────────────────────────────────
# Ordered. A closure reports the FURTHEST stage with evidence, and the first stage
# without it, because "which hop dropped it" is the only actionable output.

STAGES = (
    "queued",
    "branch",
    "merge_commit",
    "train_promoted",
    "deployed_sha",
    "public_route_asserted",
    "authed_route_asserted",
)

STAGE_LABEL = {
    "queued": "task exists in the queue",
    "branch": "an agent branch was pushed",
    "merge_commit": "a real commit changing the tree landed on an integration ref",
    "train_promoted": "the release train promoted a release containing that commit",
    "deployed_sha": "the production deployment's SHA contains that commit",
    "public_route_asserted": "a public route renders the change to a signed-out visitor",
    "authed_route_asserted": "an authenticated route renders the change to a signed-in user",
}

# ─── Secret redaction ───────────────────────────────────────────────────────
# Evidence is stored and shown to humans. Assertions capture page text, and page text
# from an AUTHENTICATED session is exactly where a token ends up.

_SECRET_PATTERNS = (
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{16,})\b"),                      # GitHub tokens
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),                                 # API keys
    re.compile(r"\bey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),  # JWT
    re.compile(r"(?i)\b(?:authorization|cookie|set-cookie|x-api-key)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\b(?:password|passwd|secret|token|api[_-]?key)\s*[:=]\s*\S+"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),      # emails
    re.compile(r"[?&](?:token|access_token|key|sig|signature)=[^&\s]+"),    # URL creds
)

REDACTED = "[REDACTED]"


def redact(value):
    """Strip anything that looks like a credential.

    Fail-soft by contract: any error returns "" rather than propagating, because a
    redaction failure must never be the reason an unredacted string gets stored.
    """
    try:
        if value is None:
            return ""
        text = str(value)
        for pattern in _SECRET_PATTERNS:
            text = pattern.sub(REDACTED, text)
        return text
    except Exception:
        return ""


def redact_all(values):
    """Redact a sequence, dropping anything that redacts to nothing."""
    try:
        return [r for r in (redact(v) for v in (values or [])) if r]
    except Exception:
        return []


# ─── Route assertions ───────────────────────────────────────────────────────

def route_assertion(route, audience, ok, before=None, after=None, status=None, evidence_url=None):
    """One route-level browser acceptance record.

    `before`/`after` are the assertion payload, NOT a screenshot. Screenshots of an
    authenticated page carry session state; the operator asked for evidence links and
    before/after assertions specifically without them, and this shape enforces that by
    having nowhere to put an image.
    """
    aud = "authed" if str(audience).lower() in ("authed", "authenticated", "user") else "public"
    return {
        "route": redact(route),
        "audience": aud,
        "ok": bool(ok),
        "status": status,
        "before": redact(before),
        "after": redact(after),
        "evidence_url": redact(evidence_url),
        "asserted_at": time.time(),
    }


def _first_failure(assertions, audience):
    for a in assertions or []:
        try:
            if a.get("audience") == audience and not a.get("ok"):
                return a
        except Exception:
            continue
    return None


def _any_pass(assertions, audience):
    for a in assertions or []:
        try:
            if a.get("audience") == audience and a.get("ok"):
                return True
        except Exception:
            continue
    return False


# ─── Closure evaluation ─────────────────────────────────────────────────────

def _minutes_since(ts, now=None):
    try:
        if not ts:
            return 0.0
        return max(0.0, ((now or time.time()) - float(ts)) / 60.0)
    except Exception:
        return 0.0


def _sha_matches(deployed_sha, merge_commit, deployed_contains=None):
    """Is the merge commit actually inside what production is serving?

    `deployed_contains` is the caller-supplied set of commits reachable from the
    deployment (from `git rev-list <deployed_sha>` or the platform API). When it is not
    supplied we fall back to exact SHA equality with prefix tolerance — deliberately
    STRICT, because the failure this whole module exists to catch is a deployment that
    looks plausible and does not contain the change.
    """
    try:
        if not deployed_sha or not merge_commit:
            return False
        if deployed_contains:
            contains = {str(c).lower() for c in deployed_contains}
            merge = str(merge_commit).lower()
            if merge in contains:
                return True
            return any(c.startswith(merge) or merge.startswith(c) for c in contains if c)
        a = str(deployed_sha).lower()
        b = str(merge_commit).lower()
        return a.startswith(b) or b.startswith(a)
    except Exception:
        return False


def evaluate_closure(evidence, now=None):
    """Evaluate one task's end-to-end release closure.

    `evidence` keys (all optional; absence is the thing being measured):
        task_id, slug, project
        branch                — agent/<slug> pushed
        merge_commit          — sha from landed_evidence.find_evidence(), NOT a grep
        merged_at             — epoch seconds
        release_id            — release-train promotion (release_attribution)
        deployed_sha          — the SHA production is actually serving
        deployed_contains     — commits reachable from the deployment, if known
        deployed_at           — epoch seconds
        assertions            — list from route_assertion()

    Returns a dict; never raises.
    """
    now = now or time.time()
    try:
        ev = dict(evidence or {})
    except Exception:
        ev = {}

    assertions = ev.get("assertions") or []
    reached = []
    failures = []

    if ev.get("task_id") or ev.get("slug"):
        reached.append("queued")
    if ev.get("branch"):
        reached.append("branch")
    if ev.get("merge_commit"):
        reached.append("merge_commit")
    if ev.get("release_id"):
        reached.append("train_promoted")

    sha_ok = _sha_matches(ev.get("deployed_sha"), ev.get("merge_commit"), ev.get("deployed_contains"))
    if ev.get("deployed_sha") and sha_ok:
        reached.append("deployed_sha")
    elif ev.get("deployed_sha") and not sha_ok:
        failures.append({
            "kind": "wrong_deployed_sha",
            "detail": "production is serving %s, which does not contain merge commit %s"
                      % (redact(ev.get("deployed_sha"))[:12], redact(ev.get("merge_commit"))[:12]),
        })

    if _any_pass(assertions, "public"):
        reached.append("public_route_asserted")
    else:
        failed = _first_failure(assertions, "public")
        if failed:
            failures.append({
                "kind": "failed_public_assertion",
                "detail": "public route %s did not render the change" % failed.get("route"),
                "route": failed.get("route"),
            })

    if _any_pass(assertions, "authed"):
        reached.append("authed_route_asserted")
    else:
        failed = _first_failure(assertions, "authed")
        if failed:
            failures.append({
                "kind": "failed_authenticated_assertion",
                "detail": "authenticated route %s did not render the change" % failed.get("route"),
                "route": failed.get("route"),
            })

    # A stale merge is the reported symptom in its purest form: code in the repo, past
    # the SLO, and nothing serving it.
    merge_age = _minutes_since(ev.get("merged_at"), now)
    if ev.get("merge_commit") and "deployed_sha" not in reached and merge_age > deploy_slo_minutes():
        failures.append({
            "kind": "stale_merge",
            "detail": "merged %.0f min ago (SLO %d) with no deployment containing the commit"
                      % (merge_age, deploy_slo_minutes()),
        })

    deploy_age = _minutes_since(ev.get("deployed_at"), now)
    if "deployed_sha" in reached and deploy_age > assertion_slo_minutes():
        for audience, kind in (("public", "failed_public_assertion"),
                               ("authed", "failed_authenticated_assertion")):
            if not _any_pass(assertions, audience) and not _first_failure(assertions, audience):
                failures.append({
                    "kind": kind,
                    "detail": "deployed %.0f min ago (SLO %d) with NO %s route assertion attempted at all"
                              % (deploy_age, assertion_slo_minutes(), audience),
                })

    # Furthest CONTIGUOUS stage. A task with an authed assertion but no merge commit is
    # not "nearly done" — it is incoherent, and reporting the max stage would hide that.
    furthest = None
    for stage in STAGES:
        if stage in reached:
            furthest = stage
        else:
            break

    missing = [s for s in STAGES if s not in reached]
    closed = not missing and not failures

    return {
        "task_id": ev.get("task_id"),
        "slug": ev.get("slug"),
        "project": ev.get("project"),
        "stage": furthest or "none",
        "stages_reached": reached,
        "missing": missing,
        "failures": failures,
        "closed": closed,
        # The single sentence a human reads.
        "statement": _statement(furthest, missing, failures, ev),
        "evidence_links": redact_all([
            ev.get("branch_url"), ev.get("merge_url"), ev.get("release_url"), ev.get("deployment_url"),
        ] + [a.get("evidence_url") for a in assertions if isinstance(a, dict)]),
    }


def _statement(furthest, missing, failures, ev):
    try:
        if not missing and not failures:
            return ("CLOSED: %s is live — merge %s promoted in %s, serving %s, and asserted on both a "
                    "public and an authenticated route."
                    % (ev.get("slug"), redact(ev.get("merge_commit"))[:12],
                       redact(ev.get("release_id")), redact(ev.get("deployed_sha"))[:12]))
        parts = ["NOT CLOSED: %s reached '%s'." % (ev.get("slug"), furthest or "nothing")]
        if failures:
            parts.append(" ".join(f.get("detail", "") for f in failures))
        if missing:
            parts.append("Missing: %s." % ", ".join(missing))
        parts.append("MERGED alone is not done.")
        return " ".join(p for p in parts if p)
    except Exception:
        return "NOT CLOSED: closure could not be evaluated."


# ─── Release-fix task, deduplicated ─────────────────────────────────────────

def release_fix_slug(closure):
    """Deterministic slug so the same unclosed task never opens two fix tasks.

    Keyed on (task slug, failure kinds) rather than on a timestamp: the same task
    failing the same way an hour later is the SAME problem, and a fix task per poll
    cycle is how an alerting channel gets muted.
    """
    try:
        kinds = sorted({f.get("kind", "") for f in (closure or {}).get("failures", [])})
        base = "%s|%s" % ((closure or {}).get("slug") or "", "|".join(kinds))
        digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:10]
        return "relfix-closure-%s" % digest
    except Exception:
        return "relfix-closure-unknown"


class _FixLedger:
    """Thread-safe open-fix registry. Module functions delegate to this singleton.

    Initialised empty at import and populated by `open_release_fix()`. Callers that
    persist fixes elsewhere pass their own open slugs into `open_release_fix(known=...)`;
    the in-process ledger is a second line of defence against a poll loop, not the
    system of record.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._open = {}

    def seen(self, slug):
        with self._lock:
            return slug in self._open

    def add(self, slug, payload):
        with self._lock:
            if slug in self._open:
                return False
            self._open[slug] = payload
            return True

    def close(self, slug):
        with self._lock:
            return self._open.pop(slug, None) is not None

    def open_slugs(self):
        with self._lock:
            return sorted(self._open)

    def clear(self):
        with self._lock:
            self._open.clear()


_ledger = _FixLedger()


def open_fix_slugs():
    return _ledger.open_slugs()


def clear_fix_ledger():
    """Test seam. Not for production callers."""
    _ledger.clear()


def open_release_fix(closure, known=None):
    """Create ONE scoped release-fix task for an unclosed task, or nothing.

    Returns {'created': bool, 'slug': str, 'task': dict|None, 'reason': str}. Never
    raises, and never creates for a closed task.
    """
    try:
        closure = closure or {}
        if closure.get("closed"):
            return {"created": False, "slug": None, "task": None,
                    "reason": "closure is complete; nothing to fix"}
        if not closure.get("failures"):
            return {"created": False, "slug": None, "task": None,
                    "reason": "unclosed but still inside SLO; no failure recorded yet"}

        slug = release_fix_slug(closure)
        if slug in {str(k) for k in (known or [])} or _ledger.seen(slug):
            return {"created": False, "slug": slug, "task": None,
                    "reason": "a release-fix task for this failure signature is already open"}

        kinds = sorted({f.get("kind", "") for f in closure.get("failures", [])})
        task = {
            "slug": slug,
            "kind": "relfix",
            "project": closure.get("project"),
            "parent_slug": closure.get("slug"),
            "failure_kinds": kinds,
            "prompt": _fix_prompt(closure, kinds),
            "evidence_links": closure.get("evidence_links", []),
        }
        _ledger.add(slug, task)
        return {"created": True, "slug": slug, "task": task, "reason": "opened"}
    except Exception:
        return {"created": False, "slug": None, "task": None, "reason": "fail-soft: fix creation errored"}


def _fix_prompt(closure, kinds):
    lines = [
        "Release closure failed for %s. Code merged; the change is not visible in production."
        % closure.get("slug"),
        "",
        "Furthest stage reached: %s (%s)." % (closure.get("stage"),
                                              STAGE_LABEL.get(closure.get("stage"), "unknown")),
        "Missing stages: %s." % (", ".join(closure.get("missing", [])) or "none"),
        "",
        "Failures:",
    ]
    for f in closure.get("failures", []):
        lines.append("  - %s: %s" % (f.get("kind"), f.get("detail")))
    lines += [
        "",
        "SCOPE: fix ONLY the hop that dropped it. Do not re-implement the original change —",
        "it is already merged, and re-implementing it is how a release-fix loop starts",
        "thrashing between resolving A and re-breaking B.",
        "",
        "Do not close the parent task until evaluate_closure() returns closed=True with both",
        "a public and an authenticated route assertion. MERGED alone is not done.",
    ]
    if "wrong_deployed_sha" in kinds:
        lines.append("Start with the deployment: production is serving a SHA that does not contain the merge.")
    if "stale_merge" in kinds:
        lines.append("Start with the release train: the merge never got promoted.")
    return "\n".join(lines)


def report_completion(closure):
    """The one gate the reporting path calls.

    Returns (may_report_complete, reason). A task must NOT be reported complete from
    MERGED alone — that is the entire point of the module, so the negative case is the
    one spelled out.
    """
    try:
        closure = closure or {}
        if closure.get("closed"):
            return True, "all seven stages carry evidence"
        stage = closure.get("stage")
        if stage in ("merge_commit", "train_promoted"):
            return False, ("reached '%s' only. MERGED is not DONE: nothing proves a user can see this."
                           % stage)
        return False, "missing: %s" % (", ".join(closure.get("missing", [])) or "unknown")
    except Exception:
        return False, "fail-soft: closure could not be evaluated, so completion is not reported"
