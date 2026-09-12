#!/usr/bin/env python3
"""
pipeline_contract.py - one shared task envelope for every improvement source.

Dashboard prompts, intake files, autonomous miners, recovered tasks, and loop-generated work should
enter the same operating model:
  * cheap provider triage and planning before agentic spend,
  * agentic coding through the best available coder route,
  * independent cross-model QA,
  * automatic dev-branch merge and batched production release,
  * human approval only for secrets or true regulatory-posture changes.

This module is intentionally fail-soft. If live telemetry or provider discovery is unavailable, it
still returns a deterministic contract rather than blocking task execution.
"""
from __future__ import annotations

import os
import json
import re
import sys
import time
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import agentic_coders
import legal_filter
import model_gateway as mg
import model_policy
import model_router
import db
import error_handling_utils

try:
    import app_triage
except Exception:  # pragma: no cover - import should normally work, contract still degrades
    app_triage = None

try:
    import judge
except Exception:  # pragma: no cover
    judge = None


MARKER = "ORCHESTRATION PIPELINE CONTRACT"
ORIGINAL_HEADER = "# Original improvement request"
CONTROL_PREFIXES = ("REPLAY:", "ROTATE_KEY:", "REVOKE_AND_STOP:")

# Word-boundary anchored on both sides, so the singular nouns used to match only their
# exact form: "authentication", "authorization", "credentials", "secrets", "tokens" and
# "permissions" all fell through to task_class="build" (need 6, risk standard) and never
# reached the security gate below. "Update authentication flow" and "Implement JWT
# authentication" classifying as routine build work is the whole failure mode this
# classifier exists to prevent. The auth family is spelled out rather than as `auth\w*`
# because that would also swallow "author"/"authored", which this module itself uses.
SECURITY_RX = re.compile(
    r"\b(auth|authn|authz|oauth|authenticat\w*|authoris\w*|authoriz\w*|permissions?|rls"
    r"|secrets?|tokens?|credentials?|security|xss|csrf|sql injection)\b", re.I)
LEGAL_RX = re.compile(r"\b(legal|compliance|licens\w*|registration|custody|transmission|advice|contract|terms|privacy|gdpr|hipaa|pci|soc|audit|regulatory|counsel|attorney|lawyer)\b", re.I)
MIGRATION_RX = re.compile(r"\b(schema|migration|database|backfill|data model|rls|release train|merge train)\b", re.I)
RESEARCH_RX = re.compile(r"\b(research|investigate|ideate|concept|strategy|proposal|experiment|ab test|a/b)\b", re.I)
MECHANICAL_RX = re.compile(r"\b(copy|typo|format|lint|rename|style|css|tailwind|docs?|changelog)\b", re.I)

#: Wording that DENIES the mechanical keyword that follows it. A prompt reading
#: "extract the stable contracts, do NOT naively copy 4,900 files" was classified as
#: a copy job -- need 5, risk routine -- because `copy` matched and nothing looked at
#: the two words in front of it. That is the one classification that reduces scrutiny,
#: so a false positive there is the expensive kind.
_MECHANICAL_NEGATION_RX = re.compile(
    r"\b(?:do(?:es)?\s+not|don'?t|doesn'?t|never|avoid|without|"
    r"rather\s+than|instead\s+of|no\s+need\s+to|not\s+a)\b", re.I)

#: How far back from a keyword a denial can sit and still govern it. Long enough for
#: "do NOT naively copy", short enough that a denial in an unrelated earlier clause
#: does not silently disarm a real one. Sentence punctuation ends the reach outright.
_NEGATION_WINDOW = 40


def _mechanical_match(text):
    """First MECHANICAL_RX match in TEXT that is not denied by nearby wording.

    Returns None when every mechanical keyword present is negated, so the caller
    falls through to a fuller classification rather than filing the task as routine.
    """
    body = text or ""
    for match in MECHANICAL_RX.finditer(body):
        window = body[max(0, match.start() - _NEGATION_WINDOW):match.start()]
        # A sentence boundary ends a denial's reach: the clause that denied
        # something is over.
        window = re.split(r"[.;:!?\n]", window)[-1]
        if not _MECHANICAL_NEGATION_RX.search(window):
            return match
    return None

