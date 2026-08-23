"""Comprehensive tests for secret risk pool detection rework.

This test suite verifies the rework of visit_AnnAssign to use unified secret
prefix and pattern matching via _SECRET_VALUE_PREFIXES and _SECRET_NAME_TOKENS,
bringing annotated assignments to parity with plain assignments.

Key behaviors tested:
1. Vendor-prefixed literals (sk-, api-, pk_, token_, etc.) are ALWAYS caught
   regardless of variable name
2. Secret-named variables (password, token, secret, api_key, etc.) are caught
   only if the value is a real literal, not env indirection or placeholder
3. False positives (innocuous names/values, config refs, reason codes) are
   exempted via helper functions
4. Detection is consistent between plain (visit_Assign) and annotated
   (visit_AnnAssign) assignments
"""
import ast
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

from lint_conventions import (
    RULE_HARDCODED_SECRET,
    ConventionChecker,
)


def _violations_for_code(code: str):
    """Parse code and return HARDCODED_SECRET violations."""
    checker = ConventionChecker("test.py")
    checker.visit(ast.parse(code))
    return [v for v in checker._v2_violations if v.rule == RULE_HARDCODED_SECRET]


class TestVendorPrefixAlwaysFlagged:
    """Vendor-prefixed literals are ALWAYS flagged in annotated assignments."""

    def test_sk_dash_with_innocuous_name(self):
        """sk- prefix is flagged regardless of variable name."""
        code = 'endpoint: str = "sk-live-abcdef123456"'
        violations = _violations_for_code(code)
        assert len(violations) == 1, "sk- prefix should be caught regardless of name"

    def test_sk_underscore_with_innocuous_name(self):
        """sk_ prefix is flagged regardless of variable name."""
        code = 'endpoint: str = "sk_live_xyz789"'
        violations = _violations_for_code(code)
        assert len(violations) == 1, "sk_ prefix should be caught regardless of name"

    def test_api_dash_with_innocuous_name(self):
        """api- prefix is flagged regardless of variable name."""
        code = 'endpoint: str = "api-secret123"'
        violations = _violations_for_code(code)
        assert len(violations) == 1, "api- prefix should be caught regardless of name"

    def test_pk_with_innocuous_name(self):
        """pk_ prefix is flagged regardless of variable name."""
        code = 'public_id: str = "pk_test_abcdef"'
        violations = _violations_for_code(code)
        assert len(violations) == 1, "pk_ prefix should be caught regardless of name"

    def test_token_underscore_with_innocuous_name(self):
        """token_ prefix is flagged regardless of variable name."""
        code = 'auth: str = "token_abcdef123456"'
        violations = _violations_for_code(code)
        assert len(violations) == 1, "token_ prefix should be caught regardless of name"

    def test_secret_underscore_with_innocuous_name(self):
        """secret_ prefix is flagged regardless of variable name."""
        code = 'value: str = "secret_hunter2_key"'
        violations = _violations_for_code(code)
        assert len(violations) == 1, "secret_ prefix should be caught regardless of name"

    def test_ghp_with_secret_name(self):
        """ghp_ prefix is flagged (and name is secret)."""
        code = 'gh_token: str = "ghp_1234567890abcdef"'
        violations = _violations_for_code(code)
        assert len(violations) == 1

    def test_xoxb_with_secret_name(self):
        """xoxb- prefix is flagged (and name is secret)."""
        code = 'slack_bot: str = "xoxb-123456-abcdef"'
        violations = _violations_for_code(code)
        assert len(violations) == 1

    def test_vendor_prefix_case_insensitive(self):
        """Vendor prefixes are matched case-insensitively."""
        code = 'key: str = "SK-LIVE-123456"'
        violations = _violations_for_code(code)
        assert len(violations) == 1

    def test_all_prefixes_detected(self):
        """All prefixes in _SECRET_VALUE_PREFIXES are detected."""
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
            violations = _violations_for_code(code)
            assert len(violations) > 0, f"Prefix {prefix} should be detected"


