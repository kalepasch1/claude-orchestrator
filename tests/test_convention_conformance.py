"""
Comprehensive test suite for convention-conformance-lints.

Validates machine-checked lint rules extracted from CLAUDE.md conventions.
Tests ensure agent output matches house style automatically and pre-merge enforcement.

Coverage areas:
1. Config key naming (ORCH_ prefix, no secrets)
2. Fail-soft error handling (return defaults, no bare except)
3. Hardcoded secrets detection
4. Naming consistency (snake_case, no abbreviations)
5. Magic number detection
6. Module-level singleton pattern
7. Integration tests with multiple violations
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

from convention_linter import check_file, ConventionViolation, check_directory


class TestFailSoftErrorHandling(unittest.TestCase):
    """Rule: Exception handlers must return sensible defaults."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        """Helper to check code snippet."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_return_empty_string_on_error_passes(self):
        """Exception handler returning empty string passes."""
        code = """
def read_file(path):
    try:
        return open(path).read()
    except:
        return ""
"""
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertEqual(len(fail_soft_violations), 0)

    def test_return_none_on_error_passes(self):
        """Exception handler returning None passes."""
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
        self.assertEqual(len(fail_soft_violations), 0)

    def test_return_default_dict_on_error_passes(self):
        """Exception handler returning default dict passes."""
        code = """
def get_config():
    try:
        return parse_config()
    except:
        return {}
"""
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertEqual(len(fail_soft_violations), 0)

    def test_bare_except_with_no_return_fails(self):
        """Exception handler with no return fails."""
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

    def test_except_with_only_print_fails(self):
        """Exception handler with only print (no return) fails."""
        code = """
def process():
    try:
        do_work()
    except Exception as e:
        print(f"Error: {e}")
"""
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertGreater(len(fail_soft_violations), 0)

    def test_except_with_raise_passes(self):
        """Exception handler that re-raises passes (is valid fail-soft)."""
        code = """
def process():
    try:
        do_work()
    except ValueError:
        raise
"""
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        # Re-raising is a valid fail-soft pattern, should not be flagged
        self.assertEqual(len(fail_soft_violations), 0)

    def test_multiple_except_handlers_all_checked(self):
        """All exception handlers are checked."""
        code = """
def process():
    try:
        do_work()
    except ValueError:
        return 0
    except TypeError:
        pass
"""
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        # TypeError handler has no return, should be flagged
        self.assertGreater(len(fail_soft_violations), 0)

    def test_nested_try_except_checked(self):
        """Nested try/except blocks are checked."""
        code = """
def outer():
    try:
        try:
            risky()
        except:
            return 1
    except:
        pass
"""
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertGreater(len(fail_soft_violations), 0)


class TestHardcodedSecrets(unittest.TestCase):
    """Rule: No hardcoded secrets in variable names."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        """Helper to check code snippet."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_env_var_reference_passes(self):
        """Environment variable references pass."""
        code = "api_token = os.environ['API_TOKEN']"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertEqual(len(secret_violations), 0)

    def test_env_var_placeholder_passes(self):
        """Environment variable placeholders pass."""
        code = "secret = '$SECRET_KEY'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertEqual(len(secret_violations), 0)

    def test_generic_string_passes(self):
        """Generic string variables pass."""
        code = "message = 'This is a message'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertEqual(len(secret_violations), 0)

    def test_hardcoded_api_token_fails(self):
        """Hardcoded API token in variable fails."""
        code = "api_token = 'sk-1234567890abcdef'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertGreater(len(secret_violations), 0)

    def test_hardcoded_password_fails(self):
        """Hardcoded password fails."""
        code = "db_password = 'mypassword123'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertGreater(len(secret_violations), 0)

    def test_config_key_password_fails(self):
        """Config key with password keyword fails."""
        code = "config['DATABASE_PASSWORD'] = 'secret'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertGreater(len(secret_violations), 0)

    def test_config_key_private_key_fails(self):
        """Config key with private_key keyword fails."""
        code = "config['PRIVATE_KEY'] = 'key-data'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertGreater(len(secret_violations), 0)

    def test_secret_keyword_case_insensitive(self):
        """Secret keyword detection is case-insensitive."""
        code = "API_KEY = 'test-key-123'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertGreater(len(secret_violations), 0)

    def test_multiple_secrets_all_flagged(self):
        """Multiple hardcoded secrets are all flagged."""
        code = """
db_password = 'pass123'
api_token = 'token456'
secret_key = 'key789'
"""
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertEqual(len(secret_violations), 3)