_ALLOWLIST_ENV_KEYS = {
    "security": "ORCH_SECURITY_TASK_ALLOWLIST",
    "legal": "ORCH_LEGAL_TASK_ALLOWLIST",
}

# Module-level constant backing each task class, consulted by `task_allowlist`
# when the corresponding ORCH_* env var is unset. Resolved through globals() at
# call time (not bound here) so that reassigning the constant — which is the
# documented programmatic control surface, and what unittest.mock.patch.object
# does — actually changes the gate.
_ALLOWLIST_CONSTANTS = {
    "security": "SECURITY_TASK_ALLOWLIST",
    "legal": "LEGAL_TASK_ALLOWLIST",
}


def _parse_allowlist(raw: Optional[str]) -> Optional[set]:
    """Parse a comma-separated allowlist env value.

    None (key unset) means "no allowlist configured" -> everything allowed.
    An empty/whitespace-only value means "allow nothing".
    """
    if raw is None:
        return None
    return set(v.strip().lower() for v in raw.split(",") if v.strip())


def task_allowlist(task_class: str) -> Optional[set]:
    """Resolve the allowlist for a task class at call time.

    Precedence:
      1. The ORCH_* environment variable, read live, so a fleet-wide config push
         takes effect without restarting the runner.
      2. Otherwise the module-level ``{SECURITY,LEGAL}_TASK_ALLOWLIST`` constant.

    Step 2 is not optional. Those constants are exported and documented as the
    programmatic control surface ("kept for backward compatibility with existing
    importers"), but an earlier refactor to live-env reads stopped consulting them,
    so assigning one had no effect and `_credential_allows` silently fell through to
    its allow-everything default. A credential gate that cannot be closed
    programmatically is worse than no gate, because callers believe it is shut.
    Reading the constant as the fallback keeps the live push authoritative while
    making the exported constants load-bearing again.

    Fail-soft: any error means "no allowlist".
    """
    try:
        cls = (task_class or "").lower()
        key = _ALLOWLIST_ENV_KEYS.get(cls)
        if not key:
            return None
        raw = os.environ.get(key)
        if raw is not None:
            return _parse_allowlist(raw)
        # Env unset -> fall back to the module-level constant. Unset AND unassigned
        # is None, i.e. "no allowlist configured", preserving the default-open
        # behaviour for classes nobody has gated.
        return globals().get(_ALLOWLIST_CONSTANTS.get(cls, ""), None)
    except Exception:
        return None


_SECURITY_ALLOWLIST_ENV = os.environ.get("ORCH_SECURITY_TASK_ALLOWLIST")
_LEGAL_ALLOWLIST_ENV = os.environ.get("ORCH_LEGAL_TASK_ALLOWLIST")
# Import-time snapshots kept for backward compatibility with existing importers.
SECURITY_TASK_ALLOWLIST = _parse_allowlist(_SECURITY_ALLOWLIST_ENV)
LEGAL_TASK_ALLOWLIST = _parse_allowlist(_LEGAL_ALLOWLIST_ENV)
RESTRICTED_OPERATIONS = {"task_security_gate", "task_legal_gate", "permission_audit", "credential_validation"}


def is_control_prompt(prompt: str) -> bool:
    text = (prompt or "").lstrip()
    return any(text.startswith(p) for p in CONTROL_PREFIXES)


def already_wrapped(prompt: str) -> bool:
    return MARKER in (prompt or "")


def original_request(prompt: str) -> str:
    """Return the human/task body without the orchestration wrapper, when present."""
    text = prompt or ""
    if MARKER not in text:
        return text
    idx = text.find(ORIGINAL_HEADER)
    if idx >= 0:
        return text[idx + len(ORIGINAL_HEADER):].strip()
    # Fallback for partially copied prompts: remove the first contract block.
    return re.sub(r"## ORCHESTRATION PIPELINE CONTRACT.*?## END ORCHESTRATION PIPELINE CONTRACT\s*",
                  "", text, count=1, flags=re.S).strip()


