"""Household passport mesh: `guardian_of` edges over HouseholdPassport.

The mesh answers one question — "does A hold authority over B?" — from the
`guardian_of` edges on each passport. Every other module here gates its
transitions on that answer, so this module decides the blast radius of the
whole package.

Two rules, both load-bearing:

* **Authority fails CLOSED.** An unknown member, a malformed graph, a cycle,
  or any error resolves to *no authority*. There is no path through this
  module that grants authority by accident.
* **Malformed graphs fail SOFT.** A passport that is None, the wrong type, or
  carries a non-list `guardian_of` is skipped with a warning; it never raises
  into the caller and never poisons the rest of the graph.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any, Iterable

log = logging.getLogger(__name__)

#: Depth cap for guardian chains. Also the cycle backstop.
MAX_CHAIN_DEPTH = int(os.environ.get("PARETO_MESH_MAX_DEPTH", "16") or 16)

#: Authority types a passport may declare.
AUTHORITY_MEMBER = "member"
AUTHORITY_GUARDIAN = "guardian"
AUTHORITY_DEPENDENT = "dependent"


def _load_contracts_module():
    """Import `pareto/2080/contracts/autonomy.py`, or return None.

    '2080' is not a valid Python identifier, so this package cannot be reached
    by dotted path. Follows the repo convention (contracts/test_contracts_smoke.py,
    household_legal/regime_consumer.py): put the directory on sys.path and
    import by bare name.
    """
    try:
        contracts_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contracts"
        )
        if contracts_dir not in sys.path:
            sys.path.insert(0, contracts_dir)
        import autonomy  # noqa: PLC0415  (deliberately late and guarded)

        return autonomy
    except Exception as exc:  # pragma: no cover - import-environment specific
        log.warning("mesh: contracts unavailable (%s); degrading to duck-typing", exc)
        return None


_contracts = _load_contracts_module()


def make_passport(
    household_id: str = "",
    member_id: str = "",
    guardian_of: Iterable[str] | None = None,
    authority_type: str = AUTHORITY_MEMBER,
    mesh_roles: Iterable[str] | None = None,
) -> Any:
    """Build a HouseholdPassport from the contracts module.

    Falls back to a duck-typed shim if contracts could not be imported, so the
    mesh stays usable in a stripped environment.
    """
    wards = list(guardian_of or [])
    roles = list(mesh_roles or [])
    if _contracts is not None and hasattr(_contracts, "HouseholdPassport"):
        return _contracts.HouseholdPassport(
            household_id=household_id,
            member_id=member_id,
            guardian_of=wards,
            authority_type=authority_type,
            mesh_roles=roles,
        )

    class _Passport:  # pragma: no cover - only without contracts
        pass

    p = _Passport()
    p.household_id = household_id
    p.member_id = member_id
    p.guardian_of = wards
    p.authority_type = authority_type
    p.mesh_roles = roles
    return p


def _valid_passport(passport: Any) -> bool:
    """True only for a passport with a usable member_id and guardian_of list."""
    if passport is None:
        return False
    member_id = getattr(passport, "member_id", None)
    if not isinstance(member_id, str) or not member_id.strip():
        return False
    wards = getattr(passport, "guardian_of", None)
    return isinstance(wards, (list, tuple))


def _wards(passport: Any) -> list[str]:
    """Non-empty string wards declared by ``passport``."""
    out: list[str] = []
    for w in getattr(passport, "guardian_of", None) or []:
        if isinstance(w, str) and w.strip():
            out.append(w.strip())
    return out


def build_mesh(passports: Iterable[Any]) -> dict[str, list[str]]:
    """Build the ``member_id -> wards`` adjacency map.

    Malformed entries are skipped with a warning (fail soft). Duplicate
    member_ids merge rather than overwrite, so a split passport cannot silently
    drop guardianship edges.
    """
    mesh: dict[str, list[str]] = {}
    try:
        candidates = list(passports or [])
    except TypeError:
        log.warning("mesh: passports not iterable; treating as empty")
        return {}

    for passport in candidates:
        if not _valid_passport(passport):
            log.warning("mesh: skipping malformed passport %r", passport)
            continue
        member_id = getattr(passport, "member_id").strip()
        existing = mesh.setdefault(member_id, [])
        for ward in _wards(passport):
            if ward not in existing:
                existing.append(ward)
    return mesh


def guardians_of(passports: Iterable[Any], member_id: str) -> list[str]:
    """Direct guardians of ``member_id``, sorted. Empty on any problem."""
    if not isinstance(member_id, str) or not member_id.strip():
        return []
    target = member_id.strip()
    mesh = build_mesh(passports)
    return sorted(m for m, wards in mesh.items() if target in wards and m != target)


def wards_of(passports: Iterable[Any], member_id: str) -> list[str]:
    """Direct wards of ``member_id``, sorted. Empty on any problem."""
    if not isinstance(member_id, str) or not member_id.strip():
        return []
    return sorted(build_mesh(passports).get(member_id.strip(), []))


def has_authority_over(
    passports: Iterable[Any], guardian_id: str, member_id: str
) -> bool:
    """Does ``guardian_id`` hold authority over ``member_id``?

    Walks guardian_of edges transitively (a grandparent who is guardian of a
    parent who is guardian of a child holds authority over the child).

    FAILS CLOSED: returns False for blank ids, self-authority, an unknown
    guardian, a cycle, a chain deeper than :data:`MAX_CHAIN_DEPTH`, or any
    unexpected error.
    """
    try:
        if not isinstance(guardian_id, str) or not isinstance(member_id, str):
            return False
        g, m = guardian_id.strip(), member_id.strip()
        if not g or not m or g == m:
            return False

        mesh = build_mesh(passports)
        if g not in mesh:
            return False

        seen: set[str] = {g}
        frontier = list(mesh.get(g, []))
        for _ in range(MAX_CHAIN_DEPTH):
            if not frontier:
                return False
            if m in frontier:
                return True
            nxt: list[str] = []
            for node in frontier:
                if node in seen:
                    continue  # cycle backstop
                seen.add(node)
                nxt.extend(mesh.get(node, []))
            frontier = nxt
        log.warning("mesh: guardian chain from %s exceeded max depth; denying", g)
        return False
    except Exception as exc:
        log.warning("mesh: authority check failed (%s); denying", exc)
        return False