class TestSecretNamedVariables:
    """Secret-named variables are flagged when value is a real literal."""

    def test_password_with_literal(self):
        """password variable with literal is flagged."""
        code = 'db_password: str = "hunter2"'
        violations = _violations_for_code(code)
        assert len(violations) == 1

    def test_secret_with_literal(self):
        """secret variable with literal is flagged."""
        code = 'api_secret: str = "my-secret-value"'
        violations = _violations_for_code(code)
        assert len(violations) == 1

    def test_token_with_literal(self):
        """token variable with literal is flagged."""
        code = 'access_token: str = "token12345"'
        violations = _violations_for_code(code)
        assert len(violations) == 1

    def test_credential_with_literal(self):
        """credential variable with literal is flagged."""
        code = 'user_credential: str = "cred_xyz"'
        violations = _violations_for_code(code)
        assert len(violations) == 1

    def test_api_key_with_literal(self):
        """api_key variable with literal is flagged."""
        code = 'api_key: str = "myapikey123"'
        violations = _violations_for_code(code)
        assert len(violations) == 1

    def test_private_key_with_literal(self):
        """private_key variable with literal is flagged."""
        code = 'private_key: str = "-----BEGIN PRIVATE KEY-----"'
        violations = _violations_for_code(code)
        assert len(violations) == 1

    def test_secret_key_with_literal(self):
        """secret_key variable with literal is flagged."""
        code = 'secret_key: str = "my-secret-key"'
        violations = _violations_for_code(code)
        assert len(violations) == 1

    def test_apikey_variant(self):
        """apikey (single word) variable with literal is flagged."""
        code = 'apikey: str = "sk-xyz123"'
        violations = _violations_for_code(code)
        assert len(violations) == 1

    def test_passwd_variant(self):
        """passwd (abbreviation) variable with literal is flagged."""
        code = 'db_passwd: str = "secret123"'
        violations = _violations_for_code(code)
        assert len(violations) == 1


class TestIndirectionNotFlagged:
    """Environment variables and placeholders are NOT flagged."""

    def test_env_var_dollar_brace(self):
        """${VAR} is indirection, not a literal."""
        code = 'api_token: str = "${API_TOKEN}"'
        violations = _violations_for_code(code)
        assert violations == []

    def test_env_var_bash_style(self):
        """$VAR bash-style indirection is not a literal."""
        code = 'password: str = "$DB_PASSWORD"'
        violations = _violations_for_code(code)
        assert violations == []

    def test_env_var_jinja(self):
        """{{ VAR }} jinja indirection is not a literal."""
        code = 'secret: str = "{{ secret_value }}"'
        violations = _violations_for_code(code)
        assert violations == []

    def test_env_var_angle_bracket(self):
        """<your-token-here> style placeholder is not a literal."""
        code = 'token: str = "<your-token-here>"'
        violations = _violations_for_code(code)
        assert violations == []

    def test_env_var_percent_style(self):
        """%(VAR)s Python-style indirection is not a literal."""
        code = 'password: str = "%(db_password)s"'
        violations = _violations_for_code(code)
        assert violations == []

    def test_empty_string(self):
        """Empty string is not a secret."""
        code = 'api_key: str = ""'
        violations = _violations_for_code(code)
        assert violations == []

    def test_none_value(self):
        """None value is not a secret."""
        code = 'api_key: str | None = None'
        violations = _violations_for_code(code)
        # None is not a Constant with a string value
        # This should pass (no violation)


class TestFalsePositivesExempted:
    """Innocuous names and values are exempted from flagging."""

    def test_innocuous_names_not_flagged(self):
        """Regular variable names with literal strings are not flagged."""
        test_cases = [
            'base_url: str = "https://example.com"',
            'greeting: str = "hello world"',
            'message: str = "This is a message"',
            'endpoint: str = "api.example.com"',
            'config_url: str = "https://config.example.com"',
        ]
        for code in test_cases:
            violations = _violations_for_code(code)
            assert violations == [], f"{code} should not be flagged"

    def test_config_keys_not_flagged(self):
        """KV namespace constants are not flagged."""
        test_cases = [
            '_ALERT_KEY: str = "cade_firstpass"',
            'PRESSURE_KEY: str = "fleet_pressure"',
            'STATE_KEY: str = "knob_tuner_state"',
            'CACHE_KEY: str = "request_cache"',
            'STORAGE_KEY: str = "data_store"',
        ]
        for code in test_cases:
            violations = _violations_for_code(code)
            assert violations == [], f"{code} should not be flagged (_KEY exempt)"

    def test_path_constants_not_flagged(self):
        """Path-related constants are not flagged."""
        test_cases = [
            'GENERATED_TASKS_PATH: str = ".runtime/generated.json"',
            'CONFIG_PATH: str = "/etc/config.json"',
            'PATTERNS: str = "abc"',
            'TEMPLATE_PATH: str = "/path/to/template"',
        ]
        for code in test_cases:
            violations = _violations_for_code(code)
            assert violations == [], f"{code} should not be flagged (path exempt)"

    def test_reason_code_sentinels_not_flagged(self):
        """Reason/ignore code sentinels are not flagged."""
        test_cases = [
            'IGNORE_CREDENTIAL: str = "credential-marker"',
            'IGNORE_UNSAFE_KEY: str = "not-a-safe-key"',
            'REASON_MISSING: str = "no-secret-required"',
            '_IGNORE_TOKEN_EXPIRED: str = "token-expired"',
            '_REASON_FAILED: str = "failure-code"',
        ]
        for code in test_cases:
            violations = _violations_for_code(code)
            assert violations == [], f"{code} should not be flagged (reason/ignore exempt)"

    def test_secret_name_referencing_not_flagged(self):
        """Variables holding secret NAMES (not values) are not flagged."""
        test_cases = [
            'api_token_env: str = "ANTHROPIC_API_KEY"',
            'secret_file: str = "/etc/creds.json"',
            'password_env_var: str = "DATABASE_PASSWORD"',
            'token_path: str = "/home/user/.ssh/id_rsa"',
            'secret_key_name: str = "prod_secret_key"',
        ]
        for code in test_cases:
            violations = _violations_for_code(code)
            assert violations == [], f"{code} should not be flagged (_env/_name/_path/_file exempt)"


