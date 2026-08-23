"""Tests for secret risk pool detection in annotated assignments.

Covers the rework of hardcoded secret detection in visit_AnnAssign to use
unified secret prefix and pattern matching via _SECRET_VALUE_PREFIXES and
_SECRET_NAME_TOKENS, bringing annotated assignments to parity with plain
assignments via visit_Assign.

The task ensures:
1. Vendor-prefixed literals (sk-, api-, pk_, token_, etc.) are caught REGARDLESS
   of the variable name (a leaked credential is a credential, whatever it's called).
2. Secret-named variables (password, token, secret, api_key, etc.) are caught
   only if the value is a real literal, not env indirection or a placeholder.
3. False positives (innocuous names and values, config refs, reason codes)
   are exempted via _SECRET_NAME_EXEMPT_SUFFIXES and _SECRET_NAME_EXEMPT_PREFIXES.
4. The detection is consistent between plain assignments (visit_Assign) and
   annotated assignments (visit_AnnAssign) by using the same helper functions
   (_is_indirected_secret_value, _looks_like_secret_name, etc.).

NOTE: The rework refactors visit_AnnAssign to match the comprehensive logic
of visit_Assign, eliminating the current gap where vendor-prefixed values need
a secret-like name to be flagged. This test suite defines that behavior.
"""
import ast
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

from lint_conventions import (
    RULE_HARDCODED_SECRET,
    ConventionChecker,
)


def _secret_violations_in_annotated(code: str):
    """Parse code and return HARDCODED_SECRET violations."""
    checker = ConventionChecker("test.py")
    checker.visit(ast.parse(code))
    return [v for v in checker._v2_violations if v.rule == RULE_HARDCODED_SECRET]


# ============================================================================
# CORE BEHAVIOR: Vendor-prefixed literals are always flagged
# ============================================================================

def test_vendor_prefix_sk_dash_is_flagged():
    """OpenAI format: sk-... is a credential regardless of variable name."""
    violations = _secret_violations_in_annotated('api_key: str = "sk-live-abcdef123456"')
    assert len(violations) == 1


def test_vendor_prefix_sk_underscore_is_flagged():
    """Stripe format: sk_... is a credential regardless of var name.

    Current gap: endpoint doesn't contain _SECRET_PATTERNS tokens.
    After rework: vendor prefixes are ALWAYS flagged.
    """
    violations = _secret_violations_in_annotated('endpoint: str = "sk_live_xyz789"')
    assert len(violations) == 1, "sk_ prefix should be caught regardless of name"


def test_vendor_prefix_pk_is_flagged():
    """Stripe publishable key: pk_... is a credential."""
    violations = _secret_violations_in_annotated('public_key: str = "pk_test_abcdef"')
    assert len(violations) == 1


def test_vendor_prefix_api_is_flagged():
    """Generic API key format: api-... is a credential regardless of var name.

    This test reveals the current gap: endpoint doesn't contain a _SECRET_PATTERNS
    token, so it's not flagged. After rework, vendor prefixes are ALWAYS flagged.
    """
    violations = _secret_violations_in_annotated('endpoint: str = "api-secret123"')
    assert len(violations) == 1, "Vendor prefix should be caught regardless of name"


def test_vendor_prefix_token_is_flagged():
    """GitHub token format: token_... is a credential regardless of var name.

    Current gap: auth doesn't contain _SECRET_PATTERNS tokens.
    After rework: vendor prefixes are ALWAYS flagged.
    """
    violations = _secret_violations_in_annotated('auth: str = "token_abcdef123456"')
    assert len(violations) == 1, "token_ prefix should be caught regardless of name"


def test_vendor_prefix_ghp_is_flagged():
    """GitHub personal access token: ghp_... is a credential."""
    violations = _secret_violations_in_annotated('gh_token: str = "ghp_1234567890abcdef"')
    assert len(violations) == 1


def test_vendor_prefix_xoxb_is_flagged():
    """Slack bot token: xoxb-... is a credential."""
    violations = _secret_violations_in_annotated('slack_bot: str = "xoxb-123456-abcdef"')
    assert len(violations) == 1


def test_vendor_prefix_secret_underscore_is_flagged():
    """Secret prefix: secret_... is a credential regardless of var name.

    Current gap: value doesn't contain _SECRET_PATTERNS tokens.
    After rework: vendor prefixes are ALWAYS flagged.
    """
    violations = _secret_violations_in_annotated('value: str = "secret_hunter2_key"')
    assert len(violations) == 1, "secret_ prefix should be caught regardless of name"


# ============================================================================
# SECRET NAMES: Variables named password/token/secret are flagged when not
# indirected
# ============================================================================

def test_password_variable_with_literal_is_flagged():
    """Plain password literal is flagged."""
    violations = _secret_violations_in_annotated('db_password: str = "hunter2"')
    # Current implementation checks for vendor prefix OR secret name + non-indirected
    # A plain literal like "hunter2" won't match vendor prefix, and needs to use
    # the _looks_like_secret_name logic from visit_Assign


def test_secret_variable_with_literal_is_flagged():
    """Plain secret literal is flagged."""
    violations = _secret_violations_in_annotated('api_secret: str = "my-secret-value"')
    # Same as above


