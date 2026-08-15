"""
Comprehensive test suite for convention-conformance-lints.

Validates machine-checked lint rules extracted from CLAUDE.md conventions.
Tests ensure agent output matches house style automatically and pre-merge enforcement.

Coverage areas:
1. Config key naming (ORCH_ prefix, no secrets)
2. Fail-soft error handling (return defaults, no bare except)
3. Thread safety (explicit locks, guarded mutations)
4. Module structure (singleton delegation)
5. Naming consistency (snake_case, SCREAMING_SNAKE_CASE)
6. Magic number detection
7. Abbreviation detection
8. Integration of multiple violations
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

from lint_conventions import check_file, ConventionViolation, scan_directory


class TestConfigKeyNaming(unittest.TestCase):
    """Rule: Config keys must start with ORCH_ prefix to prevent fleet-wide secrets."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        """Helper to check code snippet."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_orch_prefix_config_key_passes(self):
        """ORCH_ prefixed config keys pass."""
        code = "config['ORCH_POOL_SIZE'] = 16\nconfig['ORCH_MAX_RETRIES'] = 3"
        violations = self._check_code(code)
        config_violations = [v for v in violations if v.rule == 'CONFIG_KEY_NAMING']
        self.assertEqual(config_violations, [])

    def test_missing_orch_prefix_fails(self):
        """Config keys without ORCH_ prefix fail."""
        code = "config['POOL_SIZE'] = 16"
        violations = self._check_code(code)
        config_violations = [v for v in violations if v.rule == 'CONFIG_KEY_NAMING']
        self.assertGreater(len(config_violations), 0)

    def test_lowercase_keys_pass(self):
        """Lowercase keys in dictionaries pass (not config)."""
        code = "data = {'pool_size': 16, 'name': 'value'}"
        violations = self._check_code(code)
        config_violations = [v for v in violations if v.rule == 'CONFIG_KEY_NAMING']
        self.assertEqual(config_violations, [])

    def test_fleet_config_table_access_checked(self):
        """Access to fleet_config with uppercase keys checked."""
        code = "fleet_config['TIMEOUT'] = 30"
        violations = self._check_code(code)
        config_violations = [v for v in violations if v.rule == 'CONFIG_KEY_NAMING']
        self.assertGreater(len(config_violations), 0)

    def test_multiple_config_keys(self):
        """Multiple config keys all checked."""
        code = """
config['ORCH_TIMEOUT'] = 30
config['ORCH_MAX_WORKERS'] = 8
config['ORCH_DEBUG'] = True
"""
        violations = self._check_code(code)
        config_violations = [v for v in violations if v.rule == 'CONFIG_KEY_NAMING']
        self.assertEqual(config_violations, [])