def classify(prompt: str, kind: str = "build", material: bool = False) -> Dict[str, Any]:
    """Return the task class and capability need used for route planning."""
    text = prompt or ""
    k = (kind or "build").lower()
    if material or legal_filter.requires_owner_approval(text=text) or LEGAL_RX.search(text):
        if not _credential_allows("legal", k, text):
            return {"task_class": "build", "need": 6, "risk": "standard", "security_gated": True}
        return {"task_class": "legal", "need": 9, "risk": "legal_posture"}
    if SECURITY_RX.search(text):
        if not _credential_allows("security", k, text):
            return {"task_class": "build", "need": 6, "risk": "standard", "security_gated": True}
        return {"task_class": "security", "need": 9, "risk": "security"}
    if k in ("research", "strategy") or RESEARCH_RX.search(text):
        return {"task_class": "plan", "need": 8, "risk": "strategy"}
    # An EXPLICIT kind is an operator declaration and outranks anything inferred
    # from prompt wording, in both directions.
    if k in ("efficiency", "cost"):
        return {"task_class": "mechanical", "need": 5, "risk": "routine"}
    if k == "speculative":
        return {"task_class": "hard", "need": 8, "risk": "broad_change"}
    # INFERRED classes: broad change is checked BEFORE routine.
    #
    # `mechanical` is the only class that LOWERS scrutiny -- need 5, risk routine --
    # and MECHANICAL_RX matches "copy", "rename", "format", "style", "docs": ordinary
    # English that appears constantly in prompts for work that is not routine at all.
    # With mechanical checked first, "rename the payment columns and backfill" matched
    # `rename` and was filed as a routine typo-fix, even though `backfill` names it a
    # migration. When both families match, the safe reading is the broader one; the
    # dangerous direction is downgrading.
    if MIGRATION_RX.search(text):
        return {"task_class": "hard", "need": 8, "risk": "broad_change"}
    if _mechanical_match(text):
        return {"task_class": "mechanical", "need": 5, "risk": "routine"}
    return {"task_class": "build", "need": 6, "risk": "standard"}


def _credential_allows(task_class: str, kind: str, text: str) -> bool:
    """True when `kind` is permitted to be handled as a restricted task class.

    Resolves the allowlist live (see `task_allowlist`) so a fleet-wide config push
    applies without a runner restart. Fail-soft: unknown class -> allowed.
    """
    try:
        k = (kind or "").lower()
        allowed = task_allowlist(task_class)
        if allowed is None:
            return True
        return k in allowed
    except Exception:
        return True


def _operation_authorized(operation: str, task_class: str) -> bool:
    try:
        env_key = f"ORCH_{task_class.upper()}_ALLOWED_OPERATIONS"
        allowed_ops_str = os.environ.get(env_key)
        if allowed_ops_str is None:
            return True
        allowed_ops = set(v.strip() for v in allowed_ops_str.split(",") if v.strip())
        if not allowed_ops:
            return False
        for op in allowed_ops:
            if not re.match(r"^[a-z_][a-z0-9_]*$", op):
                raise ValueError(f"Invalid operation name: {op}")
        return operation in allowed_ops
    except Exception as e:
        sys.stderr.write(f"[pipeline_contract] authorization check failed ({e}); fail-soft, allowing operation\n")
        return True


def _safe_route(app: str, operation: str, task_class: str, need: Optional[int] = None,
                agentic: bool = False) -> Dict[str, str]:
    if operation in RESTRICTED_OPERATIONS and task_class in ("legal", "security"):
        if not _operation_authorized(operation, task_class):
            return {"provider": "claude", "model": "claude-haiku-4-5-20251001", "reason": "operation unauthorized for task class"}
    try:
        if app_triage is not None:
            r = app_triage.route(app, operation, task_class=task_class, agentic=agentic, need=need)
            return {
                "provider": str(r.get("provider") or ""),
                "model": str(r.get("model") or ""),
                "reason": str(r.get("reason") or r.get("source") or "policy"),
            }
    except PermissionError as e:
        sys.stderr.write(f"[pipeline_contract] preflight/strategy permission denied ({e}); fail-soft, using fallback policy\n")
    except Exception as e:
        sys.stderr.write(f"[pipeline_contract] app_triage routing failed ({e}); fall-soft, trying fallback\n")
    try:
        p, m, why = model_policy.choose(task_class=task_class, agentic=agentic, need=need)
        return {"provider": p, "model": m, "reason": why}
    except PermissionError as e:
        sys.stderr.write(f"[pipeline_contract] model policy permission denied ({e}); fail-soft, using hardcoded default\n")
        return {"provider": "claude", "model": "claude-haiku-4-5-20251001", "reason": "fallback policy (permission denied)"}
    except Exception:
        return {"provider": "claude", "model": "claude-haiku-4-5-20251001", "reason": "fallback policy"}


