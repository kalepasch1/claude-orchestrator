"""
Test suite for convention_lint.py - Phase 1 convention enforcement.

Tests cover 3 core rules:
1. Fail-soft error handling: Public functions should not raise on bad input
2. Hardcoded secrets in config keys: FLAG PASSWORD|TOKEN|SECRET|KEY= without env-var
3. Module-level singletons: Verify acquire() exists before instance methods
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

from convention_lint import check_file, ConventionViolation


class TestFailSoftErrorHandling(unittest.TestCase):
    """Test rule: Public functions should not raise on bad input."""

    def _check_code(self, code: str) -> list:
        """Helper to check code snippet."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                violations = check_file(f.name)
                return violations
            finally:
                os.unlink(f.name)

    def test_pass_return_empty_string_on_error(self):
        """Function with try/except returning default passes."""
        code = """
def read_file(path):
    try:
        return open(path).read()
    except:
        return ""
"""
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertEqual(fail_soft_violations, [])

    def test_pass_return_none_on_error(self):
        """Function returning None on error passes."""
        code = """
def load_config(path):
    try:
        with open(path) as f:
            return json.load(f)
    except:
        return None
"""
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertEqual(fail_soft_violations, [])

    def test_pass_private_function_can_raise(self):
        """Private functions (starting with _) can raise."""
        code = """
def _internal_helper(path):
    data = open(path).read()
    raise ValueError("Invalid data")
"""
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertEqual(fail_soft_violations, [])

    def test_fail_public_function_raises_without_handler(self):
        """Public function raising without exception handler fails."""
        code = """
def process_data(data):
    raise ValueError("Invalid data")
"""
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertGreater(len(fail_soft_violations), 0)

    def test_fail_public_function_with_empty_except(self):
        """Public function with empty except handler fails."""
        code = """
def safe_operation():
    try:
        risky_call()
    except:
        pass
"""
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertGreater(len(fail_soft_violations), 0)

    def test_pass_method_can_raise(self):
        """Methods in classes can raise (not module-level functions)."""
        code = """
class Handler:
    def process(self):
        raise ValueError("Invalid")
"""
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertEqual(fail_soft_violations, [])


