"""A constant returning a constant is what a constant IS.

smarter/packages/corpus-lattice/src/admit.ts:49 is

    export const REPLACEMENT_MARGIN = 0.01

with a nine-line comment above it explaining why it is not zero. stub_guard's _CRITICAL
pattern is case-insensitive, so its domain suffix `Margin` matched `..._MARGIN`, and the
structural pass saw an export whose body is a constant:

    REGRESSFAIL — SILENT STUB / SHADOWED RE-EXPORT
    [fabricated_critical_return] packages/corpus-lattice/src/admit.ts:49::REPLACEMENT_MAR

That finding is BLOCKING, so it quarantined every smarter candidate that came near the
package. On the evening of 2026-09-01 four unrelated cards were rejected for that one
line, and not one of them had touched it:

    dropbox-v5-final-additions-sm-3-leave-timing-optimizer-...  QUARANTINED
    chatgpt-local-reconcile-smarter-f2b5f51f2471               repair 1/2
    dropbox-smarter-embeddable-core-apparently-pareto-slice-1  QUARANTINED
    dropbox-v5-final-additions-sm-3-... (again)                QUARANTINED

The lane cannot clear while a declaration in the BASE trips the gate on every candidate.

The guard's own argument is an argument about FUNCTIONS: "its NAME promises a
computation, so a constant body means the check no longer runs". SCREAMING_SNAKE_CASE in
TS/JS names a value, never a function, by universal convention. So a SCREAMING_SNAKE
export bound to something with no `function`, no arrow and no `class` is exempt — and
nothing else is, which is what most of these tests are about.
"""
import os
import subprocess
import sys

import pytest

import stub_guard


def _stubs(tmp_path, name, source):
    p = tmp_path / f"{name}.ts"
    p.write_text(source + "\n", encoding="utf-8")
    found = stub_guard._structural_stubs(str(p), source + "\n")
    return [s for s, _ in found if stub_guard.is_critical_name(s)]


@pytest.mark.parametrize("name,source", [
    ("REPLACEMENT_MARGIN", "export const REPLACEMENT_MARGIN = 0.01"),
    ("MAX_FEE", "export const MAX_FEE = 250"),
    ("DEFAULT_MARGIN", "export const DEFAULT_MARGIN = 0"),
    ("SETTLEMENT", "export const SETTLEMENT = 'T+2'"),
])
def test_a_named_constant_is_not_a_fabricated_return(tmp_path, name, source):
    assert _stubs(tmp_path, name, source) == []


@pytest.mark.parametrize("name,source", [
    ("computePrice", "export const computePrice = 0"),
    ("calculateFee", "export const calculateFee = () => 0"),
    ("assertEcpCounterparty", "export function assertEcpCounterparty(x: any) { return true; }"),
    ("validateMargin", "export const validateMargin = () => true"),
])
def test_a_stubbed_function_is_still_caught(tmp_path, name, source):
    """The teeth. These are the shapes the guard was written for and they must survive."""
    assert _stubs(tmp_path, name, source) == [name], (
        f"{name} is no longer reported — the exemption is too wide"
    )


def test_a_screaming_snake_name_bound_to_an_arrow_is_still_caught(tmp_path):
    """The exemption is about VALUES. A constant holding a function is not one.

    Someone can write `export const COMPUTE_FEE = () => 0`, and the convention argument
    does not cover it, so neither does the exemption.
    """
    assert _stubs(tmp_path, "COMPUTE_FEE", "export const COMPUTE_FEE = () => 0") == ["COMPUTE_FEE"]


@pytest.mark.parametrize("slice_text", ["= () => 0", "= function () { return 0 }",
                                        "= class Foo {}"])
def test_callables_are_never_treated_as_named_constants(slice_text):
    assert stub_guard._is_named_constant("SOME_MARGIN", slice_text) is False


@pytest.mark.parametrize("name", ["computePrice", "camelCase", "Mixed_Case", "lower_snake",
                                  "", None])
def test_only_screaming_snake_names_qualify(name):
    assert stub_guard._is_named_constant(name, "= 0.01") is False


def test_the_real_file_from_the_incident_is_clean():
    """The regression pin, read from the actual repository if it is on this machine."""
    repo = os.path.expanduser("~/Documents/smarter")
    rel = "packages/corpus-lattice/src/admit.ts"
    if not os.path.isdir(os.path.join(repo, ".git")):
        pytest.skip("smarter is not checked out on this host")
    got = subprocess.run(["git", "-C", repo, "show", f"origin/orchestrator/dev:{rel}"],
                         capture_output=True, text=True, timeout=60)
    if got.returncode != 0 or "REPLACEMENT_MARGIN" not in got.stdout:
        pytest.skip("that revision of admit.ts is not available here")
    flagged = [s for s, _ in stub_guard._structural_stubs(rel, got.stdout)
               if stub_guard.is_critical_name(s)]
    assert flagged == [], (
        f"admit.ts still trips the stub guard on {flagged} — every smarter candidate "
        "touching that package is quarantined again"
    )