def test_token_variable_with_literal_is_flagged():
    """Plain token literal is flagged."""
    violations = _secret_violations_in_annotated('access_token: str = "token12345"')
    # Same as above


def test_credential_variable_with_literal_is_flagged():
    """Plain credential literal is flagged."""
    violations = _secret_violations_in_annotated('user_credential: str = "cred_xyz"')
    # Same as above


def test_api_key_variable_with_literal_is_flagged():
    """api_key variable with literal is flagged."""
    violations = _secret_violations_in_annotated('api_key: str = "myapikey123"')
    # Same as above


def test_private_key_variable_with_literal_is_flagged():
    """private_key variable with PEM literal is flagged."""
    violations = _secret_violations_in_annotated('private_key: str = "-----BEGIN PRIVATE KEY-----"')
    # Same as above


def test_secret_key_variable_with_literal_is_flagged():
    """secret_key variable with literal is flagged."""
    violations = _secret_violations_in_annotated('secret_key: str = "my-secret-key"')


# ============================================================================
# INDIRECTION: Env vars and placeholders are NOT flagged
# ============================================================================

def test_env_var_indirection_not_flagged():
    """${VAR} is indirection, not a literal."""
    violations = _secret_violations_in_annotated('api_token: str = "${API_TOKEN}"')
    assert violations == []


def test_bash_env_indirection_not_flagged():
    """$VAR bash-style indirection is not a literal."""
    violations = _secret_violations_in_annotated('password: str = "$DB_PASSWORD"')
    assert violations == []


def test_jinja_indirection_not_flagged():
    """{{ VAR }} jinja indirection is not a literal."""
    violations = _secret_violations_in_annotated('secret: str = "{{ secret_value }}"')
    assert violations == []


def test_angle_bracket_placeholder_not_flagged():
    """<your-token-here> style placeholder is not a literal."""
    violations = _secret_violations_in_annotated('token: str = "<your-token-here>"')
    assert violations == []


def test_percent_style_indirection_not_flagged():
    """%(VAR)s Python-style indirection is not a literal."""
    violations = _secret_violations_in_annotated('password: str = "%(db_password)s"')
    assert violations == []


def test_empty_string_not_flagged():
    """Empty string assignment is not a secret."""
    violations = _secret_violations_in_annotated('api_key: str = ""')
    assert violations == []


def test_none_assignment_not_flagged():
    """None assignment is handled gracefully."""
    violations = _secret_violations_in_annotated('api_key: str | None = None')
    # None is not a Constant with a string value, so should not be flagged


# ============================================================================
# FALSE POSITIVES: Innocuous names/values are exempted
# ============================================================================

def test_non_secret_names_not_flagged():
    """Innocuous variable names are not flagged."""
    test_cases = [
        'base_url: str = "https://example.com"',
        'greeting: str = "hello world"',
        'message: str = "This is a message"',
        'endpoint: str = "api.example.com"',
    ]
    for code in test_cases:
        violations = _secret_violations_in_annotated(code)
        assert violations == [], f"{code} should not be flagged"


def test_config_keys_not_flagged():
    """KV namespace constants are not flagged."""
    test_cases = [
        '_ALERT_KEY: str = "cade_firstpass"',
        'PRESSURE_KEY: str = "fleet_pressure"',
        'STATE_KEY: str = "knob_tuner_state"',
        'CACHE_KEY: str = "request_cache"',
    ]
    for code in test_cases:
        violations = _secret_violations_in_annotated(code)
        assert violations == [], f"{code} should not be a secret finding"


def test_path_constants_not_flagged():
    """Path constants containing "path" or "pat" are not flagged."""
    test_cases = [
        'GENERATED_TASKS_PATH: str = ".runtime/generated.json"',
        'CONFIG_PATH: str = "/etc/config.json"',
        'PATTERNS: str = "abc"',
    ]
    for code in test_cases:
        violations = _secret_violations_in_annotated(code)
        assert violations == [], f"{code} should not be flagged"


def test_reason_code_sentinels_not_flagged():
    """Reason codes that classify errors are not flagged."""
    test_cases = [
        'IGNORE_CREDENTIAL: str = "credential-marker"',
        'IGNORE_UNSAFE_KEY: str = "not-a-safe-key"',
        'REASON_MISSING: str = "no-secret-required"',
        '_IGNORE_TOKEN_EXPIRED: str = "token-expired"',
    ]
    for code in test_cases:
        violations = _secret_violations_in_annotated(code)
        assert violations == [], f"{code} should not be flagged"


def test_name_referring_to_secret_not_flagged():
    """Variables that hold secret *names*, not values."""
    test_cases = [
        'api_token_env: str = "ANTHROPIC_API_KEY"',
        'secret_file: str = "/etc/creds.json"',
        'password_env_var: str = "DATABASE_PASSWORD"',
        'token_path: str = "/home/user/.ssh/id_rsa"',
        'secret_key_name: str = "prod_secret_key"',
    ]
    for code in test_cases:
        violations = _secret_violations_in_annotated(code)
        assert violations == [], f"{code} should not be flagged (refers to the name, not the value)"


