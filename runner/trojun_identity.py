#!/usr/bin/env python3
"""Canonical Trojun identity, with Illuminati preserved as a live alias.

The rename is half-done across the orchestrator: ``common_brain`` already keys
on ``trojun`` and lists ``illuminati`` as an alias, ``hivemind_v15`` maps the
alias, and ``codex_reconciler`` knows the pair -- but ``db.PROJECT_PRIORITY_ORDER``
still keys only on the legacy name, so a task attributed to ``trojun`` sorts as
an unknown project.  This module is the single declaration of the mapping and
the idempotent migration that closes those gaps.

Two constraints from the brief shape everything here:

* **Backwards compatibility is permanent, not transitional.**  Existing database
  project ids, API clients, URLs and already-queued tasks keep working, because
  the alias is never removed -- :func:`canonical` accepts both names forever and
  both resolve to the SAME value.  A rename that breaks queued work is an outage.
* **Immutable history is never rewritten.**  Recovery ledgers, processed intake,
  reports and incident post-mortems say "illuminati" because that is what it was
  called when they were written.  Rewriting them would falsify the record, so
  :func:`is_immutable_path` refuses those paths outright and
  :func:`rewritable_paths` filters them out of any migration plan.

Hostname retirement is gated separately: :func:`hostname_retirement` will not
authorise retiring a working legacy hostname until a durable replacement has
actually been provisioned and observed healthy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

CANONICAL = "trojun"
LEGACY_ALIASES: Tuple[str, ...] = ("illuminati", "cross-app-intelligence")

#: Paths whose contents are a historical record.  Never rewritten by a rename.
IMMUTABLE_PREFIXES: Tuple[str, ...] = (
    "intake/processed/",
    "docs/recovery/",
    "docs/recovery-ledger/",
    "reports/",
    "tasks/",
    ".orch/",
)


class RetirementBlocked(RuntimeError):
    """A legacy hostname cannot be retired yet, and here is why."""


def canonical(name: Optional[str]) -> str:
    """Map any known spelling to the canonical project name.

    Unknown names are returned normalised rather than coerced to Trojun: this
    function resolves an identity, it does not claim ownership of every project.
    """
    if not name:
        return ""
    normalised = str(name).strip().lower()
    if normalised == CANONICAL or normalised in LEGACY_ALIASES:
        return CANONICAL
    return normalised


def is_legacy(name: Optional[str]) -> bool:
    return bool(name) and str(name).strip().lower() in LEGACY_ALIASES


def all_names() -> Tuple[str, ...]:
    """Every accepted spelling, canonical first."""
    return (CANONICAL,) + LEGACY_ALIASES


def is_immutable_path(path: str) -> bool:
    """True for paths that record history and must not be rewritten.

    ``lstrip("./")`` would be wrong here: it strips CHARACTERS, not a prefix, so
    ``.orch/ledger.json`` becomes ``orch/ledger.json`` and stops matching the
    very prefix that protects it.  A history guard that silently declassifies
    dot-directories is worse than none.
    """
    normalised = str(path)
    while normalised.startswith("./"):
        normalised = normalised[2:]
    return any(normalised.startswith(prefix) for prefix in IMMUTABLE_PREFIXES)


def rewritable_paths(paths: Iterable[str]) -> List[str]:
    """Filter a candidate rename set down to files that may legitimately change."""
    return [p for p in paths if not is_immutable_path(p)]


# -- registry migration --------------------------------------------------
@dataclass
class MigrationPlan:
    """What the migration would do.  Empty ``changes`` means already migrated."""

    changes: Dict[str, Any] = field(default_factory=dict)
    unchanged: List[str] = field(default_factory=list)
    skipped_immutable: List[str] = field(default_factory=list)

    @property
    def is_noop(self) -> bool:
        return not self.changes


def plan_registry_migration(registry: Mapping[str, Any]) -> MigrationPlan:
    """Plan the additive registry change without applying it.

    The migration is purely ADDITIVE: the canonical key is added carrying the
    legacy value, and the legacy key stays.  Nothing is removed, so a client
    still sending the old name is unaffected.
    """
    plan = MigrationPlan()
    legacy_present = [a for a in LEGACY_ALIASES if a in registry]
    if not legacy_present:
        return plan
    legacy_value = registry[legacy_present[0]]
    if CANONICAL in registry:
        # Already migrated, or someone set a different value deliberately.
        # Either way it is not ours to overwrite.
        plan.unchanged.append(CANONICAL)
        return plan
    plan.changes[CANONICAL] = legacy_value
    return plan


def migrate_registry(registry: Dict[str, Any], apply: bool = True) -> MigrationPlan:
    """Idempotent: running it twice makes no further change.

    Returns the plan either way, so a caller can dry-run first and get exactly
    the same answer the apply pass will act on.
    """
    plan = plan_registry_migration(registry)
    if apply and plan.changes:
        registry.update(plan.changes)
    return plan


def rollback_registry(registry: Dict[str, Any]) -> MigrationPlan:
    """Remove ONLY the canonical key this migration added.

    Legacy keys are never touched, so a rollback cannot break the clients the
    migration was designed to protect.
    """
    plan = MigrationPlan()
    legacy_present = [a for a in LEGACY_ALIASES if a in registry]
    if CANONICAL in registry and legacy_present:
        if registry[CANONICAL] == registry[legacy_present[0]]:
            plan.changes[CANONICAL] = registry.pop(CANONICAL)
        else:
            plan.unchanged.append(CANONICAL)   # not the value we added
    return plan


def resolve_priority(registry: Mapping[str, Any], name: str, default: Any = None) -> Any:
    """Look a project up under either spelling.

    This is the compatibility shim that makes the registry gap harmless even
    before the migration runs: today ``PROJECT_PRIORITY_ORDER`` has no
    ``trojun`` key, so a task attributed to the canonical name would otherwise
    sort as an unknown project.
    """
    if name in registry:
        return registry[name]
    canonical_name = canonical(name)
    if canonical_name in registry:
        return registry[canonical_name]
    if canonical_name == CANONICAL:
        for alias in LEGACY_ALIASES:
            if alias in registry:
                return registry[alias]
    return default


# -- hostname retirement -------------------------------------------------
@dataclass(frozen=True)
class HostnameState:
    legacy: str
    durable: Optional[str] = None
    durable_provisioned: bool = False
    durable_healthy: bool = False
    legacy_serving: bool = True


def hostname_retirement(state: HostnameState) -> Dict[str, Any]:
    """May the legacy hostname be retired yet?

    Fails CLOSED.  A working hostname is load-bearing for API clients and links
    this module cannot enumerate, so it stays until a durable replacement is
    provisioned AND observed healthy through the existing release train.
    """
    blockers: List[str] = []
    if not state.durable:
        blockers.append("no durable Trojun hostname is declared")
    if not state.durable_provisioned:
        blockers.append("durable hostname is not provisioned through the release train")
    if not state.durable_healthy:
        blockers.append("durable hostname has not been observed healthy")
    return {
        "legacy": state.legacy,
        "durable": state.durable,
        "may_retire": not blockers,
        "blockers": blockers,
        "note": ("a working hostname is retired only after its replacement is "
                 "provisioned and healthy; this check fails closed"),
    }


def require_retirement_allowed(state: HostnameState) -> None:
    decision = hostname_retirement(state)
    if not decision["may_retire"]:
        raise RetirementBlocked("; ".join(decision["blockers"]))


# -- telemetry / attribution ---------------------------------------------
def telemetry_dimension(name: Optional[str]) -> Dict[str, Any]:
    """Canonical telemetry dimension that still records what was sent.

    Emitting only the canonical name would make a dashboard lie about which
    clients are still using the old one, and that signal is exactly what tells
    an operator when the alias is finally safe to reconsider.
    """
    raw = (str(name).strip().lower() if name else "")
    return {"project": canonical(raw), "project_reported": raw,
            "used_legacy_alias": is_legacy(raw)}


def attribute_queue_row(row: Mapping[str, Any], key: str = "project") -> Dict[str, Any]:
    """Normalise a queued task's project without mutating the original row."""
    out = dict(row)
    out[key] = canonical(row.get(key))
    out["project_reported"] = str(row.get(key) or "").strip().lower()
    return out