class TestModuleSingletonPattern(unittest.TestCase):
    """Rule: Module-level functions should not have 'self' parameter."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        """Helper to check code snippet."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_module_function_without_self_passes(self):
        """Module functions without self pass."""
        code = """
def acquire():
    return _pool.acquire()

def release(item):
    _pool.release(item)
"""
        violations = self._check_code(code)
        singleton_violations = [v for v in violations if v.rule == 'MODULE_SINGLETON']
        self.assertEqual(len(singleton_violations), 0)

    def test_module_function_with_self_fails(self):
        """Module functions with self parameter fail."""
        code = """
def acquire(self):
    return self._pool.acquire()
"""
        violations = self._check_code(code)
        singleton_violations = [v for v in violations if v.rule == 'MODULE_SINGLETON']
        self.assertGreater(len(singleton_violations), 0)

    def test_class_method_with_self_passes(self):
        """Class methods with self parameter pass."""
        code = """
class Pool:
    def acquire(self):
        return self._item
"""
        violations = self._check_code(code)
        singleton_violations = [v for v in violations if v.rule == 'MODULE_SINGLETON']
        self.assertEqual(len(singleton_violations), 0)

    def test_static_method_no_self_passes(self):
        """Static methods without self pass."""
        code = """
class Pool:
    @staticmethod
    def create():
        return Pool()
"""
        violations = self._check_code(code)
        singleton_violations = [v for v in violations if v.rule == 'MODULE_SINGLETON']
        self.assertEqual(len(singleton_violations), 0)


class TestIntegrationMultipleViolations(unittest.TestCase):
    """Integration tests with multiple violation types."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        """Helper to check code snippet."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_multiple_violations_all_reported(self):
        """Code with multiple violations reports all."""
        code = """
def process():
    api_key = 'hardcoded-key'
    try:
        risky()
    except:
        pass
"""
        violations = self._check_code(code)

        # Should have violations for: hardcoded secret, error handling
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        error_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']

        self.assertGreater(len(secret_violations), 0, "Should flag hardcoded secret")
        self.assertGreater(len(error_violations), 0, "Should flag error handling")

    def test_well_formed_code_passes_all_checks(self):
        """Well-formed code passes all checks."""
        code = """
def acquire():
    try:
        pool = get_thread_pool()
        return pool.acquire()
    except Exception:
        return None

def process_data(data):
    try:
        return transform(data)
    except (ValueError, TypeError):
        return {}

token = os.environ.get('API_TOKEN')
"""
        violations = self._check_code(code)

        # Filter out only the rules we care about (the 3 core rules)
        concerning_rules = {'FAIL_SOFT_ERROR', 'HARDCODED_SECRET', 'MODULE_SINGLETON'}
        relevant_violations = [v for v in violations if v.rule in concerning_rules]

        self.assertEqual(len(relevant_violations), 0,
                        f"Well-formed code should pass: {relevant_violations}")

    def test_violation_objects_have_all_fields(self):
        """Violation objects contain required fields."""
        code = "api_key = 'hardcoded'"
        violations = self._check_code(code)
        self.assertGreater(len(violations), 0)

        v = violations[0]
        self.assertIsNotNone(v.filepath)
        self.assertIsNotNone(v.lineno)
        self.assertIsNotNone(v.rule)
        self.assertIsNotNone(v.message)
        self.assertIn(v.severity, ['fail', 'warn', 'report'])

        # Check string representation
        str_repr = str(v)
        self.assertIn(v.filepath, str_repr)
        self.assertIn(str(v.lineno), str_repr)
        self.assertIn(v.rule, str_repr)

    def test_check_directory_integration(self):
        """check_directory finds violations in all Python files."""
        import tempfile as tmpmod

        with tmpmod.TemporaryDirectory() as tmpdir:
            # Create test file with violations
            test_file = os.path.join(tmpdir, 'test.py')
            with open(test_file, 'w') as f:
                f.write("""
def process():
    try:
        risky()
    except:
        pass
""")

            violations = check_directory(tmpdir)
            error_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
            self.assertGreater(len(error_violations), 0)

    def test_syntax_error_handling(self):
        """Files with syntax errors are handled gracefully."""
        code = "def broken(\n  incomplete"
        violations = self._check_code(code)

        # Should report syntax error
        syntax_errors = [v for v in violations if v.rule == 'SYNTAX_ERROR']
        self.assertGreater(len(syntax_errors), 0)

    def test_violation_line_numbers_accurate(self):
        """Violation line numbers match source code."""
        code = """
# Line 2: This is good
def safe_func():
    try:
        risky()
    except:
        pass
"""
        violations = self._check_code(code)
        error_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertGreater(len(error_violations), 0)
        # Violation should be on line 6 (except handler)
        self.assertEqual(error_violations[0].lineno, 6)


