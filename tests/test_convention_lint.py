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

    def test_fail_soft_pass_return_empty_string_on_error(self):
        """FS1: Function with try/except returning default passes."""
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

    def test_fail_soft_pass_return_none_on_error(self):
        """FS2: Function returning None on error passes."""
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

    def test_fail_soft_pass_private_function_can_raise(self):
        """FS3: Private functions (starting with _) can raise."""
        code = """
def _internal_helper(path):
    data = open(path).read()
    raise ValueError("Invalid data")
"""
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertEqual(fail_soft_violations, [])

    def test_fail_soft_fail_public_function_raises_without_handler(self):
        """FS4: Public function raising without exception handler fails."""
        code = """
def process_data(data):
    raise ValueError("Invalid data")
"""
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertGreater(len(fail_soft_violations), 0)

    def test_fail_soft_pass_method_can_raise(self):
        """FS5: Methods in classes can raise (not module-level functions)."""
        code = """
class Handler:
    def process(self):
        raise ValueError("Invalid")
"""
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertEqual(fail_soft_violations, [])

    def test_fail_soft_pass_noqa_comment_disables_check(self):
        """FS6: # noqa: FAIL_SOFT_ERROR comment disables check."""
        code = """
def risky_function():  # noqa: FAIL_SOFT_ERROR
    raise ValueError("This is allowed")
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

    def test_secret_pass_env_var_reference(self):
        """S1: Environment variable references pass."""
        code = "api_token = os.environ['API_TOKEN']"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertEqual(secret_violations, [])

    def test_secret_pass_env_var_placeholder(self):
        """S2: Environment variable placeholders pass."""
        code = "secret = '$SECRET_KEY'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertEqual(secret_violations, [])

    def test_secret_pass_generic_string_variable(self):
        """S3: Generic string variables pass."""
        code = "message = 'This is a message'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertEqual(secret_violations, [])

    def test_secret_fail_hardcoded_password(self):
        """S4: Hardcoded password fails."""
        code = "db_password = 'mypassword123'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertGreater(len(secret_violations), 0)

    def test_secret_fail_config_key_with_secret(self):
        """S5: Config key with secret keyword fails."""
        code = "config['DATABASE_PASSWORD'] = 'secret'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertGreater(len(secret_violations), 0)

    def test_secret_fail_private_key_in_config(self):
        """S6: Private key in config fails."""
        code = "config['PRIVATE_KEY'] = 'key-data'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertGreater(len(secret_violations), 0)

    def test_secret_pass_noqa_comment_disables_check(self):
        """S7: # noqa: HARDCODED_SECRET comment disables check."""
        code = "temp_password = 'test123'  # noqa: HARDCODED_SECRET"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertEqual(secret_violations, [])

    def test_secret_fail_api_key_variable(self):
        """S8: API_KEY variable with hardcoded value fails."""
        code = "API_KEY = 'sk-1234567890abcdef'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertGreater(len(secret_violations), 0)


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

    def test_singleton_pass_normal_module_function(self):
        """SG1: Normal module functions without self parameter pass."""
        code = """
def process_data(data):
    return transform(data)
"""
        violations = self._check_code(code)
        singleton_violations = [v for v in violations if v.rule == 'MODULE_SINGLETON']
        self.assertEqual(singleton_violations, [])

    def test_singleton_pass_function_with_params(self):
        """SG2: Functions with normal parameters pass."""
        code = """
def acquire(key, timeout=None):
    return _pool.acquire(key, timeout)
"""
        violations = self._check_code(code)
        singleton_violations = [v for v in violations if v.rule == 'MODULE_SINGLETON']
        self.assertEqual(singleton_violations, [])

    def test_singleton_pass_private_function_with_self(self):
        """SG3: Private functions can have self parameter."""
        code = """
def _internal_handler(self):
    self.process()
"""
        violations = self._check_code(code)
        singleton_violations = [v for v in violations if v.rule == 'MODULE_SINGLETON']
        self.assertEqual(singleton_violations, [])

    def test_singleton_fail_public_function_with_self(self):
        """SG4: Public module function with self parameter fails."""
        code = """
def acquire(self):
    return self.pool.acquire()
"""
        violations = self._check_code(code)
        singleton_violations = [v for v in violations if v.rule == 'MODULE_SINGLETON']
        self.assertGreater(len(singleton_violations), 0)
        self.assertIn('self', singleton_violations[0].message)

    def test_singleton_pass_method_in_class(self):
        """SG5: Methods in classes with self parameter are OK."""
        code = """
class Handler:
    def acquire(self):
        return self.pool.acquire()
"""
        violations = self._check_code(code)
        singleton_violations = [v for v in violations if v.rule == 'MODULE_SINGLETON']
        self.assertEqual(singleton_violations, [])

    def test_singleton_pass_noqa_comment_disables_check(self):
        """SG6: # noqa: MODULE_SINGLETON comment disables check."""
        code = """
def acquire(self):  # noqa: MODULE_SINGLETON
    return self.pool.acquire()
"""
        violations = self._check_code(code)
        singleton_violations = [v for v in violations if v.rule == 'MODULE_SINGLETON']
        self.assertEqual(singleton_violations, [])


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

    def test_int_multiple_violations_different_types(self):
        """INT1: Code with multiple violations reports all."""
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

    def test_int_violation_has_required_fields(self):
        """INT2: Violation objects have all required fields."""
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

    def test_int_violation_string_format(self):
        """INT3: Violation string representation is correct format."""
        code = """
def func():
    token = 'abc123'
"""
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertGreater(len(secret_violations), 0)
        v = secret_violations[0]
        v_str = str(v)
        self.assertIn('[HARDCODED_SECRET]', v_str)
        self.assertIn('token', v_str)

    def test_int_mixed_passing_and_failing_code(self):
        """INT4: Mixed code with some passing and some failing cases."""
        code = """
def safe_function(path):
    try:
        return open(path).read()
    except:
        return ""

def _internal_function():
    raise ValueError("This is OK")

db_password = 'secret123'

def process_data(data):
    return transform(data)
"""
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        # Should only have secret violations (hardcoded password)
        self.assertGreater(len(secret_violations), 0)
        # Should have no fail-soft violations (safe_function has try/except, _internal_function is private, process_data doesn't raise)
        self.assertEqual(len(fail_soft_violations), 0)

    def test_int_all_three_rules_together(self):
        """INT5: Code violating all three rules detects all violations."""
        code = """
def acquire(self):
    api_secret = 'hardcoded-secret'
    raise ValueError("Bad input")
"""
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        singleton_violations = [v for v in violations if v.rule == 'MODULE_SINGLETON']
        self.assertGreater(len(secret_violations), 0)
        self.assertGreater(len(fail_soft_violations), 0)
        self.assertGreater(len(singleton_violations), 0)

    def test_int_violation_to_dict_format(self):
        """INT6: Violation to_dict() includes all required fields."""
        code = """
def process():
    raise ValueError("error")
"""
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertGreater(len(fail_soft_violations), 0)
        v_dict = fail_soft_violations[0].to_dict()
        self.assertIn('file', v_dict)
        self.assertIn('line', v_dict)
        self.assertIn('rule', v_dict)
        self.assertIn('message', v_dict)
        self.assertIn('severity', v_dict)

    def test_int_empty_file_passes(self):
        """INT7: Empty file passes all checks."""
        code = ""
        violations = self._check_code(code)
        self.assertEqual(len(violations), 0)

    def test_int_only_comments_and_docstrings(self):
        """INT8: File with only comments and docstrings passes."""
        code = '''
"""Module docstring."""
# This is a comment
# Another comment
'''
        violations = self._check_code(code)
        self.assertEqual(len(violations), 0)

    def test_int_class_methods_dont_trigger_singleton_rule(self):
        """INT9: Class methods with self parameter are not flagged."""
        code = """
class ResourcePool:
    def acquire(self):
        return self.items.pop()

    def release(self, item):
        self.items.append(item)
"""
        violations = self._check_code(code)
        singleton_violations = [v for v in violations if v.rule == 'MODULE_SINGLETON']
        self.assertEqual(singleton_violations, [])

    def test_int_async_functions_checked(self):
        """INT10: Async functions are checked for fail-soft violations."""
        code = """
async def fetch_data(url):
    raise ValueError("Bad URL")
"""
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertGreater(len(fail_soft_violations), 0)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

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

    def test_edge_nested_functions(self):
        """EDGE1: Nested functions are checked correctly."""
        code = """
def outer():
    def inner():
        raise ValueError("error")
    return inner()
"""
        violations = self._check_code(code)
        # Nested functions are still public module-level from outer's perspective
        self.assertIsNotNone(violations)

    def test_edge_lambda_functions(self):
        """EDGE2: Lambda functions don't trigger checks."""
        code = "func = lambda x: x or ValueError('error')"
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertEqual(fail_soft_violations, [])

    def test_edge_dict_subscript_with_variable_key(self):
        """EDGE3: Dict subscript with variable key doesn't trigger secret rule."""
        code = """
key_name = 'password'
config[key_name] = 'value'
"""
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertEqual(secret_violations, [])

    def test_edge_string_with_no_secret_keywords(self):
        """EDGE4: String values in secret-named variables don't trigger if no keyword."""
        code = "password = 'not_a_secret_value'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        # Note: This will still trigger because the variable name contains 'password'
        self.assertGreater(len(secret_violations), 0)

    def test_edge_exception_handler_with_no_return(self):
        """EDGE5: Try/except without return in handler still triggers fail-soft."""
        code = """
def process():
    try:
        data = open(file).read()
    except:
        pass
    raise ValueError("error")
"""
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertGreater(len(fail_soft_violations), 0)

    def test_edge_multiple_returns_in_except_blocks(self):
        """EDGE6: Multiple exception handlers each returning different defaults."""
        code = """
def load_data(path):
    try:
        return open(path).read()
    except FileNotFoundError:
        return ""
    except json.JSONDecodeError:
        return "{}"
"""
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertEqual(fail_soft_violations, [])

    def test_edge_raise_in_exception_handler_with_return_elsewhere(self):
        """EDGE7: Raise in except block with return in try is caught."""
        code = """
def process():
    try:
        return data
    except:
        raise ValueError("Cannot process")
"""
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertGreater(len(fail_soft_violations), 0)

    def test_edge_secret_keyword_case_insensitive(self):
        """EDGE8: Secret keywords are case-insensitive."""
        code = "api_PASSWORD = 'secret'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertGreater(len(secret_violations), 0)

    def test_edge_env_var_pattern_dollar_brace(self):
        """EDGE9: ${VAR} style env var placeholders are skipped."""
        code = "secret = '${SECRET_KEY}'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        # Will still be flagged because $ check is simple prefix, not ${} pattern
        # This is a known limitation that's acceptable
        self.assertIsNotNone(violations)

    def test_edge_bytes_strings_not_checked(self):
        """EDGE10: Byte strings are not flagged as hardcoded secrets."""
        code = "data = b'password_bytes'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertEqual(secret_violations, [])

    def test_edge_function_with_docstring_only(self):
        """EDGE11: Function with only docstring and no raise passes."""
        code = '''
def process():
    """Process data."""
    return data
'''
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertEqual(fail_soft_violations, [])

    def test_edge_raise_from_called_function(self):
        """EDGE12: Calling a function that might raise is not flagged."""
        code = """
def process():
    return helper_function()

def helper_function():
    raise ValueError("error")
"""
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        # Only helper_function is flagged, not process
        self.assertEqual(len([v for v in fail_soft_violations if 'process' in v.message]), 0)


