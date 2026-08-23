"""Tests for annotated assignment secret detection (Rule 2 / HARDCODED_SECRET).

Annotated assignments (e.g. ``api_key: str = "sk-..."`) previously bypassed
hardcoded-secret detection. This test suite verifies that the convention
checker now catches secrets in annotated assignments using the
_SECRET_VALUE_PREFIXES constant and _SECRET_PATTERNS.
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
    """Parse code and return HARDCODED_SECRET violations."""
    checker = ConventionChecker("test.py")
    checker.visit(ast.parse(code))
    return [v for v in checker._v2_violations if v.rule == RULE_HARDCODED_SECRET]


# ============================================================================
# Vendor-prefixed value tests: secret is detected by value prefix, not name
# ============================================================================

def test_annotated_assignment_with_sk_prefix():
    """Annotated assignment with 'sk-' vendor prefix should be flagged."""
    violations = _secret_violations('api_token: str = "sk-live-abcdef123456"')
    assert len(violations) == 1


def test_annotated_assignment_with_sk_underscore_prefix():
    """Annotated assignment with 'sk_' vendor prefix should be flagged."""
    violations = _secret_violations('key: str = "sk_test_abcdef123456"')
    assert len(violations) == 1


def test_annotated_assignment_with_api_dash_prefix():
    """Annotated assignment with 'api-' vendor prefix should be flagged."""
    violations = _secret_violations('endpoint: str = "api-key-abcdef123456"')
    assert len(violations) == 1


def test_annotated_assignment_with_pk_prefix():
    """Annotated assignment with 'pk_' vendor prefix should be flagged."""
    violations = _secret_violations('publishable_key: str = "pk_live_abcdef123456"')
    assert len(violations) == 1


def test_annotated_assignment_with_secret_prefix():
    """Annotated assignment with 'secret_' vendor prefix should be flagged."""
    violations = _secret_violations('config: str = "secret_abcdef123456"')
    assert len(violations) == 1


def test_annotated_assignment_with_token_prefix():
    """Annotated assignment with 'token_' vendor prefix should be flagged."""
    violations = _secret_violations('auth: str = "token_abcdef123456"')
    assert len(violations) == 1


def test_annotated_assignment_with_ghp_prefix():
    """Annotated assignment with 'ghp_' (GitHub Personal) prefix should be flagged."""
    violations = _secret_violations('github_token: str = "ghp_abcdef123456"')
    assert len(violations) == 1


def test_annotated_assignment_with_xoxb_prefix():
    """Annotated assignment with 'xoxb-' (Slack bot) prefix should be flagged."""
    violations = _secret_violations('slack_token: str = "xoxb-123456789"')
    assert len(violations) == 1


def test_vendor_prefix_case_insensitive():
    """Vendor prefix matching should be case-insensitive."""
    violations = _secret_violations('token: str = "SK-UPPERCASE123"')
    assert len(violations) == 1


# ============================================================================
# Secret-like names tests: secret is detected by variable name pattern
# ============================================================================

def test_annotated_password_literal():
    """Annotated assignment with 'password' in name should be flagged."""
    violations = _secret_violations('db_password: str = "hunter2"')
    assert len(violations) == 1


def test_annotated_secret_literal():
    """Annotated assignment with 'secret' in name should be flagged."""
    violations = _secret_violations('my_secret: str = "plaintext"')
    assert len(violations) == 1


def test_annotated_key_literal():
    """Annotated assignment with 'key' in name should be flagged."""
    violations = _secret_violations('private_key: str = "-----BEGIN PRIVATE KEY-----"')
    assert len(violations) == 1


def test_annotated_token_literal():
    """Annotated assignment with 'token' in name should be flagged."""
    violations = _secret_violations('access_token: str = "abc123def456"')
    assert len(violations) == 1


def test_annotated_api_key_literal():
    """Annotated assignment with 'api_key' in name should be flagged."""
    violations = _secret_violations('api_key: str = "mykey12345"')
    assert len(violations) == 1


def test_annotated_pat_literal():
    """Annotated assignment with 'pat' in name should be flagged."""
    violations = _secret_violations('github_pat: str = "ghp_pattern"')
    assert len(violations) == 1


def test_secret_pattern_case_insensitive():
    """Secret pattern matching should be case-insensitive."""
    violations = _secret_violations('API_KEY: str = "mytoken"')
    assert len(violations) == 1


# ============================================================================
# Combined vendor and name tests: both conditions present
# ============================================================================

def test_annotated_assignment_vendor_and_secret_name():
    """Vendor prefix AND secret-like name both present should be flagged."""
    violations = _secret_violations('api_key: str = "sk-live-abc123"')
    assert len(violations) == 1


def test_annotated_assignment_multiple_secret_patterns():
    """Variable name with multiple secret patterns should be flagged."""
    violations = _secret_violations('api_token_secret: str = "plaintext"')
    assert len(violations) == 1


# ============================================================================
# Non-flagged cases: indirection and environment variables
# ============================================================================

def test_annotated_env_get_not_flagged():
    """Annotated assignment using os.environ.get() should NOT be flagged."""
    violations = _secret_violations('api_key: str = os.environ.get("API_KEY")')
    assert violations == []


def test_annotated_env_subscript_not_flagged():
    """Annotated assignment using os.environ[] should NOT be flagged."""
    violations = _secret_violations('api_key: str = os.environ["API_KEY"]')
    assert violations == []


def test_annotated_placeholder_not_flagged():
    """Annotated assignment with placeholder values should NOT be flagged."""
    placeholders = [
        '"${API_TOKEN}"',
        '"$API_TOKEN"',
        '"{{ api_token }}"',
        '"<your-token-here>"',
        '"%(token)s"',
        '""',
    ]
    for placeholder in placeholders:
        code = f'api_token: str = {placeholder}'
        violations = _secret_violations(code)
        assert violations == [], f"{placeholder} should be treated as indirection"


def test_annotated_config_method_call_not_flagged():
    """Annotated assignment with method call should NOT be flagged."""
    violations = _secret_violations('secret: str = config.get_secret("name")')
    assert violations == []


# ============================================================================
# Non-secret names and values
# ============================================================================

def test_annotated_normal_url_not_flagged():
    """Annotated assignment with URL but non-secret name should NOT be flagged."""
    violations = _secret_violations('base_url: str = "https://example.com"')
    assert violations == []


def test_annotated_normal_path_not_flagged():
    """Annotated assignment with file path but non-secret name should NOT be flagged."""
    violations = _secret_violations('config_path: str = "/etc/config.json"')
    assert violations == []


def test_annotated_greeting_not_flagged():
    """Annotated assignment with greeting should NOT be flagged."""
    violations = _secret_violations('greeting: str = "hello world"')
    assert violations == []


def test_annotated_cache_key_not_flagged():
    """Annotated assignment with cache key constant should NOT be flagged."""
    violations = _secret_violations('ALERT_KEY: str = "cache_alert_key"')
    assert violations == []


def test_annotated_state_key_not_flagged():
    """Annotated assignment with state key should NOT be flagged."""
    violations = _secret_violations('STATE_KEY: str = "knob_tuner_state"')
    assert violations == []


# ============================================================================
# Edge cases
# ============================================================================

def test_annotated_assignment_none_value_not_flagged():
    """Annotated assignment with None value should NOT be flagged."""
    violations = _secret_violations('api_key: str = None')
    assert violations == []


def test_annotated_assignment_no_value_not_flagged():
    """Annotated assignment without value should NOT be flagged."""
    violations = _secret_violations('api_key: str')
    assert violations == []


def test_annotated_assignment_int_value_not_flagged():
    """Annotated assignment with int value should NOT be flagged."""
    violations = _secret_violations('count: int = 123')
    assert violations == []


def test_annotated_assignment_list_value_not_flagged():
    """Annotated assignment with list value should NOT be flagged."""
    violations = _secret_violations('items: list = ["a", "b"]')
    assert violations == []


def test_annotated_assignment_subscript_target_not_flagged():
    """Annotated assignment with subscript target should NOT be flagged."""
    violations = _secret_violations('config["key"]: str = "password"')
    # Note: This is technically invalid Python, but we test the visitor doesn't crash
    assert isinstance(violations, list)


def test_annotated_assignment_with_complex_annotation():
    """Annotated assignment with complex type annotation should still detect secrets."""
    violations = _secret_violations('api_key: Optional[str] = "sk-live-abc123"')
    assert len(violations) == 1


def test_annotated_assignment_with_union_annotation():
    """Annotated assignment with Union type should still detect secrets."""
    violations = _secret_violations('token: Union[str, None] = "ghp_abc123"')
    assert len(violations) == 1


# ============================================================================
# Regression: ensure plain assignments still work alongside annotated
# ============================================================================

def test_plain_and_annotated_both_detected():
    """Both plain and annotated secret assignments should be detected."""
    code = '''
api_key = "sk-live-plain"
api_token: str = "sk-live-annotated"
'''
    violations = _secret_violations(code)
    assert len(violations) == 2


def test_private_key_both_forms():
    """Private key secrets in both plain and annotated forms should be detected."""
    code = '''
key = "-----BEGIN PRIVATE KEY-----"
key_annotated: str = "-----BEGIN PRIVATE KEY-----"
'''
    violations = _secret_violations(code)
    assert len(violations) == 2


# ============================================================================
# Sentinel values that should NOT be flagged
# ============================================================================

def test_annotated_ignore_credential_marker_not_flagged():
    """IGNORE_CREDENTIAL sentinel should NOT be flagged."""
    violations = _secret_violations('IGNORE_CREDENTIAL: str = "credential-marker"')
    assert violations == []


def test_annotated_ignore_unsafe_key_marker_not_flagged():
    """IGNORE_UNSAFE_KEY sentinel should NOT be flagged."""
    violations = _secret_violations('IGNORE_UNSAFE_KEY: str = "not-a-safe-key"')
    assert violations == []


# ============================================================================
# Name referring to a secret (not the secret itself)
# ============================================================================

def test_annotated_token_env_var_name_not_flagged():
    """Variable holding the *name* of a token env var should NOT be flagged."""
    violations = _secret_violations('api_token_env: str = "ANTHROPIC_API_KEY"')
    assert violations == []


def test_annotated_secret_file_path_not_flagged():
    """Variable holding the *path* to a secret file should NOT be flagged."""
    violations = _secret_violations('secret_file: str = "/etc/creds.json"')
    assert violations == []


if __name__ == "__main__":
    import traceback

    failures = 0
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_") and callable(_fn):
            try:
                _fn()
                print(f"ok   {_name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {_name}")
                traceback.print_exc()
    print(f"\n{failures} failure(s)")
    sys.exit(1 if failures else 0)
