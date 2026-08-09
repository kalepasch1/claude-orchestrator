"""PROPRIETARY -- Apparently Inc. Trade Secret. Protected under DTSA (18 U.S.C. 1836).

Scope + named-test-executed gates for the orchestrator DoD.

Two objective, zero-token machine-checked gates the manual loop lacks:
  1. symbol-scope: the proof test must reference the changed symbol, and the
     diff must not touch files outside the task's declared scope (no drift).
  2. named-test-executed: the proof run must show the *named* test actually
     collected AND passed -- closing the "0 tests collected, exit 0 = green" hole.
Pure functions; unit-tested without git or a test runner.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Mapping, Sequence


@dataclass
class ScopeResult:
    passed: bool
    reasons: List[str] = field(default_factory=list)
    out_of_scope: List[str] = field(default_factory=list)


def _in_scope(path: str, scope: Sequence[str]) -> bool:
    for s in scope:
        s = s.rstrip("/")
        if path == s or path.startswith(s + "/"):
            return True
    return False


def files_out_of_scope(changed_files: Sequence[str], declared_scope: Sequence[str]) -> List[str]:
    """Files in the diff that fall outside every declared-scope prefix."""
    if not declared_scope:
        return []  # no declared scope => scope check not enforced
    return [f for f in changed_files if not _in_scope(f, declared_scope)]


def references_changed_symbol(proof_test_source: str, changed_symbol: str) -> bool:
    """The proof test must mention the changed symbol, or it proves nothing about it."""
    if not changed_symbol:
        return True
    return changed_symbol in (proof_test_source or "")


def named_test_executed(report: Mapping[str, int]) -> bool:
    """A green exit is not enough: the named test must have been collected and passed,
    with zero failures/errors. Defends against '0 tests collected, exit 0'."""
    collected = int(report.get("collected", 0) or 0)
    passed = int(report.get("passed", 0) or 0)
    failed = int(report.get("failed", 0) or 0)
    errors = int(report.get("errors", 0) or 0)
    return collected > 0 and passed > 0 and failed == 0 and errors == 0


def assess_scope(
    changed_files: Sequence[str],
    declared_scope: Sequence[str],
    proof_test_source: str,
    changed_symbol: str,
    proof_report: Mapping[str, int],
) -> ScopeResult:
    reasons: List[str] = []
    oos = files_out_of_scope(changed_files, declared_scope)
    if oos:
        reasons.append("diff touches files outside declared scope: " + ", ".join(oos))
    if not references_changed_symbol(proof_test_source, changed_symbol):
        reasons.append(f"proof test does not reference the changed symbol '{changed_symbol}'")
    if not named_test_executed(proof_report):
        reasons.append("named proof test did not demonstrably collect+pass (possible 0-collected/spoofed green)")
    return ScopeResult(passed=(len(reasons) == 0), reasons=reasons, out_of_scope=oos)