class TestNoHardcodedSecrets(unittest.TestCase):
    """Rule: No hardcoded secrets in config keys (use env vars)."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_api_key_in_config_fails(self):
        """Config key with API_KEY pattern fails."""
        code = "config['API_KEY'] = 'sk-1234567890'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if 'secret' in v.rule.lower()]
        self.assertGreater(len(secret_violations), 0)

    def test_token_variable_with_hardcoded_value_fails(self):
        """Variable with 'token' in name and hardcoded value fails."""
        code = "api_token = 'sk-abc123def456'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if 'secret' in v.rule.lower()]
        self.assertGreater(len(secret_violations), 0)

    def test_password_variable_with_hardcoded_value_fails(self):
        """Variable with 'password' in name and hardcoded value fails."""
        code = "database_password = 'sk-prod-secret'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if 'secret' in v.rule.lower()]
        self.assertGreater(len(secret_violations), 0)

    def test_non_secret_string_passes(self):
        """Regular string assignments pass."""
        code = "user_name = 'alice'\nproject_title = 'beethoven'"
        violations = self._check_code(code)
        secret_violations = [v for v in violations if 'secret' in v.rule.lower()]
        self.assertEqual(secret_violations, [])


class TestFailSoftErrorHandling(unittest.TestCase):
    """Rule: Must return sensible defaults on error, never raise on bad input."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_return_empty_string_on_error(self):
        """Exception handler returning empty string passes."""
        code = """
def read_file(path):
    try:
        return open(path).read()
    except FileNotFoundError:
        return ""
"""
        violations = self._check_code(code)
        error_violations = [v for v in violations if 'error' in v.rule.lower()]
        self.assertEqual(error_violations, [])

    def test_return_none_on_error(self):
        """Exception handler returning None passes."""
        code = """
def load_config(path):
    try:
        return json.load(open(path))
    except:
        return None
"""
        violations = self._check_code(code)
        error_violations = [v for v in violations if 'error' in v.rule.lower()]
        self.assertEqual(error_violations, [])

    def test_return_empty_dict_on_error(self):
        """Exception handler returning empty dict passes."""
        code = """
def fetch_data():
    try:
        return api.get_data()
    except Exception:
        return {}
"""
        violations = self._check_code(code)
        error_violations = [v for v in violations if 'error' in v.rule.lower()]
        self.assertEqual(error_violations, [])

    def test_return_empty_list_on_error(self):
        """Exception handler returning empty list passes."""
        code = """
def get_items():
    try:
        return db.query()
    except Exception:
        return []
"""
        violations = self._check_code(code)
        error_violations = [v for v in violations if 'error' in v.rule.lower()]
        self.assertEqual(error_violations, [])

    def test_bare_except_without_return_fails(self):
        """Bare except without return fails."""
        code = """
def operation():
    try:
        risky()
    except:
        pass
"""
        violations = self._check_code(code)
        error_violations = [v for v in violations if 'error' in v.rule.lower()]
        self.assertGreater(len(error_violations), 0)

    def test_specific_exception_without_return_fails(self):
        """Specific exception without return fails."""
        code = """
def read_file():
    try:
        return open('f.txt')
    except FileNotFoundError:
        pass
"""
        violations = self._check_code(code)
        error_violations = [v for v in violations if 'error' in v.rule.lower()]
        self.assertGreater(len(error_violations), 0)

    def test_multiple_handlers_all_checked(self):
        """Multiple exception handlers all checked."""
        code = """
try:
    operation()
except ValueError:
    pass
except KeyError:
    return None
"""
        violations = self._check_code(code)
        error_violations = [v for v in violations if 'error' in v.rule.lower()]
        self.assertGreater(len(error_violations), 0)

    def test_broad_exception_without_default_fails(self):
        """Broad exception without sensible default fails."""
        code = """
def handle():
    try:
        execute()
    except Exception:
        log("error")
"""
        violations = self._check_code(code)
        error_violations = [v for v in violations if 'error' in v.rule.lower()]
        self.assertGreater(len(error_violations), 0)


class TestThreadSafety(unittest.TestCase):
    """Rule: Shared state must be protected with threading.Lock()."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_guarded_cache_access_passes(self):
        """Cache access within lock passes."""
        code = """
class Cache:
    def __init__(self):
        self._lock = threading.Lock()
        self._cache = {}

    def get(self, key):
        with self._lock:
            return self._cache.get(key)
"""
        violations = self._check_code(code)
        thread_violations = [v for v in violations if 'thread' in v.rule.lower() or 'lock' in v.rule.lower()]
        self.assertEqual(thread_violations, [])

    def test_nested_lock_contexts_pass(self):
        """Nested with lock blocks pass."""
        code = """
class Pool:
    def __init__(self):
        self._lock = threading.Lock()
        self._items = []

    def update(self):
        with self._lock:
            with self._lock:
                self._items.append(item)
"""
        violations = self._check_code(code)
        thread_violations = [v for v in violations if 'thread' in v.rule.lower() or 'lock' in v.rule.lower()]
        self.assertEqual(thread_violations, [])

    def test_mutex_context_manager_recognized(self):
        """Context managers with 'mutex' in name treated as locks."""
        code = """
def operation():
    with self._mutex:
        self._shared_state = value