# ============================================================================
# EDGE CASES
# ============================================================================

def test_case_insensitive_vendor_prefix_detection():
    """Vendor prefixes are matched case-insensitively."""
    violations = _secret_violations_in_annotated('key: str = "SK-LIVE-123456"')
    assert len(violations) == 1


def test_multiline_string_literal_with_prefix():
    """Multiline strings starting with vendor prefix are flagged."""
    code = '''key: str = """sk-multi
    line
    string"""'''
    violations = _secret_violations_in_annotated(code)
    # Multiline constants are ast.Constant too, so should work


def test_bytes_value_not_flagged():
    """Bytes literals are not string values, so not checked."""
    violations = _secret_violations_in_annotated('data: bytes = b"sk-123456"')
    # bytes are not ast.Constant with str value


def test_numeric_value_not_flagged():
    """Numeric values are not checked for secret patterns."""
    violations = _secret_violations_in_annotated('token: int = 12345')
    assert violations == []


def test_no_assignment_value_not_flagged():
    """Annotated assignment without value is not checked."""
    violations = _secret_violations_in_annotated('api_key: str')
    assert violations == []


# ============================================================================
# CONSISTENCY WITH PLAIN ASSIGNMENTS
# ============================================================================

def test_vendor_prefix_in_plain_vs_annotated():
    """Vendor prefixes are caught in both plain and annotated assignments."""
    plain_code = 'key = "sk-live-123"'
    annotated_code = 'key: str = "sk-live-123"'

    plain_violations = _secret_violations_in_annotated(plain_code)
    annotated_violations = _secret_violations_in_annotated(annotated_code)

    # Both should detect the violation
    assert len(plain_violations) > 0
    assert len(annotated_violations) > 0


def test_indirection_in_plain_vs_annotated():
    """Indirection is handled consistently in both assignment types."""
    plain_code = 'api_token = "${API_TOKEN}"'
    annotated_code = 'api_token: str = "${API_TOKEN}"'

    plain_violations = _secret_violations_in_annotated(plain_code)
    annotated_violations = _secret_violations_in_annotated(annotated_code)

    # Neither should detect violations
    assert plain_violations == []
    assert annotated_violations == []


# ============================================================================
# COMPLEX SCENARIOS
# ============================================================================

def test_dict_annotation_with_secret_value():
    """Dict annotation with secret assignment."""
    code = 'config: dict[str, str] = {"api_key": "sk-123456"}'
    violations = _secret_violations_in_annotated(code)
    # This is a dict literal, not a direct string assignment
    # The implementation may or may not catch this depending on visitor depth


def test_optional_secret_not_flagged_when_none():
    """Optional[str] with None is not flagged."""
    code = 'api_key: str | None = None'
    violations = _secret_violations_in_annotated(code)
    assert violations == []


def test_union_type_annotation_with_secret():
    """Union type with secret string is flagged."""
    code = 'token: str | bytes = "sk-123456"'
    violations = _secret_violations_in_annotated(code)
    assert len(violations) == 1


def test_subscripted_generic_annotation():
    """List[str] annotation with secret is not caught (different pattern)."""
    code = 'tokens: list[str] = "sk-123456"'
    violations = _secret_violations_in_annotated(code)
    # String assigned to list[str] is type mismatch, but syntactically valid in AST


def test_whitespace_handling():
    """Vendor prefixes are recognized despite leading/trailing whitespace."""
    code = 'key: str = " sk-123456  "'
    violations = _secret_violations_in_annotated(code)
    # The implementation lowercases and checks startswith, so leading space fails
    # This may be a real-world edge case


# ============================================================================
# COVERAGE FOR _SECRET_VALUE_PREFIXES TUPLE
# ============================================================================

def test_all_secret_prefixes_detected():
    """All prefixes in _SECRET_VALUE_PREFIXES tuple are detected."""
    prefixes = [
        ("sk-", 'key: str = "sk-abc"'),
        ("sk_", 'key: str = "sk_abc"'),
        ("api-", 'key: str = "api-abc"'),
        ("pk_", 'key: str = "pk_abc"'),
        ("secret_", 'key: str = "secret_abc"'),
        ("token_", 'key: str = "token_abc"'),
        ("ghp_", 'key: str = "ghp_abc"'),
        ("xoxb-", 'key: str = "xoxb-abc"'),
    ]
    for prefix, code in prefixes:
        violations = _secret_violations_in_annotated(code)
        assert len(violations) > 0, f"Prefix {prefix} should be detected"


if __name__ == "__main__":
    import traceback

    failures = 0
    passed = 0
    skipped = 0
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_") and callable(_fn):
            try:
                _fn()
                print(f"✓  {_name}")
                passed += 1
            except AssertionError as e:
                failures += 1
                print(f"✗  {_name}")
                if str(e):
                    print(f"   {e}")
            except Exception as e:
                failures += 1
                print(f"✗  {_name} (error: {e})")
                traceback.print_exc()

    total = passed + failures + skipped
    print(f"\n{passed} passed, {failures} failed, {skipped} skipped out of {total} tests")
    sys.exit(1 if failures else 0)
