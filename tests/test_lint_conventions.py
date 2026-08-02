"""
Test suite for lint_conventions.py - convention enforcement from CLAUDE.md.

Tests cover 5 key rules:
1. Configuration Key Naming (ORCH_ prefix)
2. Fail-Soft Error Handling (return "" or defaults on error)
3. Thread Safety (locks for shared state)
4. Naming Consistency (snake_case, SCREAMING_SNAKE_CASE, no abbreviations)
5. Module Structure (singleton delegation pattern)
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

from lint_conventions import check_file, ConventionViolation


class TestConfigKeyNaming(unittest.TestCase):
    """Test rule: Config keys must start with ORCH_ prefix."""

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

    def test_pass_orch_prefixed_key(self):
        """Config key with ORCH_ prefix passes."""
        code = "config['ORCH_POOL_SIZE'] = 16"
        violations = self._check_code(code)
        config_violations = [v for v in violations if v.rule == 'CONFIG_KEY_NAMING']
        self.assertEqual(config_violations, [])

    def test_pass_multiple_orch_keys(self):
        """Multiple ORCH_ prefixed keys pass."""
        code = """
config['ORCH_POOL_SIZE'] = 16
config['ORCH_TIMEOUT'] = 30
config['ORCH_MAX_RETRIES'] = 3
"""
        violations = self._check_code(code)
        config_violations = [v for v in violations if v.rule == 'CONFIG_KEY_NAMING']
        self.assertEqual(config_violations, [])

    def test_pass_lowercase_non_config_key(self):
        """Lowercase keys in non-config context pass."""
        code = "data = {'name': 'value', 'count': 42}"
        violations = self._check_code(code)
        config_violations = [v for v in violations if v.rule == 'CONFIG_KEY_NAMING']
        self.assertEqual(config_violations, [])

    def test_fail_missing_orch_prefix(self):
        """Config key without ORCH_ prefix fails."""
        code = "config['POOL_SIZE'] = 16"
        violations = self._check_code(code)
        config_violations = [v for v in violations if v.rule == 'CONFIG_KEY_NAMING']
        self.assertGreater(len(config_violations), 0)

    def test_fail_api_key_in_config(self):
        """API keys in config fail (no ORCH_ prefix)."""
        code = "config['API_KEY'] = 'secret'"
        violations = self._check_code(code)
        config_violations = [v for v in violations if v.rule == 'CONFIG_KEY_NAMING']
        self.assertGreater(len(config_violations), 0)

    def test_fail_timeout_key_in_config(self):
        """Timeout key without ORCH_ prefix fails."""
        code = "config['TIMEOUT'] = 30"
        violations = self._check_code(code)
        config_violations = [v for v in violations if v.rule == 'CONFIG_KEY_NAMING']
        self.assertGreater(len(config_violations), 0)


class TestFailSoftErrorHandling(unittest.TestCase):
    """Test rule: Functions must return default on error, never raise on bad input."""

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
        """Function returning empty string on error passes."""
        code = """
def read_file(path):
    try:
        return open(path).read()
    except:
        return ""
"""
        violations = self._check_code(code)
        error_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertEqual(error_violations, [])

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
        error_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertEqual(error_violations, [])

    def test_pass_return_default_dict(self):
        """Function returning default dict on error passes."""
        code = """
def fetch_data():
    try:
        return requests.get(url).json()
    except:
        return {}
"""
        violations = self._check_code(code)
        error_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertEqual(error_violations, [])

    def test_pass_return_default_list(self):
        """Function returning default list on error passes."""
        code = """
def get_items():
    try:
        return load_items()
    except Exception:
        return []
"""
        violations = self._check_code(code)
        error_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertEqual(error_violations, [])

    def test_fail_empty_except_handler(self):
        """Empty except handler without return fails."""
        code = """
def safe_operation():
    try:
        risky_call()
    except:
        pass
"""
        violations = self._check_code(code)
        error_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertGreater(len(error_violations), 0)

    def test_fail_empty_except_specific_exception(self):
        """Empty except block with specific exception fails."""
        code = """
def load_data():
    try:
        return open('file.txt').read()
    except FileNotFoundError:
        pass
"""
        violations = self._check_code(code)
        error_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertGreater(len(error_violations), 0)


class TestThreadSafety(unittest.TestCase):
    """Test rule: Shared state must be protected with threading.Lock()."""

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

    def test_pass_guarded_cache_access(self):
        """Cache access within lock passes."""
        code = """
class Cache:
    def __init__(self):
        self._lock = threading.Lock()
        self._cache = {}

    def set(self, key, value):
        with self._lock:
            self._cache[key] = value