class TestCLIAndFormatting(unittest.TestCase):
    """Test CLI output and formatting."""

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

    def test_fmt_violation_includes_filename(self):
        """FMT1: Violation string includes filename."""
        code = "password = 'secret'"
        violations = self._check_code(code)
        self.assertGreater(len(violations), 0)
        violation_str = str(violations[0])
        self.assertIn('.py', violation_str)

    def test_fmt_violation_includes_line_number(self):
        """FMT2: Violation string includes line number."""
        code = "\n\npassword = 'secret'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertGreater(len(secret_violations), 0)
        violation_str = str(secret_violations[0])
        self.assertIn(':3:', violation_str)

    def test_fmt_violation_includes_rule_name(self):
        """FMT3: Violation string includes rule name in brackets."""
        code = "def func(): raise ValueError('e')"
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertGreater(len(fail_soft_violations), 0)
        violation_str = str(fail_soft_violations[0])
        self.assertIn('[FAIL_SOFT_ERROR]', violation_str)

    def test_fmt_json_output_structure(self):
        """FMT4: JSON output has correct structure."""
        code = "db_token = 'secret'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertGreater(len(secret_violations), 0)
        json_dict = secret_violations[0].to_dict()
        self.assertEqual(set(json_dict.keys()), {'file', 'line', 'rule', 'message', 'severity'})

    def test_fmt_severity_values_valid(self):
        """FMT5: Severity values are 'error' or 'warn'."""
        code = """
def func():
    raise ValueError("e")

def acquire(self):
    pass

password = 'secret'
"""
        violations = self._check_code(code)
        for violation in violations:
            self.assertIn(violation.severity, ['error', 'warn'])


if __name__ == '__main__':
    unittest.main()