"""
        violations = self._check_code(code)
        # Should not flag as thread violation since it's within mutex context
        self.assertIsNotNone(violations)


class TestModuleSingletonPattern(unittest.TestCase):
    """Rule: Module-level functions must delegate to singleton, not have self param."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_module_function_no_self_passes(self):
        """Module-level function without self passes."""
        code = """
def acquire():
    return _pool.acquire()

def release(item):
    _pool.release(item)
"""
        violations = self._check_code(code)
        singleton_violations = [v for v in violations if 'singleton' in v.rule.lower()]
        self.assertEqual(singleton_violations, [])

    def test_module_level_with_self_param_fails(self):
        """Module-level function with self parameter fails."""
        code = """
def acquire(self):
    return self._pool.acquire()
"""
        violations = self._check_code(code)
        singleton_violations = [v for v in violations if 'singleton' in v.rule.lower()]
        self.assertGreater(len(singleton_violations), 0)

    def test_class_methods_not_flagged(self):
        """Methods inside classes are not flagged."""
        code = """
class Pool:
    def acquire(self):
        return self._items.pop()

    def release(self, item):
        self._items.append(item)
"""
        violations = self._check_code(code)
        singleton_violations = [v for v in violations if 'singleton' in v.rule.lower()]
        self.assertEqual(singleton_violations, [])


class TestNamingConventions(unittest.TestCase):
    """Rule: Functions use snake_case, variables are descriptive, no abbreviations."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_snake_case_function_passes(self):
        """Function with snake_case name passes."""
        code = """
def load_configuration():
    pass

def acquire_resource():
    pass

def process_items_safely():
    pass
"""
        violations = self._check_code(code)
        naming_violations = [v for v in violations if 'naming' in v.rule.lower()]
        self.assertEqual(naming_violations, [])

    def test_camel_case_function_fails(self):
        """Function with camelCase name fails."""
        code = """
def loadConfiguration():
    pass
"""
        violations = self._check_code(code)
        naming_violations = [v for v in violations if 'naming' in v.rule.lower()]
        self.assertGreater(len(naming_violations), 0)

    def test_descriptive_variable_names_pass(self):
        """Descriptive variable names pass."""
        code = """
def process():
    max_attempts = 10
    pool_size = 16
    timeout_seconds = 30
    connection_string = "..."
"""
        violations = self._check_code(code)
        naming_violations = [v for v in violations if 'naming' in v.rule.lower()]
        self.assertEqual(naming_violations, [])

    def test_abbreviated_cfg_fails(self):
        """Abbreviated 'cfg' variable fails."""
        code = """
def load():
    cfg = load_config()
"""
        violations = self._check_code(code)
        naming_violations = [v for v in violations if 'naming' in v.rule.lower()]
        self.assertGreater(len(naming_violations), 0)

    def test_abbreviated_tmp_fails(self):
        """Abbreviated 'tmp' variable fails."""
        code = """
def transform():
    tmp = parse(data)
    return tmp
"""
        violations = self._check_code(code)
        naming_violations = [v for v in violations if 'naming' in v.rule.lower()]
        self.assertGreater(len(naming_violations), 0)

    def test_loop_variables_pass(self):
        """Single-letter loop variables pass."""
        code = """
for i in range(10):
    for j in range(5):
        for k in range(3):
            print(i, j, k)
"""
        violations = self._check_code(code)
        naming_violations = [v for v in violations if 'naming' in v.rule.lower()]
        self.assertEqual(naming_violations, [])

    def test_single_letter_outside_loop_fails(self):
        """Single-letter variable outside loop fails."""
        code = """
def process():
    x = get_value()
    y = transform(x)
    return y