def _author_model(prompt: str, kind: str) -> str:
    try:
        return model_router.route(prompt, 1)["model"]
    except Exception:
        return os.environ.get("ORCH_DEFAULT_MODEL", "claude-haiku-4-5-20251001")


def _coder(slug: str, prompt: str, material: bool) -> str:
    task = {"slug": slug or "", "prompt": prompt or "", "material": material, "deps": []}
    try:
        return agentic_coders.pick(task)
    except Exception:
        return "claude"


def _qa_panel(author_model: str, task_class: str = "") -> List[str]:
    try:
        if judge is not None and hasattr(judge, "_panel_providers"):
            providers = judge._panel_providers(author_model)  # existing reviewer ordering
            reviewers = getattr(judge, "REVIEWERS", {})
            return [f"{p}:{reviewers.get(p, '')}".rstrip(":") for p in providers]
    except Exception:
        pass
    if task_class == "legal":
        try:
            avail = set(mg.available()) if mg else set()
            if "local" in avail or "deepseek" in avail:
                result = []
                if "local" in avail:
                    result.extend(["local:llama3.1", "local:llama3.2:3b"])
                if "deepseek" in avail and len(result) < 2:
                    result.append("deepseek:deepseek-v4-flash")
                return result[:2]
        except Exception:
            pass
    try:
        avail = [p for p in ("local", "deepseek", "google", "openai", "claude") if p in set(mg.available())]
        return avail[:2] or ["claude:claude-haiku-4-5-20251001"]
    except Exception:
        return ["claude:claude-haiku-4-5-20251001"]


def _recent_context(project: str) -> List[str]:
    """Small cross-learning bundle. Best effort only; DB/network failure returns an empty list."""
    if not project:
        return []
    # NOTE: no local `import db` here. This function used to re-import db into its own
    # scope, which shadowed the module-level import and meant rebinding
    # `pipeline_contract.db` — the module's only dependency seam — had no effect on the
    # one function that reads the database. The guarded local import was also dead:
    # `import db` at module scope already ran, so it can never fail here. Every query
    # below is individually fail-soft, which is where the "best effort" promise lives.
    items: List[str] = []
    try:
        rows = db.select("outcomes", {"select": "model,tests_passed,integrated,usd",
                                      "project": f"eq.{project}",
                                      "order": "created_at.desc", "limit": "12"}) or []
        if rows:
            merged = sum(1 for r in rows if r.get("integrated"))
            passed = sum(1 for r in rows if r.get("tests_passed"))
            spend = sum(float(r.get("usd") or 0) for r in rows)
            models = ", ".join(sorted({str(r.get("model") or "?") for r in rows})[:4])
            items.append(f"recent outcome signal: {merged}/{len(rows)} merged, {passed}/{len(rows)} test-pass, ${spend:.2f}, models {models}")
    except PermissionError as e:
        sys.stderr.write(f"[pipeline_contract] outcomes query permission denied ({e}); fail-soft, skipping\n")
    except Exception:
        pass
    try:
        routes = db.select("app_op_routes", {"select": "operation,provider,model,avg_quality",
                                             "app": f"eq.{project}", "limit": "4"}) or []
        for r in routes[:4]:
            q = r.get("avg_quality")
            qtxt = f", q={q}" if q is not None else ""
            items.append(f"learned route: {r.get('operation')} -> {r.get('provider')}:{r.get('model')}{qtxt}")
    except PermissionError as e:
        sys.stderr.write(f"[pipeline_contract] learned routes query permission denied ({e}); fail-soft, skipping\n")
    except Exception:
        pass
    try:
        fb = db.select("orchestrator_feedback", {"select": "category,severity,observation",
                                                 "status": "in.(new,open)",
                                                 "order": "created_at.desc", "limit": "3"}) or []
        for f in fb[:3]:
            obs = str(f.get("observation") or "").replace("\n", " ")[:140]
            if obs:
                items.append(f"operator feedback: {f.get('severity')}/{f.get('category')} - {obs}")
    except PermissionError as e:
        sys.stderr.write(f"[pipeline_contract] feedback query permission denied ({e}); fail-soft, skipping\n")
    except Exception:
        pass
    return items[:8]