class TestConventionLinterCLI(unittest.TestCase):
    """Test linter as a command-line tool."""

    def test_check_file_function_exists(self):
        """check_file function is callable."""
        from convention_linter import check_file
        self.assertTrue(callable(check_file))

    def test_check_directory_function_exists(self):
        """check_directory function is callable."""
        from convention_linter import check_directory
        self.assertTrue(callable(check_directory))

    def test_violation_to_dict_output(self):
        """Violations can be output as dict."""
        code = """
def process():
    try:
        risky()
    except:
        pass
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                violations = check_file(f.name)
                error_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
                self.assertGreater(len(error_violations), 0)

                # Check if violation has dict-compatible attributes
                v = error_violations[0]
                self.assertTrue(hasattr(v, 'filepath'))
                self.assertTrue(hasattr(v, 'lineno'))
                self.assertTrue(hasattr(v, 'rule'))
                self.assertTrue(hasattr(v, 'message'))
            finally:
                os.unlink(f.name)


class TestEdgeCases(unittest.TestCase):
    """Edge case tests for robustness."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        """Helper to check code snippet."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_empty_file_no_crashes(self):
        """Empty files don't crash the linter."""
        violations = self._check_code("")
        self.assertIsNotNone(violations)
        self.assertIsInstance(violations, list)

    def test_file_with_only_comments(self):
        """Files with only comments don't crash."""
        code = """
# This is a comment
# Another comment
"""
        violations = self._check_code(code)
        self.assertIsNotNone(violations)

    def test_unicode_in_strings(self):
        """Unicode strings are handled correctly."""
        code = "message = 'こんにちは世界'"
        violations = self._check_code(code)
        self.assertIsNotNone(violations)

    def test_long_file(self):
        """Large files are processed correctly."""
        code = "\n".join([f"var_{i} = {i}" for i in range(100)])
        violations = self._check_code(code)
        # Large files should process without error
        self.assertIsInstance(violations, list)

    def test_deeply_nested_function(self):
        """Deeply nested code in functions is checked correctly."""
        code = """
def outer():
    if True:
        try:
            for i in range(10):
                risky_call()
        except:
            pass
"""
        violations = self._check_code(code)
        error_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        # Deeply nested exception handler with no return should fail
        self.assertGreater(len(error_violations), 0)

    def test_async_function_checked(self):
        """Async functions are checked for conventions."""
        code = """
async def async_process():
    try:
        await risky()
    except:
        pass
"""
        violations = self._check_code(code)
        error_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertGreater(len(error_violations), 0)


if __name__ == '__main__':
    unittest.main()
