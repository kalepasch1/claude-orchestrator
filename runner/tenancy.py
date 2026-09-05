#!/usr/bin/env python3
"""
tenancy.py — the tenant boundary for fleet execution.

WHAT THIS MODULE IS FOR
-----------------------
Today the fleet is one operator, one portfolio, repos hardcoded in
runner/deployment_bindings.json, and tasks with no owner. Tenancy makes that
portfolio *one* tenant among possible others — which is only safe if a worker
running tenant A's task physically cannot reach tenant B's checkout, credentials
or knowledge store.

So the interesting function here is not `bindings_for()`, it is
`assert_repo_access()`. Everything else exists to make that check possible.

THE ISOLATION RULE, STATED ONCE
-------------------------------
A repo path belongs to exactly one tenant. A task may touch a path only if the
binding that owns it names the task's tenant. Path comparison is done on
`os.path.realpath` so a symlink, a `..` segment or a trailing slash cannot be
used to smuggle tenant B's checkout past a string compare — that is the whole
attack, and it is a one-line mistake to reintroduce.

FAIL-SOFT, BUT NOT FAIL-OPEN
----------------------------
Repo convention here is fail-soft: errors must not wedge the runner. That is
right for *reads* — if the DB is unreachable, `bindings_for()` falls back to the
on-disk seed rather than halting the fleet. It is exactly wrong for the
*isolation check*: a guard that returns "allowed" when it cannot tell is not a
guard. So `assert_repo_access()` denies on error and says why.

Module-level functions delegate to a thread-safe singleton, per repo convention.
"""
import json
import os
import threading
from typing import Any, Dict, List, Optional

_DIR = os.path.dirname(os.path.abspath(__file__))
SEED_MANIFEST = os.path.join(_DIR, "deployment_bindings.json")

#: The existing single-operator portfolio. Rows with no tenant belong to it.
FOUNDING_TENANT = os.environ.get("ORCH_FOUNDING_TENANT", "founding")

#: Set false only in tests that want to prove the DB path is exercised.
ALLOW_SEED_FALLBACK = os.environ.get("ORCH_TENANCY_SEED_FALLBACK", "true") != "false"


def _norm(path: Optional[str]) -> str:
    """Canonical path for comparison. Empty string on anything unusable.

    realpath, not abspath: symlinks are the interesting case. A tenant-B
    checkout symlinked into a tenant-A directory must not compare equal to the
    tenant-A binding.
    """
    if not path or not isinstance(path, str):
        return ""
    try:
        return os.path.realpath(os.path.expanduser(path.strip()))
    except (OSError, ValueError):
        return ""


class _TenancyRegistry:
    """Thread-safe cache of tenant bindings, DB-first with an on-disk seed."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_tenant: Dict[str, List[Dict[str, Any]]] = {}
        self._loaded = False

    # ── loading ────────────────────────────────────────────────────────────

    def _load_seed(self) -> Dict[str, List[Dict[str, Any]]]:
        """The founding tenant's bindings, from the JSON that predates tenancy.

        The file stays on disk on purpose: it is the seed AND the offline
        fallback. The fleet must not lose track of its own repos because the
        control plane blinked.
        """
        try:
            with open(SEED_MANIFEST, "r", encoding="utf-8", errors="replace") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            return {}
        targets = raw.get("targets") if isinstance(raw, dict) else None
        if not isinstance(targets, list):
            return {}
        rows: List[Dict[str, Any]] = []
        for t in targets:
            if not isinstance(t, dict) or not t.get("repo_path"):
                continue
            rows.append({
                "tenant_id": FOUNDING_TENANT,
                "app": t.get("app") or "",
                "repo_path": t.get("repo_path") or "",
                "github_repo": t.get("github_repo") or "",
                "branch": t.get("branch") or "main",
                "vercel_project": t.get("vercel_project"),
                "supabase_project_ref": t.get("supabase_project_ref"),
            })
        return {FOUNDING_TENANT: rows} if rows else {}

    def _load_db(self) -> Dict[str, List[Dict[str, Any]]]:
        """Bindings from tenant_deployment_bindings. Empty dict on any failure.

        Imported lazily: this module is imported by tests and tooling that have
        no database, and an import-time dependency would make it unusable there.
        """
        try:
            import db  # type: ignore
            rows = db.select("tenant_deployment_bindings", {}) or []
        except Exception:  # noqa: BLE001 — fail-soft read, seed covers us
            return {}
        out: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            if not isinstance(r, dict):
                continue
            tid = r.get("tenant_id")
            if not tid or not r.get("repo_path"):
                continue
            out.setdefault(tid, []).append(dict(r))
        return out

    def _ensure(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            data = self._load_db()
            if not data and ALLOW_SEED_FALLBACK:
                data = self._load_seed()
            elif ALLOW_SEED_FALLBACK:
                # DB is authoritative, but a founding tenant absent from it
                # still resolves from the seed rather than silently vanishing.
                for tid, rows in self._load_seed().items():
                    data.setdefault(tid, rows)
            self._by_tenant = data
            self._loaded = True

    # ── queries ────────────────────────────────────────────────────────────

    def bindings_for(self, tenant_id: Optional[str]) -> List[Dict[str, Any]]:
        self._ensure()
        return list(self._by_tenant.get(tenant_id or FOUNDING_TENANT, []))

    def tenant_of_repo(self, repo_path: Optional[str]) -> Optional[str]:
        self._ensure()
        want = _norm(repo_path)
        if not want:
            return None
        for tid, rows in self._by_tenant.items():
            for r in rows:
                if _norm(r.get("repo_path")) == want:
                    return tid
        return None

    def invalidate(self) -> None:
        with self._lock:
            self._by_tenant = {}
            self._loaded = False

    def stats(self) -> Dict[str, Any]:
        self._ensure()
        return {
            "tenants": len(self._by_tenant),
            "bindings": sum(len(v) for v in self._by_tenant.values()),
            "loaded": self._loaded,
        }


_registry = _TenancyRegistry()


# ── module-level API ───────────────────────────────────────────────────────

def bindings_for(tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Deployment bindings visible to `tenant_id`. Never raises."""
    return _registry.bindings_for(tenant_id)