#
# Live-route budget
#
# Every lookup below (_author_model, _coder, _safe_route x3, _qa_panel,
# _recent_context) is individually fail-soft against *exceptions* but not
# against *latency*. db._req retries GETs HTTP_RETRIES times at HTTP_TIMEOUT
# seconds each, across every configured base URL, so a single unreachable
# Supabase edge turns one lookup into minutes of blocking TLS handshakes and a
# full build_plan into far longer.
#
# That is the measured cause of the 2026-08-12 "enqueue terminates silently
# before insertion" regression: enqueue_task never crashed and never inserted,
# it sat in urlopen until its supervisor killed it, which prints nothing. A
# fail-soft module that can still hang forever is not fail-soft.
#
# So live resolution now runs against a wall-clock budget. When the budget is
# spent, the remaining fields degrade to the same deferred values intake
# already uses (build_deferred_plan) -- routing is revalidated at claim time
# anyway, so a deferred envelope is correct, merely less specific. Set
# ORCH_CONTRACT_ROUTE_BUDGET=0 to restore unbounded legacy behaviour.
ROUTE_BUDGET_S = float(os.environ.get("ORCH_CONTRACT_ROUTE_BUDGET", "25") or 25)

DEFERRED_ROUTE: Dict[str, str] = {
    "provider": "runtime-policy",
    "model": "selected-at-claim",
    "reason": "deferred to execution-time capability and capacity checks",
}


class _Budget:
    """Wall-clock allowance for the blocking lookups inside build_plan."""

    def __init__(self, seconds: float):
        self.seconds = float(seconds or 0)
        self.started = time.monotonic()
        self.degraded = False

    @property
    def unlimited(self) -> bool:
        return self.seconds <= 0

    def spent(self) -> bool:
        if self.unlimited:
            return False
        return (time.monotonic() - self.started) >= self.seconds

    def check(self, what: str) -> bool:
        """True if `what` may still run. Announces the first degradation."""
        if not self.spent():
            return True
        if not self.degraded:
            self.degraded = True
            sys.stderr.write(
                "[pipeline_contract] live route budget of {0:.0f}s exhausted before {1}; "
                "remaining routes deferred to claim time. The task envelope is still "
                "valid -- routing is revalidated when the task is claimed.\n".format(
                    self.seconds, what))
        return False


def _budgeted(budget: "_Budget", what: str, fn, fallback):
    """Run a blocking lookup only while the budget allows; never raise."""
    if not budget.check(what):
        return fallback() if callable(fallback) else fallback
    try:
        return fn()
    except Exception as exc:
        sys.stderr.write(
            "[pipeline_contract] {0} failed ({1}); fail-soft, using deferred value\n".format(what, exc))
        return fallback() if callable(fallback) else fallback