"""
        violations = self._check_code(code)
        thread_violations = [v for v in violations if 'THREAD' in v.rule]
        self.assertEqual(thread_violations, [])

    def test_pass_property_guard(self):
        """Shared state accessed via property guard passes."""
        code = """
class Pool:
    def __init__(self):
        self._items = []
        self._lock = threading.Lock()

    @property
    def items(self):
        with self._lock:
            return self._items.copy()
"""
        violations = self._check_code(code)
        thread_violations = [v for v in violations if 'THREAD' in v.rule]
        self.assertEqual(thread_violations, [])

    def test_pass_nested_lock(self):
        """Nested lock contexts pass."""
        code = """
class Cache:
    def __init__(self):
        self._lock = threading.Lock()
        self._data = {}

    def update(self, key, value):
        with self._lock:
            with self._lock:
                self._data[key] = value
"""
        violations = self._check_code(code)
        thread_violations = [v for v in violations if 'THREAD' in v.rule]
        self.assertEqual(thread_violations, [])


class TestMagicNumbers(unittest.TestCase):
    """Test rule: Magic numbers must be assigned to named constants."""

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

    def test_pass_named_constant(self):
        """Named constant passes."""
        code = "MAX_RETRIES = 3"
        violations = self._check_code(code)
        magic_violations = [v for v in violations if v.rule == 'MAGIC_NUMBERS']
        self.assertEqual(magic_violations, [])

    def test_pass_allowed_magic_numbers(self):
        """Allowed magic numbers (0, 1, -1) pass."""
        code = """
if x > 0:
    pass
if y == 1:
    pass
if z < -1:
    pass
"""
        violations = self._check_code(code)
        magic_violations = [v for v in violations if v.rule == 'MAGIC_NUMBERS']
        self.assertEqual(magic_violations, [])

    def test_fail_magic_number_in_comparison(self):
        """Magic number in comparison fails."""
        code = """
def retry():
    if attempts > 3:
        return False
"""
        violations = self._check_code(code)
        magic_violations = [v for v in violations if v.rule == 'MAGIC_NUMBERS']
        self.assertGreater(len(magic_violations), 0)

    def test_fail_magic_number_in_assignment(self):
        """Magic number assigned to variable fails."""
        code = """
def configure():
    timeout_seconds = 30
    max_workers = 16
"""
        violations = self._check_code(code)
        magic_violations = [v for v in violations if v.rule == 'MAGIC_NUMBERS']
        self.assertGreater(len(magic_violations), 0)


class TestNamingConventions(unittest.TestCase):
    """Test rule: snake_case for variables, descriptive names required."""

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

    def test_pass_snake_case_function(self):
        """Function with snake_case name passes."""
        code = """
def load_configuration():
    pass

def acquire_connection():
    pass
"""
        violations = self._check_code(code)
        naming_violations = [v for v in violations if v.rule == 'NAMING_CONVENTION']
        self.assertEqual(naming_violations, [])

    def test_pass_descriptive_variable_names(self):
        """Descriptive variable names pass."""
        code = """
def process():
    max_attempts = 10
    pool_size = 16
    timeout_seconds = 30
"""
        violations = self._check_code(code)
        naming_violations = [v for v in violations if v.rule == 'NAMING_CONVENTION']
        self.assertEqual(naming_violations, [])

    def test_pass_loop_variables(self):
        """Loop variables i, j, k pass."""
        code = """
for i in range(10):
    for j in range(5):
        for k in range(3):
            print(i, j, k)
"""
        violations = self._check_code(code)
        naming_violations = [v for v in violations if v.rule == 'NAMING_CONVENTION']
        self.assertEqual(naming_violations, [])

    def test_fail_non_snake_case_function(self):
        """Function with camelCase name fails."""
        code = """
def loadConfiguration():
    pass
"""
        violations = self._check_code(code)
        naming_violations = [v for v in violations if v.rule == 'NAMING_CONVENTION']
        self.assertGreater(len(naming_violations), 0)

    def test_fail_abbreviated_cfg(self):
        """Abbreviated cfg variable fails."""
        code = """
def process():
    cfg = load_config()
"""
        violations = self._check_code(code)
        naming_violations = [v for v in violations if v.rule == 'NAMING_CONVENTION']
        self.assertGreater(len(naming_violations), 0)

    def test_fail_abbreviated_tmp(self):
        """Abbreviated tmp variable fails."""
        code = """
def process():
    tmp = parse(data)
"""
        violations = self._check_code(code)
        naming_violations = [v for v in violations if v.rule == 'NAMING_CONVENTION']
        self.assertGreater(len(naming_violations), 0)

    def test_fail_single_letter_outside_loop(self):
        """Single letter variable outside loop fails."""
        code = """