def tenant_of_repo(repo_path: Optional[str]) -> Optional[str]:
    """Which tenant owns `repo_path`, or None if no binding claims it."""
    return _registry.tenant_of_repo(repo_path)


def resolve_repo(tenant_id: Optional[str], app: Optional[str]) -> Optional[Dict[str, Any]]:
    """The binding for `app` WITHIN `tenant_id`. None if the tenant has no such app.

    Scoped deliberately: a global app->repo lookup is how a worker ends up in
    another tenant's checkout without anyone writing a line of malicious code.
    """
    if not app:
        return None
    for r in bindings_for(tenant_id):
        if r.get("app") == app:
            return dict(r)
    return None


def assert_repo_access(tenant_id: Optional[str], repo_path: Optional[str]) -> Dict[str, Any]:
    """The isolation gate. Returns {'allowed': bool, 'reason': str}.

    DENIES on anything it cannot positively confirm — unknown path, unknown
    tenant, mismatch. A guard that says "allowed" when it does not know is not a
    guard, so this is the one place in the module that is not fail-soft.
    """
    tid = tenant_id or FOUNDING_TENANT
    want = _norm(repo_path)
    if not want:
        return {"allowed": False, "reason": "repo_path missing or unresolvable"}

    owner = tenant_of_repo(want)
    if owner is None:
        return {
            "allowed": False,
            "reason": f"no deployment binding claims {want}; unclaimed paths are not accessible",
        }
    if owner != tid:
        return {
            "allowed": False,
            "reason": f"repo belongs to tenant '{owner}', task runs as tenant '{tid}'",
        }
    return {"allowed": True, "reason": ""}


def assert_task_repo_access(task: Optional[Dict[str, Any]], repo_path: Optional[str]) -> Dict[str, Any]:
    """`assert_repo_access` for a task dict. A task with no tenant is founding."""
    tid = (task or {}).get("tenant_id") or FOUNDING_TENANT
    return assert_repo_access(tid, repo_path)


def knowledge_root(tenant_id: Optional[str] = None) -> str:
    """Per-tenant knowledge directory.

    The founding tenant keeps the EXISTING path so nothing it has already
    learned moves; every other tenant gets a subdirectory. Sharing one knowledge
    store across tenants would leak one org's learnings into another's prompts,
    which is the quietest possible cross-tenant leak.
    """
    home = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
    base = os.path.join(home, "knowledge")
    tid = tenant_id or FOUNDING_TENANT
    return base if tid == FOUNDING_TENANT else os.path.join(base, "tenants", tid)


def invalidate() -> None:
    """Drop the cache; next call reloads from DB then seed."""
    _registry.invalidate()


def stats() -> Dict[str, Any]:
    """Observability for operators and tests."""
    return _registry.stats()