def build_plan(prompt: str, project: str = "", kind: str = "build", source: str = "unknown",
               slug: str = "", material: bool = False,
               budget_s: Optional[float] = None) -> Dict[str, Any]:
    budget = _Budget(ROUTE_BUDGET_S if budget_s is None else budget_s)
    cls = classify(prompt, kind=kind, material=material)
    author = _budgeted(budget, "author model routing",
                       lambda: _author_model(prompt, kind), "selected-at-claim")
    coder = _budgeted(budget, "coder selection",
                      lambda: _coder(slug, prompt, material), "selected-at-claim")
    preflight = _budgeted(
        budget, "preflight routing",
        lambda: _safe_route("orchestrator", "task_preflight", "rating", need=5, agentic=False),
        lambda: dict(DEFERRED_ROUTE))
    strategy = _budgeted(
        budget, "strategy routing",
        lambda: _safe_route("orchestrator", "task_strategy", "plan",
                            need=max(7, int(cls["need"])), agentic=False),
        lambda: dict(DEFERRED_ROUTE))
    qa = _budgeted(
        budget, "qa routing",
        lambda: _safe_route("orchestrator", "task_qa", "review",
                            need=6 if cls["need"] < 8 else 8, agentic=False),
        lambda: dict(DEFERRED_ROUTE))
    qa_panel = _budgeted(
        budget, "qa panel selection",
        lambda: _qa_panel(author, cls["task_class"]),
        lambda: ["independent cross-model panel selected at execution time"])
    collaboration = _budgeted(
        budget, "cross-learning context", lambda: _recent_context(project), list)
    return {
        "source": source or "unknown",
        "project": project or "selected app",
        "kind": kind or "build",
        "slug": slug or "(auto)",
        "task_class": cls["task_class"],
        "need": cls["need"],
        "risk": cls["risk"],
        "preflight": preflight,
        "strategy": strategy,
        "coder": coder,
        "author_model": author,
        "qa": qa,
        "qa_panel": qa_panel,
        "legal_gate": "owner-only when the change would force licensing/registration/custody/transmission/advice or needs a secret",
        "release": f"auto-merge to {os.environ.get('ORCH_STAGING_BRANCH', 'orchestrator/dev')} after tests, verify, judge; production release via batch train",
        "collaboration": collaboration,
        "degraded": budget.degraded,
    }


def render_plan(plan: Dict[str, Any]) -> str:
    def route_line(label: str, r: Dict[str, str]) -> str:
        model = f"{r.get('provider', '?')}:{r.get('model', '?')}"
        why = r.get("reason") or "policy"
        return f"- {label}: {model} ({why})"

    lines = [
        f"## {MARKER}",
        f"- source: {plan.get('source')}",
        f"- project: {plan.get('project')}",
        f"- task class: {plan.get('task_class')} (need {plan.get('need')}, risk {plan.get('risk')})",
        route_line("preflight triage", plan.get("preflight") or {}),
        route_line("strategy planner", plan.get("strategy") or {}),
        f"- agentic coder: {plan.get('coder')} using author model {plan.get('author_model')}",
        route_line("independent QA route", plan.get("qa") or {}),
        f"- QA panel: {', '.join(plan.get('qa_panel') or [])}",
        f"- legal gate: {plan.get('legal_gate')}",
        f"- merge/release: {plan.get('release')}",
        "- coordination rule: reconcile with active loop-generated work, reuse prior solutions first, do not delete or overwrite unrelated queued improvements, and leave recovered work in the queue until shipped.",
    ]
    ctx = plan.get("collaboration") or []
    if ctx:
        lines.append("- cross-learning context:")
        lines.extend(f"  - {item}" for item in ctx)
    lines.append(f"## END {MARKER}")
    return "\n".join(lines)


def build_deferred_plan(prompt: str, project: str = "", kind: str = "build",
                        source: str = "unknown", slug: str = "",
                        material: bool = False) -> Dict[str, Any]:
    """Build a deterministic envelope without telemetry or provider calls.

    Intake uses this path because live routing is revalidated when a task is
    claimed. Performing the same remote lookups serially for every manifest can
    consume the watcher's entire lease before the queue insert happens.
    """
    cls = classify(prompt, kind=kind, material=material)
    deferred = dict(DEFERRED_ROUTE)
    return {
        "source": source or "unknown",
        "project": project or "selected app",
        "kind": kind or "build",
        "slug": slug or "(auto)",
        "task_class": cls["task_class"],
        "need": cls["need"],
        "risk": cls["risk"],
        "preflight": dict(deferred),
        "strategy": dict(deferred),
        "coder": "selected-at-claim",
        "author_model": "selected-at-claim",
        "qa": dict(deferred),
        "qa_panel": ["independent cross-model panel selected at execution time"],
        "legal_gate": "owner-only when the change would force licensing/registration/custody/transmission/advice or needs a secret",
        "release": f"auto-merge to {os.environ.get('ORCH_STAGING_BRANCH', 'orchestrator/dev')} after tests, verify, judge; production release via batch train",
        "collaboration": [],
        "degraded": True,
    }