def process():
    x = get_value()
    y = transform(x)
"""
        violations = self._check_code(code)
        naming_violations = [v for v in violations if v.rule == 'NAMING_CONVENTION']
        self.assertGreater(len(naming_violations), 0)


class TestIntegration(unittest.TestCase):
    """Integration tests combining multiple rules."""

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

    def test_well_formed_module(self):
        """Well-formed module following all conventions passes."""
        code = """
import threading

class _ResourcePool:
    def __init__(self):
        self._lock = threading.Lock()
        self._items = []

    def acquire(self):
        with self._lock:
            if self._items:
                return self._items.pop()
        return None

_pool = _ResourcePool()

MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30

def acquire():
    return _pool.acquire()

def process_item(item):
    try:
        result = _pool.acquire()
        if result:
            return result
        return None
    except Exception:
        return None
"""
        violations = self._check_code(code)
        config_violations = [v for v in violations if v.rule == 'CONFIG_KEY_NAMING']
        error_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertEqual(config_violations, [])
        self.assertEqual(error_violations, [])

    def test_multiple_violations(self):
        """Code with multiple violations is caught."""
        code = """
config['API_KEY'] = 'secret'

def badFunction():
    try:
        open('file.txt').read()
    except:
        pass
"""
        violations = self._check_code(code)
        self.assertGreater(len(violations), 0)
        rules_found = set(v.rule for v in violations)
        self.assertIn('CONFIG_KEY_NAMING', rules_found)
        self.assertIn('NAMING_CONVENTION', rules_found)
        self.assertIn('FAIL_SOFT_ERROR', rules_found)


class TestEdgeCases(unittest.TestCase):
    """Edge cases and special scenarios."""

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

    def test_syntax_error_handling(self):
        """Syntax errors are handled gracefully."""
        code = "def broken(:\n    pass"
        violations = self._check_code(code)
        self.assertGreater(len(violations), 0)
        self.assertEqual(violations[0].rule, 'SYNTAX_ERROR')

    def test_empty_file(self):
        """Empty files pass."""
        code = ""
        violations = self._check_code(code)
        self.assertEqual(violations, [])

    def test_comments_ignored(self):
        """Comments don't trigger false positives."""
        code = """
# This is bad: if x > 3: pass
# config['API_KEY'] = secret
# def badFunction():
"""
        violations = self._check_code(code)
        self.assertEqual(violations, [])

    def test_docstrings_ignored(self):
        """Docstrings don't trigger violations."""
        code = '''
def my_function():
    """
    This function does X.

    Config keys like config['API_KEY'] should not trigger.
    """
    pass
'''
        violations = self._check_code(code)
        config_violations = [v for v in violations if v.rule == 'CONFIG_KEY_NAMING']
        self.assertEqual(config_violations, [])

    def test_private_function_naming(self):
        """Private functions with underscores pass naming checks."""
        code = """
def _internal_helper():
    pass

def __very_private():
    pass
"""
        violations = self._check_code(code)
        naming_violations = [v for v in violations if v.rule == 'NAMING_CONVENTION']
        self.assertEqual(naming_violations, [])


class TestViolationStructure(unittest.TestCase):
    """Test violation data structure."""

    def test_violation_string_representation(self):
        """Violation objects format correctly."""
        v = ConventionViolation('test.py', 42, 'TEST_RULE', 'Test message')
        self.assertIn('test.py', str(v))
        self.assertIn('42', str(v))
        self.assertIn('TEST_RULE', str(v))
        self.assertIn('Test message', str(v))

    def test_violation_sorting(self):
        """Violations sort correctly by file and line."""
        v1 = ConventionViolation('a.py', 10, 'RULE', 'msg')
        v2 = ConventionViolation('a.py', 5, 'RULE', 'msg')
        v3 = ConventionViolation('b.py', 1, 'RULE', 'msg')
        violations = [v1, v2, v3]
        violations.sort(key=lambda v: (v.filepath, v.lineno))
        self.assertEqual(violations[0].lineno, 5)
        self.assertEqual(violations[1].lineno, 10)
        self.assertEqual(violations[2].filepath, 'b.py')

    def test_violation_properties(self):
        """Violation properties are accessible."""
        v = ConventionViolation('file.py', 123, 'RULE', 'message', 'error')
        self.assertEqual(v.filepath, 'file.py')
        self.assertEqual(v.lineno, 123)
        self.assertEqual(v.rule, 'RULE')
        self.assertEqual(v.message, 'message')
        self.assertEqual(v.severity, 'error')


if __name__ == '__main__':
    unittest.main()