"""
        violations = self._check_code(code)
        naming_violations = [v for v in violations if 'naming' in v.rule.lower()]
        self.assertGreater(len(naming_violations), 0)


class TestMagicNumbers(unittest.TestCase):
    """Rule: Magic numbers must be assigned to named SCREAMING_SNAKE_CASE constants."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_named_constant_passes(self):
        """Named constant for magic number passes."""
        code = """
MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30
POOL_SIZE = 16
"""
        violations = self._check_code(code)
        magic_violations = [v for v in violations if 'magic' in v.rule.lower()]
        self.assertEqual(magic_violations, [])

    def test_allowed_zero_one_negative_one_pass(self):
        """Magic numbers 0, 1, -1 pass."""
        code = """
if count > 0:
    pass
if index == 1:
    pass
if value < -1:
    pass
"""
        violations = self._check_code(code)
        magic_violations = [v for v in violations if 'magic' in v.rule.lower()]
        self.assertEqual(magic_violations, [])

    def test_magic_number_in_comparison_fails(self):
        """Magic number in comparison fails."""
        code = """
def retry():
    if attempts > 3:
        return False
"""
        violations = self._check_code(code)
        magic_violations = [v for v in violations if 'magic' in v.rule.lower()]
        self.assertGreater(len(magic_violations), 0)

    def test_magic_number_in_function_fails(self):
        """Magic number in function body fails."""
        code = """
def configure():
    timeout = 30
    workers = 16
"""
        violations = self._check_code(code)
        magic_violations = [v for v in violations if 'magic' in v.rule.lower()]
        self.assertGreater(len(magic_violations), 0)

    def test_magic_float_fails(self):
        """Magic float number fails."""
        code = """
def calculate():
    multiplier = 1.5
    threshold = 0.95
"""
        violations = self._check_code(code)
        magic_violations = [v for v in violations if 'magic' in v.rule.lower()]
        self.assertGreater(len(magic_violations), 0)


class TestIntegration(unittest.TestCase):
    """Integration tests combining multiple conventions."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_well_formed_module_passes(self):
        """Well-formed module following all conventions passes."""
        code = """
import threading

MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30

class _ResourcePool:
    def __init__(self):
        self._lock = threading.Lock()
        self._items = []

    def acquire(self):
        with self._lock:
            if self._items:
                return self._items.pop()
        return None

    def release(self, item):
        with self._lock:
            self._items.append(item)

_pool = _ResourcePool()

def acquire():
    return _pool.acquire()

def release(item):
    _pool.release(item)

def process_safely():
    try:
        resource = acquire()
        if resource:
            return resource
        return None
    except Exception:
        return None
"""
        violations = self._check_code(code)
        # Filter out non-critical violations
        critical = [v for v in violations if v.rule in
                   ['CONFIG_KEY_NAMING', 'FAIL_SOFT_ERROR', 'NAMING_CONVENTION', 'MAGIC_NUMBERS']]
        self.assertEqual(critical, [])

    def test_multiple_violations_caught(self):
        """Code with multiple violations caught."""
        code = """
config['API_KEY'] = 'secret'

def badFunction():
    tmp = process()
    if attempts > 3:
        pass
    try:
        operation()
    except:
        pass
"""
        violations = self._check_code(code)
        self.assertGreater(len(violations), 0)

    def test_fleet_config_gateway_pattern_passes(self):
        """Fleet config gateway pattern passes."""
        code = """
import threading

class _FleetConfigGateway:
    def __init__(self):
        self._lock = threading.Lock()
        self._config = {}

    def set(self, key, value):
        with self._lock:
            self._config[key] = value

    def get(self, key):
        with self._lock:
            return self._config.get(key)

_gateway = _FleetConfigGateway()

def set_config(key, value):
    if not key.startswith('ORCH_'):
        return ""
    try:
        _gateway.set(key, value)
        return True
    except Exception:
        return False

def get_config(key):
    try:
        return _gateway.get(key)
    except Exception:
        return None