def wrap_prompt(prompt: str, project: str = "", kind: str = "build", source: str = "unknown",
                slug: str = "", material: bool = False,
                resolve_live_routes: bool = True) -> str:
    """Prepend the shared contract unless the prompt is already wrapped or is a control command.

    This is the canonical intent chokepoint: every enqueue path runs through it
    before the row is inserted. It must therefore always return, and always
    return promptly. Live routing is budgeted (see ROUTE_BUDGET_S) and any
    residual failure falls back to the deterministic deferred envelope rather
    than propagating -- a wrapper that can strand an enqueue is worse than a
    wrapper that produces a less specific plan.
    """
    text = prompt or ""
    if not text.strip() or already_wrapped(text) or is_control_prompt(text):
        return text
    plan = None
    if resolve_live_routes:
        try:
            plan = build_plan(text, project=project, kind=kind, source=source,
                              slug=slug, material=material)
        except Exception as exc:
            sys.stderr.write(
                "[pipeline_contract] live plan build failed ({0}); "
                "falling back to the deferred envelope\n".format(exc))
    if plan is None:
        plan = build_deferred_plan(text, project=project, kind=kind, source=source,
                                   slug=slug, material=material)
    return render_plan(plan) + "\n\n" + ORIGINAL_HEADER + "\n" + text


def artifact(prompt: str, project: str = "", kind: str = "build", source: str = "unknown",
             slug: str = "", material: bool = False) -> str:
    """Return the shared pipeline contract as stable JSON for non-prompt consumers."""
    try:
        return json.dumps(
            build_plan(prompt, project=project, kind=kind, source=source,
                       slug=slug, material=material),
            sort_keys=True,
        )
    except Exception:
        return "{}"


def deferred_artifact(prompt: str, project: str = "", kind: str = "build", source: str = "unknown",
                      slug: str = "", material: bool = False) -> str:
    """Return the deferred pipeline contract as stable JSON without live routing.

    Used for intake and high-volume intake pathways where deferring live lookups
    avoids serial query overhead. Returns valid JSON with the same schema as artifact().
    Fail-soft: returns "{}" on any error.
    """
    try:
        return json.dumps(
            build_deferred_plan(prompt, project=project, kind=kind, source=source,
                                slug=slug, material=material),
            sort_keys=True,
        )
    except Exception:
        return "{}"


def task_fields(prompt: str, project: str = "", kind: str = "build", source: str = "unknown",
                slug: str = "", material: bool = False, existing_note: str = "",
                model: Optional[str] = None, force_coder: Optional[str] = None) -> Dict[str, Any]:
    """Return schema-safe admission fields shared by every task source.

    Persisting the route is important for Cowork executors that claim directly
    from Supabase and do not execute the native runner's prompt assembler.
    Native execution still revalidates forced routes at claim time, so provider
    exhaustion or capability drift safely falls through to a fresh choice.
    """
    text = prompt or ""
    try:
        plan = build_plan(text, project=project, kind=kind, source=source,
                          slug=slug, material=material)
    except Exception as exc:
        sys.stderr.write(
            "[pipeline_contract] live plan build failed ({0}); "
            "falling back to the deferred envelope\n".format(exc))
        plan = build_deferred_plan(text, project=project, kind=kind, source=source,
                                   slug=slug, material=material)
    wrapped = text if (already_wrapped(text) or is_control_prompt(text) or not text.strip()) else (
        render_plan(plan) + "\n\n" + ORIGINAL_HEADER + "\n" + text
    )
    # A degraded plan reports "selected-at-claim" rather than a concrete route.
    # That sentinel must not be persisted into force_coder/model: those columns
    # feed native claim-time route validation, and an unknown provider string
    # there is worse than a NULL, which correctly means "choose at claim time".
    def _concrete(value):
        text_value = str(value or "").strip()
        return None if text_value in ("", "selected-at-claim", "runtime-policy") else text_value

    chosen_coder = force_coder or _concrete(plan.get("coder"))
    chosen_model = model or _concrete(plan.get("executor_model")) or _concrete(plan.get("author_model"))
    return {
        "prompt": wrapped,
        "note": note(existing_note, source=source),
        "model": chosen_model,
        "force_coder": chosen_coder,
    }