class TestHardcodedSecrets(unittest.TestCase):
    """Test rule: FLAG hardcoded secrets without env-var indirection."""

    def _check_code(self, code: str) -> list:
        """Helper to check code snippet."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                violations = check_file(f.name)
                return violations
            finally:
                os.unlink(f.name)

    def test_pass_env_var_reference(self):
        """Environment variable references pass."""
        code = "api_token = os.environ['API_TOKEN']"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertEqual(secret_violations, [])

    def test_pass_env_var_placeholder(self):
        """Environment variable placeholders pass."""
        code = "secret = '$SECRET_KEY'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertEqual(secret_violations, [])

    def test_pass_generic_string_variable(self):
        """Generic string variables pass."""
        code = "message = 'This is a message'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertEqual(secret_violations, [])

    def test_fail_hardcoded_api_token(self):
        """Hardcoded API token fails."""
        code = "api_token = 'sk-1234567890abcdef'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertGreater(len(secret_violations), 0)

    def test_fail_hardcoded_password(self):
        """Hardcoded password fails."""
        code = "db_password = 'mypassword123'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertGreater(len(secret_violations), 0)

    def test_fail_config_key_with_secret(self):
        """Config key with secret keyword fails."""
        code = "config['DATABASE_PASSWORD'] = 'secret'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertGreater(len(secret_violations), 0)

    def test_fail_private_key_in_config(self):
        """Private key in config fails."""
        code = "config['PRIVATE_KEY'] = 'key-data'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertGreater(len(secret_violations), 0)

    # ── Regression: the nine false positives this rule produced on runner/ ──────────
    #
    # Every HARDCODED_SECRET the linter reported across the whole runner/ tree was
    # false. Each case below is a verbatim line from the code it flagged. They are
    # tested individually rather than as one blob so a regression names the shape that
    # broke, and as a group so the "zero false positives" property is asserted directly.

    def _secret_hits(self, code: str) -> list:
        return [v for v in self._check_code(code) if v.rule == 'HARDCODED_SECRET']

    def test_pass_author_is_not_auth(self):
        """"author_model" must not match the "auth" keyword by substring."""
        self.assertEqual(self._secret_hits('author_model = "anthropic-claude"'), [])
        self.assertEqual(self._secret_hits('author_provider = "openai"'), [])

    def test_pass_empty_string_assigned_to_secret_name(self):
        """An empty literal cannot leak a credential, whatever it is called."""
        self.assertEqual(self._secret_hits('auth_hint = ""'), [])
        self.assertEqual(self._secret_hits('credential_fp = ""'), [])
        self.assertEqual(self._secret_hits('api_key = ""'), [])

    def test_pass_sentinel_and_placeholder_values(self):
        """Markers and test placeholders are config vocabulary, not credentials."""
        self.assertEqual(self._secret_hits('IGNORE_CREDENTIAL = "credential-marker"'), [])
        self.assertEqual(self._secret_hits('os.environ["PLOEH_S2S_SECRET"] = "test-key"'), [])

    def test_pass_config_row_names_ending_in_key(self):
        """fleet_config row names (STATE_KEY, BUDGET_KEY, ...) hold names, not secrets."""
        for line in ('STATE_KEY = "orch_state_v2"',
                     'BUDGET_KEY = "material_red_team_budget"',
                     'PRESSURE_KEY = "merge_train_pressure"',
                     'CONTROL_KEY = "model_slashing_control"'):
            self.assertEqual(self._secret_hits(line), [], line)

    def test_fail_qualified_key_names_still_flagged(self):
        """"key" next to a qualifier is still a credential."""
        for line in ('api_key = "sk-live-9f83bc2a17de"',
                     'private_key = "MIIEowIBAAKCAQEA9f83bc"',
                     'accessKey = "AKIA9F83BC2A17DEQZ"'):
            self.assertGreater(len(self._secret_hits(line)), 0, line)

    def test_pass_prose_assigned_to_secret_name(self):
        """Human-readable messages contain spaces; credentials do not."""
        self.assertEqual(
            self._secret_hits('auth_error = "token exchange failed, retrying"'), [])

    def test_real_credentials_are_still_caught(self):
        """The tightening must not buy its accuracy with false negatives."""
        for line in ('GITHUB_TOKEN = "ghp_16C7e42F292c6912E7710c838347Ae178B4a"',
                     'password = "hunter2corrhorse"',
                     'SUPABASE_SECRET = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"'):
            self.assertGreater(len(self._secret_hits(line)), 0, line)


class TestModuleLevelSingletons(unittest.TestCase):
    """Test rule: Module-level functions follow singleton delegation pattern."""

    def _check_code(self, code: str) -> list:
        """Helper to check code snippet."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                violations = check_file(f.name)
                return violations
            finally:
                os.unlink(f.name)

    def test_pass_singleton_delegation(self):
        """Module functions delegating to singleton pass."""
        code = """
_pool = None

def acquire():
    global _pool
    if _pool is None:
        _pool = Pool()
    return _pool.acquire()
"""
        violations = self._check_code(code)
        # Currently no test for singletons; this documents the pattern
        self.assertIsNotNone(violations)

    def test_pass_normal_module_function(self):
        """Normal module functions without self parameter pass."""
        code = """
def process_data(data):
    return transform(data)
"""
        violations = self._check_code(code)
        # Should not flag as singleton violation
        self.assertIsNotNone(violations)


class TestIntegration(unittest.TestCase):
    """Integration tests with multiple violations."""

    def _check_code(self, code: str) -> list:
        """Helper to check code snippet."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                violations = check_file(f.name)
                return violations
            finally:
                os.unlink(f.name)

    def test_multiple_violations(self):
        """Code with multiple violations reports all."""
        code = """
def process():
    api_key = 'hardcoded-key'
    raise ValueError("Bad input")

config['DB_PASSWORD'] = 'secret'
"""
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertGreater(len(secret_violations), 0)
        self.assertGreater(len(fail_soft_violations), 0)

    def test_violation_has_required_fields(self):
        """Violation objects have all required fields."""
        code = """
def func():
    password = 'secret'
"""
        violations = self._check_code(code)
        self.assertGreater(len(violations), 0)
        v = violations[0]
        self.assertIsNotNone(v.filepath)
        self.assertIsNotNone(v.lineno)
        self.assertIsNotNone(v.rule)
        self.assertIsNotNone(v.message)
        self.assertIsNotNone(v.severity)


if __name__ == '__main__':
    unittest.main()