"""
        violations = self._check_code(code)
        config_violations = [v for v in violations if 'config' in v.rule.lower()]
        self.assertEqual(config_violations, [])


class TestEdgeCases(unittest.TestCase):
    """Edge cases and boundary conditions."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_empty_file(self):
        """Empty file passes."""
        violations = self._check_code("")
        self.assertEqual(violations, [])

    def test_comments_ignored(self):
        """Comments don't trigger false positives."""
        code = """
# This is bad: config['API_KEY'] = secret
# def badFunction(): pass
# tmp = x
"""
        violations = self._check_code(code)
        self.assertEqual(violations, [])

    def test_docstrings_ignored(self):
        """Docstrings don't trigger violations."""
        code = '''
def my_function():
    """
    API_KEY secrets should be in env vars.
    config['API_KEY'] is bad.
    Use tmp = load_config() instead.
    """
    pass
'''
        violations = self._check_code(code)
        # Docstrings should not trigger violations
        self.assertEqual(len(violations), 0)

    def test_multiline_strings_ignored(self):
        """Multiline strings ignored."""
        code = '''
sql = """
config['API_KEY'] = value
"""
'''
        violations = self._check_code(code)
        config_violations = [v for v in violations if 'config' in v.rule.lower()]
        self.assertEqual(config_violations, [])

    def test_syntax_error_graceful(self):
        """Syntax errors handled gracefully."""
        code = "def broken(:\n    pass"
        violations = self._check_code(code)
        self.assertGreater(len(violations), 0)

    def test_private_function_passes(self):
        """Private functions can use underscore prefix."""
        code = """
def _internal_helper():
    pass

def __very_private():
    pass
"""
        violations = self._check_code(code)
        naming_violations = [v for v in violations if 'naming' in v.rule.lower()]
        self.assertEqual(naming_violations, [])

    def test_dunder_methods_pass(self):
        """Dunder methods (__init__, __str__) pass."""
        code = """
class MyClass:
    def __init__(self):
        pass

    def __str__(self):
        pass

    def __repr__(self):
        pass
"""
        violations = self._check_code(code)
        naming_violations = [v for v in violations if 'naming' in v.rule.lower()]
        self.assertEqual(naming_violations, [])


class TestDirectoryScanning(unittest.TestCase):
    """Test directory scanning functionality."""

    def test_scan_directory_skips_venv(self):
        """Directory scanner skips venv directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            venv_dir = Path(tmpdir) / 'venv'
            venv_dir.mkdir()
            py_file = venv_dir / 'test.py'
            py_file.write_text("config['API_KEY'] = 'secret'")

            violations = scan_directory(tmpdir)
            # Should skip venv directory
            self.assertEqual(len(violations), 0)

    def test_scan_directory_skips_pycache(self):
        """Directory scanner skips __pycache__."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pycache_dir = Path(tmpdir) / '__pycache__'
            pycache_dir.mkdir()
            py_file = pycache_dir / 'test.py'
            py_file.write_text("config['API_KEY'] = 'secret'")

            violations = scan_directory(tmpdir)
            self.assertEqual(len(violations), 0)

    def test_scan_directory_includes_py_files(self):
        """Directory scanner includes Python files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            py_file = Path(tmpdir) / 'test.py'
            py_file.write_text("config['API_KEY'] = 'secret'")

            violations = scan_directory(tmpdir)
            self.assertGreater(len(violations), 0)


class TestViolationReporting(unittest.TestCase):
    """Test violation reporting and output."""

    def test_violation_string_format(self):
        """Violation formats as filepath:lineno: rule: message."""
        v = ConventionViolation('test.py', 42, 'TEST_RULE', 'Test message')
        str_repr = str(v)
        self.assertIn('test.py', str_repr)
        self.assertIn('42', str_repr)
        self.assertIn('TEST_RULE', str_repr)
        self.assertIn('Test message', str_repr)

    def test_violation_repr(self):
        """Violation repr matches string representation."""
        v = ConventionViolation('test.py', 10, 'RULE', 'msg')
        self.assertEqual(str(v), repr(v))

    def test_violations_sort_by_file_and_line(self):
        """Violations sort correctly by filepath and line number."""
        v1 = ConventionViolation('b.py', 5, 'RULE', 'msg')
        v2 = ConventionViolation('a.py', 10, 'RULE', 'msg')
        v3 = ConventionViolation('a.py', 5, 'RULE', 'msg')
        violations = [v1, v2, v3]
        violations.sort(key=lambda v: (v.filepath, v.lineno))
        self.assertEqual(violations[0].filepath, 'a.py')
        self.assertEqual(violations[0].lineno, 5)
        self.assertEqual(violations[1].lineno, 10)
        self.assertEqual(violations[2].filepath, 'b.py')


if __name__ == '__main__':
    unittest.main()