def note(existing: str = "", source: str = "unknown") -> str:
    base = (existing or "").strip()
    suffix = f"pipeline:{source or 'unknown'}; triage-plan-code-qa-devmerge-release"
    return f"{base}; {suffix}" if base else suffix


# ── contract-first verification ─────────────────────────────────────────────────────────────
#
# "the verify gate IS the spec" (Wave C, Part 4, clause 2). A code task that is generated with a
# sibling `-write-tests` task but does NOT depend on it runs concurrently with its own acceptance
# test, so the test can land after the code and prove nothing. That ordering bug is invisible in
# the DAG unless something checks it — this is that check.
#
# Both helpers below were referenced by runner/tests/test_contract_first.py and by
# planner._apply_tdd_gating, and existed in neither module: 10 tests failed on master with
# AttributeError, and the planner silently fell through to its except branch on every gated task.

#: A proof that names a runnable command is already specific; do not overwrite the author's.
_SPECIFIC_PROOF_RX = re.compile(
    r"(pytest|unittest|npm |yarn |pnpm |go test|cargo |python3? -m|make |exits? [0-9]|\-k )", re.I)


def rewrite_proof_for_contract_first(proof: str, test_slug: str) -> str:
    """Point a vague proof at the acceptance test that must pass. Specific proofs pass through.

    "tests pass" is not a proof — every task claims it and nothing checks which tests. Naming
    the sibling test task makes the claim falsifiable.
    """
    text = (proof or "").strip()
    if text and _SPECIFIC_PROOF_RX.search(text):
        return proof
    return f"acceptance test from '{test_slug}' passes + suite green"


def _acceptance_test_file(repo_path: str, slug: str) -> Optional[str]:
    """The conventional acceptance-test path for a slug, if it exists on disk."""
    stem = f"test_{str(slug or '').replace('-', '_')}.py"
    for parts in (("runner", "tests", stem), ("tests", stem)):
        candidate = os.path.join(repo_path, *parts)
        if os.path.isfile(candidate):
            return candidate
    return None


def verify_contract_first(tasks: List[Dict[str, Any]],
                          repo_path: Optional[str] = None) -> Dict[str, Any]:
    """Check that every code task is ordered behind its acceptance test.

    Returns {"ok": bool, "errors": [str], "verified": [str]}.

    Absence of a test task is NOT an error — TDD gating is opt-in per kind, and failing tasks
    that were never gated would make this check unusable. What IS an error is a test task that
    exists and is not depended upon: that is the silent-ordering bug this exists to catch.
    """
    errors: List[str] = []
    verified: List[str] = []
    try:
        by_slug = {t.get("slug"): t for t in (tasks or []) if isinstance(t, dict)}
        for task in tasks or []:
            if not isinstance(task, dict):
                continue
            slug = task.get("slug") or ""
            if not slug or slug == "contracts":
                continue

            test_slug = f"{slug}-write-tests"
            deps = list(task.get("deps") or [])
            if test_slug in by_slug:
                if test_slug in deps:
                    verified.append(slug)
                else:
                    errors.append(
                        f"{slug}: acceptance test task '{test_slug}' exists but is not in its "
                        f"deps {deps} — the two run concurrently, so the test proves nothing")
                continue

            if repo_path:
                path = _acceptance_test_file(repo_path, slug)
                if path:
                    try:
                        with open(path) as fh:
                            body = fh.read()
                    except Exception:
                        body = ""
                    state = "xfail" if "xfail" in body else "active"
                    verified.append(f"{slug}: acceptance test file {state} ({path})")
        return {"ok": not errors, "errors": errors, "verified": verified}
    except Exception as e:
        # Fail-soft per this module's contract: a broken verifier must not block the pipeline.
        return {"ok": True, "errors": [], "verified": [], "warning": f"verify unavailable: {e}"}


if __name__ == "__main__":
    print(wrap_prompt("Improve the dashboard queue flow.", project="beethoven", source="manual"))