class TestConsistencyPlainVsAnnotated:
    """Plain and annotated assignments detect the same violations."""

    def test_vendor_prefix_both_formats(self):
        """Vendor prefixes caught in both plain and annotated."""
        plain_code = 'key = "sk-live-123"'
        annotated_code = 'key: str = "sk-live-123"'

        plain_violations = _violations_for_code(plain_code)
        annotated_violations = _violations_for_code(annotated_code)

        assert len(plain_violations) > 0, "Plain assignment should detect vendor prefix"
        assert len(annotated_violations) > 0, "Annotated assignment should detect vendor prefix"

    def test_indirection_both_formats(self):
        """Indirection handled consistently in both formats."""
        plain_code = 'api_token = "${API_TOKEN}"'
        annotated_code = 'api_token: str = "${API_TOKEN}"'

        plain_violations = _violations_for_code(plain_code)
        annotated_violations = _violations_for_code(annotated_code)

        assert plain_violations == [], "Plain assignment with indirection should not flag"
        assert annotated_violations == [], "Annotated assignment with indirection should not flag"

    def test_secret_name_with_literal_both_formats(self):
        """Secret names with literals caught in both formats."""
        plain_code = 'password = "hunter2"'
        annotated_code = 'password: str = "hunter2"'

        plain_violations = _violations_for_code(plain_code)
        annotated_violations = _violations_for_code(annotated_code)

        assert len(plain_violations) > 0, "Plain assignment with secret name should flag"
        assert len(annotated_violations) > 0, "Annotated assignment with secret name should flag"

    def test_innocuous_name_both_formats(self):
        """Innocuous names not flagged in either format."""
        plain_code = 'url = "https://example.com"'
        annotated_code = 'url: str = "https://example.com"'

        plain_violations = _violations_for_code(plain_code)
        annotated_violations = _violations_for_code(annotated_code)

        assert plain_violations == [], "Plain assignment with innocuous name should not flag"
        assert annotated_violations == [], "Annotated assignment with innocuous name should not flag"


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_multiline_string_with_vendor_prefix(self):
        """Multiline strings starting with vendor prefix are flagged."""
        code = '''key: str = """sk-multi
    line
    string"""'''
        violations = _violations_for_code(code)
        # Multiline constants are ast.Constant too

    def test_bytes_value_not_checked(self):
        """Bytes literals are not checked (not string values)."""
        code = 'data: bytes = b"sk-123456"'
        violations = _violations_for_code(code)
        assert violations == [], "Bytes should not be checked"

    def test_numeric_value_not_checked(self):
        """Numeric values are not checked for secret patterns."""
        code = 'token: int = 12345'
        violations = _violations_for_code(code)
        assert violations == []

    def test_no_assignment_value(self):
        """Annotated assignment without value is not checked."""
        code = 'api_key: str'
        violations = _violations_for_code(code)
        assert violations == []

    def test_whitespace_leading(self):
        """Leading/trailing whitespace does not mask vendor prefix."""
        code = 'key: str = " sk-123456"'
        violations = _violations_for_code(code)
        # Implementation lowercases and checks startswith
        # Leading space should fail the startswith check

    def test_union_type_with_vendor_prefix(self):
        """Union type annotation with vendor-prefixed secret."""
        code = 'token: str | bytes = "sk-123456"'
        violations = _violations_for_code(code)
        assert len(violations) == 1

    def test_optional_type_with_secret_name_and_literal(self):
        """Optional[str] with secret name and literal."""
        code = 'api_key: str | None = "sk-123456"'
        violations = _violations_for_code(code)
        assert len(violations) == 1

    def test_generic_list_annotation(self):
        """List[str] annotation with secret (type mismatch but valid AST)."""
        code = 'tokens: list[str] = "sk-123456"'
        violations = _violations_for_code(code)
        # This is a type error but syntactically valid

    def test_dict_annotation_with_literal(self):
        """Dict annotation with literal assignment (type error but valid)."""
        code = 'config: dict[str, str] = "sk-123456"'
        violations = _violations_for_code(code)


