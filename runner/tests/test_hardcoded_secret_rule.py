"""Regression: Rule 2 (HARDCODED_SECRET) must key off the target NAME.

Two defects made this rule nearly inert:

1. The whole check was gated on the assigned *value* starting with a vendor prefix
   ("sk-", "api-", …). A plain literal — `db_password = "hunter2"`,
   `private_key = "-----BEGIN PRIVATE KEY-----"` — was never inspected at all, which
   is exactly the shape CLAUDE.md's "no hardcoded secrets" rule exists to stop.
2. This module emitted the finding as NO_HARDCODED_SECRETS while CONVENTION_LINT.md
   and tools/convention_linter.py (the pre-commit linter) both use HARDCODED_SECRET,
   so one rule was filed under two ids and the documented `# noqa: HARDCODED_SECRET`
   suppression did not match.
"""
import ast
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

from lint_conventions import (  # noqa: E402
    RULE_HARDCODED_SECRET,
    ConventionChecker,
)


def _secret_violations(code):
    checker = ConventionChecker("test.py")
    checker.visit(ast.parse(code))
    return [v for v in checker._v2_violations if v.rule == RULE_HARDCODED_SECRET]


def test_rule_id_matches_documented_name():
    """CONVENTION_LINT.md and tools/convention_linter.py both say HARDCODED_SECRET."""
    assert RULE_HARDCODED_SECRET == "HARDCODED_SECRET"


def test_plain_password_literal_is_flagged():
    """The value has no vendor prefix — it was previously invisible."""
    assert len(_secret_violations('db_password = "hunter2"')) == 1


def test_private_key_literal_is_flagged():
    assert len(_secret_violations('private_key = "-----BEGIN PRIVATE KEY-----"')) == 1


def test_config_subscript_secret_is_flagged():
    assert len(_secret_violations('config["DATABASE_PASSWORD"] = "prod-secret"')) == 1


def test_vendor_prefixed_literal_flagged_regardless_of_name():
    """A leaked `sk-…` is a credential even under an innocuous name."""
    assert len(_secret_violations('endpoint = "sk-live-abcdef123456"')) == 1


def test_env_indirection_is_not_flagged():
    assert _secret_violations('api_token = os.environ.get("API_TOKEN")') == []
    assert _secret_violations('api_token = os.environ["API_TOKEN"]') == []


def test_placeholders_are_not_flagged():
    for literal in ('"${API_TOKEN}"', '"$API_TOKEN"', '"{{ api_token }}"',
                    '"<your-token-here>"', '"%(token)s"', '""'):
        code = f"api_token = {literal}"
        assert _secret_violations(code) == [], f"{literal} should be treated as indirection"


def test_non_secret_names_are_not_flagged():
    assert _secret_violations('base_url = "https://example.com"') == []
    assert _secret_violations('greeting = "hello"') == []


def test_kv_namespace_constants_are_not_flagged():
    """Bare "key"/"pat" made every cache-namespace constant a false positive."""
    for code in ('_ALERT_KEY = "cade_firstpass"',
                 'PRESSURE_KEY = "fleet_pressure"',
                 'STATE_KEY = "knob_tuner_state"',
                 'REL_PATH = "runner/foulkon"',
                 'GENERATED_TASKS_PATH = ".runtime/generated.json"',
                 '_PATTERNS = "abc"'):
        assert _secret_violations(code) == [], f"{code} must not be a secret finding"


def test_reason_code_sentinels_are_not_flagged():
    """fleet_control classifies *why* a key was ignored; the marker is not a secret."""
    assert _secret_violations('IGNORE_CREDENTIAL = "credential-marker"') == []
    assert _secret_violations('IGNORE_UNSAFE_KEY = "not-a-safe-key"') == []


def test_name_referring_to_a_secret_is_not_the_secret():
    """`token_env`/`api_key_name` hold the *name* of a variable, not its value."""
    assert _secret_violations('api_token_env = "ANTHROPIC_API_KEY"') == []
    assert _secret_violations('secret_file = "/etc/creds.json"') == []


if __name__ == "__main__":
    import traceback

    failures = 0
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_") and callable(_fn):
            try:
                _fn()
                print(f"ok   {_name}")
            except AssertionError:
                failures += 1
                print(f"FAIL {_name}")
                traceback.print_exc()
    print(f"\n{failures} failure(s)")
    sys.exit(1 if failures else 0)
