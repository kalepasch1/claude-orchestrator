"""fleet_contracts: one declaration of what may go fleet-wide, and it fails closed."""
import subprocess
import sys
from pathlib import Path

import pytest

import fleet_contracts
from fleet_contracts import (
    DENY_MARKERS,
    FLEET_CONFIG_SCHEMA,
    SAFE_PREFIXES,
    assert_safe_config_key,
    fail_soft,
    is_safe_config_key,
)


def test_stated_acceptance_command_exits_zero():
    """The task's literal acceptance check, run as written."""
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-c",
         "import runner.fleet_contracts as c; "
         "assert c.FLEET_CONFIG_SCHEMA and hasattr(c,'is_safe_config_key') "
         "and hasattr(c,'fail_soft')"],
        cwd=repo_root, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr


def test_schema_is_populated_and_declares_fail_closed():
    assert FLEET_CONFIG_SCHEMA
    assert FLEET_CONFIG_SCHEMA["fail_closed"] is True
    assert FLEET_CONFIG_SCHEMA["table"] == "fleet_config"
    assert FLEET_CONFIG_SCHEMA["safe_prefixes"] == SAFE_PREFIXES
    assert FLEET_CONFIG_SCHEMA["deny_markers"] == DENY_MARKERS


@pytest.mark.parametrize("key", [
    "ORCH_MAX_TURNS", "MAX_PARALLEL", "RAM_FLOOR_GB", "MERGE_TRAIN_SCAN_LIMIT",
    "OLLAMA_MODEL", "COMMITTEE_INTERVAL", "CADE_DIMS",
])
def test_secret_free_tuning_knobs_are_allowed(key):
    assert is_safe_config_key(key) is True


@pytest.mark.parametrize("key", [
    "VERCEL_TOKEN", "GITHUB_PAT", "OPENAI_API_KEY", "GEMINI_API_KEY",
    "SUPABASE_SERVICE_KEY", "DB_PASSWORD", "SIGNING_PRIVATE_KEY",
])
def test_the_2026_08_02_incident_keys_are_all_refused(key):
    """These four were stored in plaintext. None may ever be allowed again."""
    assert is_safe_config_key(key) is False


def test_a_deny_marker_beats_a_permitted_prefix():
    """A credential must not smuggle itself in behind an allowed prefix."""
    assert is_safe_config_key("ORCH_OPENAI_API_KEY") is False
    assert is_safe_config_key("ORCH_SESSION_TOKEN") is False
    assert is_safe_config_key("MERGE_SECRET") is False


def test_unknown_keys_fail_closed():
    """Refusing a legitimate knob costs a config change; admitting a credential
    costs a rotation across every provider. The asymmetry decides the default."""
    assert is_safe_config_key("SOMETHING_NEW") is False
    assert is_safe_config_key("") is False
    assert is_safe_config_key(None) is False
    assert is_safe_config_key(123) is False


def test_explicit_exclusions_are_refused_even_though_the_prefix_matches():
    assert "ORCH_GIT_PAT".startswith("ORCH_")
    assert is_safe_config_key("ORCH_GIT_PAT") is False


def test_keys_are_normalised_for_case_and_whitespace():
    assert is_safe_config_key("  orch_max_turns  ") is True
    assert is_safe_config_key("  vercel_token  ") is False


def test_assert_safe_config_key_raises_with_an_actionable_message():
    assert_safe_config_key("ORCH_MAX_TURNS")           # does not raise

    with pytest.raises(ValueError) as excinfo:
        assert_safe_config_key("VERCEL_TOKEN")

    assert "per-machine environment" in str(excinfo.value)


def test_fail_soft_returns_the_default_instead_of_raising():
    @fail_soft(default="degraded")
    def boom():
        raise RuntimeError("kaboom")

    assert boom() == "degraded"


def test_fail_soft_passes_through_a_successful_result_and_preserves_metadata():
    @fail_soft(default=None)
    def add(a, b):
        """adds"""
        return a + b

    assert add(2, 3) == 5
    assert add.__name__ == "add"
    assert add.__doc__ == "adds"


def test_fail_soft_reports_the_error_without_letting_it_escape():
    seen = []

    @fail_soft(default=0, on_error=seen.append)
    def boom():
        raise ValueError("noted")

    assert boom() == 0
    assert isinstance(seen[0], ValueError)


def test_a_raising_on_error_hook_cannot_defeat_fail_soft():
    def bad_hook(_exc):
        raise RuntimeError("the hook is broken too")

    @fail_soft(default="still-soft", on_error=bad_hook)
    def boom():
        raise ValueError("original")

    assert boom() == "still-soft"


def test_the_guard_predicate_is_not_wrapped_in_fail_soft():
    """A security predicate that swallows failure and returns a truthy default
    is how a guard silently stops guarding."""
    assert is_safe_config_key.__name__ == "is_safe_config_key"
    assert getattr(is_safe_config_key, "__wrapped__", None) is None


def test_describe_returns_a_copy_so_the_contract_cannot_be_mutated_in_place():
    described = fleet_contracts.describe()
    described["fail_closed"] = False

    assert FLEET_CONFIG_SCHEMA["fail_closed"] is True


def test_fleet_control_delegates_to_this_contract():
    """The whole point: one declaration, not two that drift."""
    import fleet_control

    assert fleet_control._safe_key("ORCH_MAX_TURNS") is True
    for key in ("VERCEL_TOKEN", "GITHUB_PAT", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        assert fleet_control._safe_key(key) is False
    assert fleet_control._safe_key("ORCH_GIT_PAT") is False, \
        "delegation must carry the explicit exclusion, not just the prefix rule"
