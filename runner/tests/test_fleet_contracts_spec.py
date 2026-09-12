"""The four SPEC invariants, held to the code that is supposed to satisfy them.

A docstring listing invariants is a comment, and comments do not fail. This
suite makes the list load-bearing in two directions:

  * the prose in the module docstring and the `SPEC_INVARIANTS` data must agree,
    so neither can be edited alone;
  * each invariant is checked against the behaviour it names, so the list cannot
    describe a module that no longer does those things.

The interesting case is invariant 4. `fail-soft-no-crash` and `safe-keys-only`
pull against each other, and the resolution — the security predicate fails
CLOSED rather than fail-soft — is asserted explicitly, because "wrap everything
in fail_soft" is exactly the tidy-looking change that would silently disarm the
guard.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fleet_contracts  # noqa: E402


EXPECTED_SLUGS = [
    "fleet_config-up-to-date",
    "no-hardcoded-secrets",
    "safe-keys-only",
    "fail-soft-no-crash",
]


def test_exactly_four_invariants_are_declared():
    assert list(fleet_contracts.SPEC_INVARIANTS) == EXPECTED_SLUGS


def test_the_docstring_states_every_invariant():
    """The prose and the data must not drift apart."""
    doc = fleet_contracts.__doc__ or ""
    assert "THE FOUR SPEC INVARIANTS" in doc

    for slug in EXPECTED_SLUGS:
        # The docstring numbers them and writes the slug inline, e.g.
        # "3. safe-keys-only — ...".
        assert slug in doc, f"invariant {slug!r} is declared in data but absent from the docstring"


def test_every_invariant_has_a_real_description():
    for slug, text in fleet_contracts.SPEC_INVARIANTS.items():
        assert isinstance(text, str) and len(text.strip()) > 40, slug


def test_describe_carries_the_invariants():
    described = fleet_contracts.describe()
    assert described["spec_invariants"] == dict(fleet_contracts.SPEC_INVARIANTS)

    # describe() must stay a copy: a caller mutating the log payload must not
    # edit the contract other modules read.
    described["spec_invariants"]["fail-soft-no-crash"] = "mutated"
    assert fleet_contracts.SPEC_INVARIANTS["fail-soft-no-crash"] != "mutated"


# ── Invariant 1: fleet_config-up-to-date ────────────────────────────────────

def test_the_contract_is_stated_once_and_is_importable_without_a_cycle():
    schema = fleet_contracts.FLEET_CONFIG_SCHEMA
    assert schema["table"] == "fleet_config"
    assert schema["safe_prefixes"] is fleet_contracts.SAFE_PREFIXES
    assert schema["deny_markers"] is fleet_contracts.DENY_MARKERS

    # No I/O and no control-plane imports, so any module may depend on it.
    source = open(fleet_contracts.__file__, encoding="utf-8").read()
    for forbidden in ("import db", "import fleet_control", "import requests", "import psycopg"):
        assert forbidden not in source, f"fleet_contracts must not {forbidden}"


# ── Invariant 2: no-hardcoded-secrets ───────────────────────────────────────

@pytest.mark.parametrize(
    "key",
    [
        "VERCEL_TOKEN",
        "GITHUB_PAT",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "ORCH_GIT_PAT",
        # The 2026-08-02 shape: a credential wearing a permitted prefix.
        "ORCH_OPENAI_API_KEY",
        "ORCH_SESSION_ID",
    ],
)
def test_credentials_are_refused_whatever_they_wear(key):
    assert fleet_contracts.is_safe_config_key(key) is False


def test_the_module_hardcodes_no_credential_values():
    source = open(fleet_contracts.__file__, encoding="utf-8").read()
    # Marker names are the contract; assignments of a value to one are not.
    for marker in ("TOKEN", "SECRET", "PASSWORD"):
        assert f'{marker} = "' not in source
        assert f"{marker} = '" not in source


# ── Invariant 3: safe-keys-only ─────────────────────────────────────────────

@pytest.mark.parametrize("key", ["ORCH_MAX_TASKS", "MAX_PARALLEL", "RELEASE_WINDOW", "CADE_MODE"])
def test_safe_knobs_are_admitted(key):
    assert fleet_contracts.is_safe_config_key(key) is True


@pytest.mark.parametrize("key", ["", "   ", None, 42, "UNRECOGNISED_KNOB", "random"])
def test_anything_unrecognised_is_refused_rather_than_allowed(key):
    assert fleet_contracts.is_safe_config_key(key) is False


def test_deny_is_checked_before_the_allowlist():
    """Order matters: prefix-first would admit ORCH_OPENAI_API_KEY."""
    assert any("ORCH_OPENAI_API_KEY".startswith(p) for p in fleet_contracts.SAFE_PREFIXES)
    assert fleet_contracts.is_safe_config_key("ORCH_OPENAI_API_KEY") is False


def test_assert_safe_config_key_names_the_contract_when_it_refuses():
    with pytest.raises(ValueError) as excinfo:
        fleet_contracts.assert_safe_config_key("VERCEL_TOKEN")
    assert "FLEET_CONFIG_SCHEMA" in str(excinfo.value)


# ── Invariant 4: fail-soft-no-crash, and where it must NOT apply ────────────

def test_fail_soft_returns_the_default_instead_of_raising():
    @fleet_contracts.fail_soft(default="degraded")
    def boom():
        raise RuntimeError("wedged")

    assert boom() == "degraded"


def test_fail_soft_reports_without_letting_the_reporter_wedge_it():
    seen = []

    @fleet_contracts.fail_soft(default=None, on_error=seen.append)
    def boom():
        raise RuntimeError("x")

    assert boom() is None
    assert len(seen) == 1

    @fleet_contracts.fail_soft(default="still fine", on_error=lambda _: (_ for _ in ()).throw(ValueError()))
    def boom2():
        raise RuntimeError("y")

    # A failing error handler must not resurrect the exception it was handling.
    assert boom2() == "still fine"


def test_the_security_predicate_fails_closed_and_is_not_wrapped():
    """The deliberate exception to invariant 4.

    A guard decorated with fail_soft(default=True) would return permission on
    its own failure. is_safe_config_key returns False instead — for a key whose
    very type makes the check impossible, refusing is the only safe answer.
    """
    assert not hasattr(fleet_contracts.is_safe_config_key, "__wrapped__")

    class Hostile:
        def strip(self):
            raise RuntimeError("boom")

        def __bool__(self):
            return True

    assert fleet_contracts.is_safe_config_key(Hostile()) is False