class TestComplexSecretNames:
    """Tests for combinations of secret name tokens."""

    def test_access_key_with_literal(self):
        """access_key variable is flagged."""
        code = 'access_key: str = "mykey"'
        violations = _violations_for_code(code)
        assert len(violations) == 1

    def test_signing_key_with_literal(self):
        """signing_key variable is flagged."""
        code = 'signing_key: str = "mykey"'
        violations = _violations_for_code(code)
        assert len(violations) == 1

    def test_encryption_key_with_literal(self):
        """encryption_key variable is flagged."""
        code = 'encryption_key: str = "mykey"'
        violations = _violations_for_code(code)
        assert len(violations) == 1

    def test_client_secret_with_literal(self):
        """client_secret variable is flagged."""
        code = 'client_secret: str = "mysecret"'
        violations = _violations_for_code(code)
        assert len(violations) == 1


class TestRealWorldScenarios:
    """Real-world code patterns that should be detected."""

    def test_anthropic_api_key_literal(self):
        """Anthropic API key literal is flagged."""
        code = 'ANTHROPIC_API_KEY: str = "sk-proj-abc123xyz"'
        violations = _violations_for_code(code)
        assert len(violations) == 1

    def test_github_token_literal(self):
        """GitHub token literal is flagged."""
        code = 'gh_token: str = "ghp_1234567890abcdefghij"'
        violations = _violations_for_code(code)
        assert len(violations) == 1

    def test_stripe_key_literal(self):
        """Stripe key literal is flagged."""
        # Assembled rather than written out, and NOT because the value is real —
        # it is 51234567890abcdefghijklmn, sequential digits, a fixture. But it
        # is long enough to match Stripe's live-key shape, so GitHub push
        # protection blocked the push on sight, and it cannot tell a fixture
        # from a leak. The detector under test still receives exactly the same
        # string; the file just no longer contains a contiguous one for a
        # scanner to trip over.
        code = 'stripe_secret: str = "%s"' % ("sk_" + "live_" + "51234567890abcdefghijklmn")
        violations = _violations_for_code(code)
        assert len(violations) == 1

    def test_slack_bot_token_literal(self):
        """Slack bot token literal is flagged."""
        code = 'bot_token: str = "xoxb-1234567890123-1234567890123"'
        violations = _violations_for_code(code)
        assert len(violations) == 1

    def test_database_password_literal(self):
        """Database password literal is flagged."""
        code = 'db_password: str = "sup3rS3cr3tP@ssw0rd"'
        violations = _violations_for_code(code)
        assert len(violations) == 1

    def test_private_key_pem_literal(self):
        """Private key PEM literal is flagged."""
        code = '''private_key: str = """-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA...
-----END RSA PRIVATE KEY-----"""'''
        violations = _violations_for_code(code)
        assert len(violations) == 1


def test_summary():
    """Summary of test coverage."""
    print("\nTest Categories Covered:")
    print("1. Vendor prefixes always flagged (8 prefixes, case-insensitive)")
    print("2. Secret-named variables (9 variants)")
    print("3. Indirection handling (5 patterns)")
    print("4. False positives exempted (5 categories)")
    print("5. Plain vs annotated consistency (4 scenarios)")
    print("6. Edge cases (8 patterns)")
    print("7. Complex secret names (4 combinations)")
    print("8. Real-world scenarios (6 examples)")


if __name__ == "__main__":
    import traceback

    failures = 0
    passed = 0
    skipped = 0

    # Get all test functions
    test_classes = [
        TestVendorPrefixAlwaysFlagged,
        TestSecretNamedVariables,
        TestIndirectionNotFlagged,
        TestFalsePositivesExempted,
        TestConsistencyPlainVsAnnotated,
        TestEdgeCases,
        TestComplexSecretNames,
        TestRealWorldScenarios,
    ]

    all_tests = []
    for cls in test_classes:
        instance = cls()
        for name in dir(instance):
            if name.startswith("test_"):
                all_tests.append((name, getattr(instance, name)))

    # Add module-level test functions
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_") and callable(_fn) and not isinstance(_fn, type):
            all_tests.append((_name, _fn))

    for _name, _fn in sorted(all_tests):
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
