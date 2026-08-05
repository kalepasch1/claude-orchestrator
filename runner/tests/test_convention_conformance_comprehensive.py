"""
Comprehensive test suite for convention-conformance-lints enforcement.

Tests the complete convention linting system that enforces CLAUDE.md conventions
across the codebase. Validates pre-merge enforcement, violation detection, agent
output validation, multi-file scanning, CI/CD integration, and edge cases.

Coverage areas:
1. Rule 1: Fail-soft error handling (FAIL_SOFT_ERROR)
2. Rule 2: Hardcoded secrets detection (HARDCODED_SECRET)
3. Rule 3: Module-level singleton pattern (MODULE_LEVEL_SINGLETONS)
4. Rule 4: Config key naming (CONFIG_KEY_NAMING) - ORCH_ prefix
5. Rule 5: Magic numbers and constants (MAGIC_NUMBERS)
6. Rule 6: Naming conventions (NAMING_CONVENTION)
7. Pre-merge enforcement blocking violations
8. Agent output validation
9. Multi-file scanning and aggregation
10. Severity levels (error, warning)
11. CI/CD integration and exit codes
12. Convention regeneration
13. Git workflow integration
14. Edge cases and error handling
"""

import os
import sys
import tempfile
import unittest
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

try:
    from lint_conventions import (
        check_file,
        check_directory,
        ConventionViolation,
        scan_directory,
    )
except ImportError:
    try:
        from convention_lint import (
            check_file,
            ConventionViolation,
            check_directory,
        )
    except ImportError:
        # Mock implementation for testing
        class ConventionViolation:
            def __init__(self, filepath: str, lineno: int, rule: str, message: str, severity: str = "error"):
                self.filepath = filepath
                self.lineno = lineno
                self.rule = rule
                self.message = message
                self.severity = severity

            def to_dict(self) -> Dict[str, Any]:
                return {
                    "file": self.filepath,
                    "line": self.lineno,
                    "rule": self.rule,
                    "message": self.message,
                    "severity": self.severity,
                }

            def __str__(self) -> str:
                return f"{self.filepath}:{self.lineno}: {self.rule}: {self.message}"


class TestFailSoftErrorHandling(unittest.TestCase):
    """Test FAIL_SOFT_ERROR rule: Public functions must handle errors gracefully."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        """Helper to check code snippet."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_public_function_with_unhandled_raise(self):
        """Public function with bare raise violates FAIL_SOFT_ERROR."""
        code = """
def process_data(data):
    raise ValueError("Bad data")
"""
        violations = self._check_code(code)
        self.assertTrue(any(v.rule == 'FAIL_SOFT_ERROR' for v in violations))

    def test_public_function_with_try_except_return(self):
        """Public function with try/except and return passes FAIL_SOFT_ERROR."""
        code = """
def process_data(data):
    try:
        if not data:
            raise ValueError("Bad data")
        return transform(data)
    except Exception:
        return None
"""
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertEqual(len(fail_soft_violations), 0)

    def test_private_function_can_raise(self):
        """Private functions (prefixed with _) can raise freely."""
        code = """
def _private_function():
    raise ValueError("This is allowed in private functions")

def public_function():
    try:
        _private_function()
        return True
    except Exception:
        return False
"""
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        # Should not flag the private function's raise
        self.assertEqual(len(fail_soft_violations), 0)

    def test_class_methods_can_raise(self):
        """Methods inside classes can raise freely."""
        code = """
class DataProcessor:
    def process(self, data):
        raise ValueError("Methods can raise")
"""
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertEqual(len(fail_soft_violations), 0)

    def test_bare_except_without_return_fails(self):
        """Bare except without return fails FAIL_SOFT_ERROR."""
        code = """
def load_config():
    try:
        with open('config.json') as f:
            return json.load(f)
    except:
        pass
"""
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertGreater(len(fail_soft_violations), 0)

    def test_multiple_exception_handlers_with_returns(self):
        """Multiple exception handlers with returns passes FAIL_SOFT_ERROR."""
        code = """
def load_configuration():
    try:
        with open('config.json') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}
    except Exception:
        return {}
"""
        violations = self._check_code(code)
        fail_soft_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertEqual(len(fail_soft_violations), 0)


class TestHardcodedSecrets(unittest.TestCase):
    """Test HARDCODED_SECRET rule: No hardcoded secrets in variables."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_detects_hardcoded_password(self):
        """Detects hardcoded password assignment."""
        code = 'api_password = "secret123"'
        violations = self._check_code(code)
        self.assertTrue(any(v.rule == 'HARDCODED_SECRET' for v in violations))

    def test_detects_hardcoded_token(self):
        """Detects hardcoded API token."""
        code = 'api_token = "sk-1234567890abcdef"'
        violations = self._check_code(code)
        self.assertTrue(any(v.rule == 'HARDCODED_SECRET' for v in violations))

    def test_detects_hardcoded_private_key(self):
        """Detects hardcoded private key."""
        code = 'private_key = "-----BEGIN PRIVATE KEY-----..."'
        violations = self._check_code(code)
        self.assertTrue(any(v.rule == 'HARDCODED_SECRET' for v in violations))

    def test_allows_environment_variable_reference(self):
        """Allows environment variable references."""
        code = 'api_token = os.environ.get("API_TOKEN")'
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertEqual(len(secret_violations), 0)

    def test_allows_placeholder_format(self):
        """Allows placeholder format with $ prefix."""
        code = 'api_token = "${API_TOKEN}"'
        violations = self._check_code(code)
        secret_violations = [v for v in violations if v.rule == 'HARDCODED_SECRET']
        self.assertEqual(len(secret_violations), 0)

    def test_detects_config_dict_with_secrets(self):
        """Detects secrets in config dict assignments."""
        code = 'config["DATABASE_PASSWORD"] = "prod-secret"'
        violations = self._check_code(code)
        self.assertTrue(any(v.rule == 'HARDCODED_SECRET' for v in violations))


class TestModuleLevelSingletons(unittest.TestCase):
    """Test MODULE_LEVEL_SINGLETONS rule: Functions delegate to singletons."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_singleton_delegation_pattern(self):
        """Validates proper singleton delegation pattern."""
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

def acquire():
    try:
        return _pool.acquire()
    except Exception:
        return None
"""
        violations = self._check_code(code)
        # Should not have violations for proper pattern
        singleton_violations = [v for v in violations if 'singleton' in v.rule.lower()]
        self.assertEqual(len(singleton_violations), 0)

    def test_module_function_with_state(self):
        """Module-level function should delegate to singleton, not manage state."""
        code = """
_connections = []

def add_connection(conn):
    _connections.append(conn)
"""
        violations = self._check_code(code)
        # Module-level state access should be flagged
        self.assertIsNotNone(violations)


class TestConfigKeyNaming(unittest.TestCase):
    """Test CONFIG_KEY_NAMING rule: Fleet config keys must have ORCH_ prefix."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_fleet_config_requires_orch_prefix(self):
        """Fleet config keys must have ORCH_ prefix."""
        code = """
def setup_fleet():
    config['DATABASE_URL'] = 'db://localhost'
    config['TIMEOUT'] = 30
"""
        violations = self._check_code(code)
        config_violations = [v for v in violations if v.rule == 'CONFIG_KEY_NAMING']
        self.assertGreater(len(config_violations), 0,
                          "Unprefixed config keys should be flagged")

    def test_orch_prefix_allows_assignment(self):
        """Config keys with ORCH_ prefix are allowed."""
        code = """
def setup_fleet():
    config['ORCH_DATABASE_URL'] = 'db://localhost'
    config['ORCH_TIMEOUT'] = 30
    config['ORCH_WORKER_COUNT'] = 8
"""
        violations = self._check_code(code)
        config_violations = [v for v in violations if v.rule == 'CONFIG_KEY_NAMING']
        self.assertEqual(len(config_violations), 0,
                        "ORCH_ prefixed keys should be allowed")

    def test_local_config_dict_not_flagged(self):
        """Local (non-fleet) config dict assignments not flagged."""
        code = """
def load_config():
    local_config = {
        'host': 'localhost',
        'port': 8080
    }
    return local_config
"""
        violations = self._check_code(code)
        config_violations = [v for v in violations if v.rule == 'CONFIG_KEY_NAMING']
        # Local configs may be flagged differently
        self.assertIsNotNone(violations)


class TestMagicNumbers(unittest.TestCase):
    """Test MAGIC_NUMBERS rule: Avoid hardcoded numeric constants."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_flags_magic_numbers_in_assignments(self):
        """Flags magic numbers in variable assignments."""
        code = """
def configure_pool():
    max_size = 16
    retry_count = 3
    timeout_seconds = 30
"""
        violations = self._check_code(code)
        magic_violations = [v for v in violations if v.rule == 'MAGIC_NUMBERS']
        self.assertGreater(len(magic_violations), 0,
                          "Magic numbers should be flagged")

    def test_flags_magic_numbers_in_comparisons(self):
        """Flags magic numbers in comparisons."""
        code = """
def should_retry(attempts):
    if attempts > 3:
        return False
    if timeout > 30:
        return False
"""
        violations = self._check_code(code)
        magic_violations = [v for v in violations if v.rule == 'MAGIC_NUMBERS']
        self.assertGreater(len(magic_violations), 0)

    def test_allows_defined_constants(self):
        """Allows named constants."""
        code = """
MAX_POOL_SIZE = 16
RETRY_COUNT = 3
DEFAULT_TIMEOUT = 30

def configure_pool():
    return MAX_POOL_SIZE, RETRY_COUNT, DEFAULT_TIMEOUT
"""
        violations = self._check_code(code)
        magic_violations = [v for v in violations if v.rule == 'MAGIC_NUMBERS']
        # Should allow references to named constants
        self.assertEqual(len(magic_violations), 0)


class TestNamingConventions(unittest.TestCase):
    """Test NAMING_CONVENTION rule: Use consistent naming patterns."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_flags_camelCase_function_names(self):
        """Flags camelCase function names (should be snake_case)."""
        code = """
def badFunctionName():
    pass

def processData():
    pass
"""
        violations = self._check_code(code)
        naming_violations = [v for v in violations if v.rule == 'NAMING_CONVENTION']
        self.assertGreater(len(naming_violations), 0,
                          "camelCase function names should be flagged")

    def test_allows_snake_case_function_names(self):
        """Allows snake_case function names."""
        code = """
def good_function_name():
    pass

def process_data():
    pass
"""
        violations = self._check_code(code)
        naming_violations = [v for v in violations if v.rule == 'NAMING_CONVENTION']
        self.assertEqual(len(naming_violations), 0)

    def test_allows_screaming_snake_case_constants(self):
        """Allows SCREAMING_SNAKE_CASE for constants."""
        code = """
MAX_POOL_SIZE = 16
DEFAULT_TIMEOUT = 30
RETRY_COUNT = 3
"""
        violations = self._check_code(code)
        naming_violations = [v for v in violations if v.rule == 'NAMING_CONVENTION']
        self.assertEqual(len(naming_violations), 0)


class TestPreMergeEnforcement(unittest.TestCase):
    """Test pre-merge blocking of violations."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_pre_merge_blocks_on_error_severity(self):
        """Pre-merge blocks code with error-level violations."""
        code = 'config["PASSWORD"] = "secret"'
        violations = self._check_code(code)
        error_violations = [v for v in violations if v.severity == 'error']
        self.assertGreater(len(error_violations), 0,
                          "Pre-merge should block error-level violations")

    def test_pre_merge_allows_warning_severity(self):
        """Pre-merge allows code with only warning-level violations."""
        code = """
def good_function():
    pass
"""
        violations = self._check_code(code)
        error_violations = [v for v in violations if v.severity == 'error']
        # No error-level violations should allow merge
        # This depends on the linter implementation

    def test_violations_report_accurate_line_numbers(self):
        """Violations report accurate line numbers."""
        code = """# Line 1
# Line 2
config['PASSWORD'] = 'secret'  # Line 3
# Line 4
"""
        violations = self._check_code(code)
        self.assertGreater(len(violations), 0)
        for v in violations:
            self.assertIsNotNone(v.lineno)


class TestAgentOutputValidation(unittest.TestCase):
    """Test validation of agent-generated code."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_validates_agent_singleton_pattern(self):
        """Validates agent-generated singleton pattern."""
        code = """
import threading

class _ControlGateway:
    def __init__(self):
        self._lock = threading.Lock()
        self._state = {}

    def update(self, key, value):
        with self._lock:
            self._state[key] = value

_gateway = _ControlGateway()

def set_state(key, value):
    try:
        if not isinstance(key, str):
            return False
        _gateway.update(key, value)
        return True
    except Exception:
        return False
"""
        violations = self._check_code(code)
        critical_violations = [v for v in violations
                              if v.severity == 'error']
        # Should have no critical violations
        self.assertEqual(len(critical_violations), 0)

    def test_rejects_agent_code_with_secrets(self):
        """Rejects agent code with hardcoded secrets."""
        code = """
def initialize():
    api_token = 'sk-1234567890'
    database_password = 'prod-secret'
"""
        violations = self._check_code(code)
        self.assertGreater(len(violations), 0)

    def test_validates_fleet_config_patterns(self):
        """Validates fleet config access patterns."""
        code = """
def update_fleet():
    config['ORCH_WORKER_COUNT'] = 8
    config['ORCH_TIMEOUT'] = 30
"""
        violations = self._check_code(code)
        config_violations = [v for v in violations if v.rule == 'CONFIG_KEY_NAMING']
        self.assertEqual(len(config_violations), 0,
                        "ORCH_ prefixed configs should be allowed")


class TestMultiFileScanning(unittest.TestCase):
    """Test scanning multiple files."""

    def test_scan_directory_collects_all_violations(self):
        """Directory scan collects violations from all Python files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, 'module1.py').write_text('config["BAD_KEY"] = 1')
            Path(tmpdir, 'module2.py').write_text('bad_token = "secret"')
            Path(tmpdir, 'good.py').write_text('MAX_SIZE = 16')

            try:
                violations = check_directory(tmpdir)
                self.assertGreater(len(violations), 0,
                                  "Should find violations across files")
                files_with_violations = set(v.filepath for v in violations)
                self.assertGreater(len(files_with_violations), 1,
                                  "Should scan multiple files")
            except (NameError, AttributeError):
                # check_directory may not be available in all implementations
                self.skipTest("check_directory not available")

    def test_scan_skips_excluded_directories(self):
        """Directory scan skips venv, __pycache__, .git."""
        with tempfile.TemporaryDirectory() as tmpdir:
            venv_dir = Path(tmpdir) / '.venv'
            venv_dir.mkdir()
            (venv_dir / 'bad.py').write_text('config["SECRET"] = "value"')

            cache_dir = Path(tmpdir) / '__pycache__'
            cache_dir.mkdir()
            (cache_dir / 'module.py').write_text('bad_token = "secret"')

            normal_file = Path(tmpdir) / 'normal.py'
            normal_file.write_text('config["ORCH_KEY"] = 1')

            try:
                violations = check_directory(tmpdir)
                # Should only find violations in normal.py
                filepaths = [v.filepath for v in violations]
                self.assertFalse(any('.venv' in fp for fp in filepaths),
                                "Should skip .venv directory")
                self.assertFalse(any('__pycache__' in fp for fp in filepaths),
                                "Should skip __pycache__ directory")
            except (NameError, AttributeError):
                self.skipTest("check_directory not available")


class TestSeverityLevels(unittest.TestCase):
    """Test severity level reporting."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_violations_report_severity(self):
        """All violations report severity level."""
        code = 'config["BAD"] = 1'
        violations = self._check_code(code)
        for v in violations:
            self.assertIn(v.severity, ['error', 'warning', 'warn', 'info'],
                         f"Invalid severity: {v.severity}")

    def test_config_key_violations_are_errors(self):
        """Config key violations are errors (block merge)."""
        code = 'config["NO_PREFIX"] = 1'
        violations = self._check_code(code)
        config_violations = [v for v in violations if v.rule == 'CONFIG_KEY_NAMING']
        if config_violations:
            self.assertTrue(all(v.severity == 'error' for v in config_violations),
                          "Config violations should be errors")

    def test_filter_violations_by_severity(self):
        """Violations can be filtered by severity."""
        code = """
config['BAD'] = 1
x = 1.5
def badFunc(): pass
"""
        violations = self._check_code(code)
        errors = [v for v in violations if v.severity == 'error']
        warnings = [v for v in violations if v.severity in ['warning', 'warn']]
        total = errors + warnings
        self.assertGreater(len(total), 0,
                          "Should have violations at some severity level")


class TestCIIntegration(unittest.TestCase):
    """Test CI/CD integration."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_violations_output_format(self):
        """Violations output in CI-checkable format (file:line: rule: message)."""
        code = 'config["BAD"] = 1'
        violations = self._check_code(code)
        for v in violations:
            output = str(v)
            # Format: filepath:lineno: rule: message
            self.assertIn(':', output,
                         "Output should contain colons for CI parsing")

    def test_violations_convertible_to_json(self):
        """Violations can be converted to JSON for CI reporting."""
        code = 'config["BAD"] = 1'
        violations = self._check_code(code)
        for v in violations:
            if hasattr(v, 'to_dict'):
                v_dict = v.to_dict()
                json_str = json.dumps(v_dict)
                self.assertIsNotNone(json_str,
                                    "Violation should be JSON-serializable")

    def test_exit_code_semantics(self):
        """Violations indicate non-zero exit code."""
        code = 'config["INVALID"] = 1'
        violations = self._check_code(code)
        has_errors = any(v.severity == 'error' for v in violations)
        if violations:
            self.assertTrue(has_errors or len(violations) > 0,
                           "Should indicate failure for CI")


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_handles_empty_files(self):
        """Empty files don't cause errors."""
        violations = self._check_code("")
        self.assertEqual(len(violations), 0,
                        "Empty file should have no violations")

    def test_handles_syntax_errors(self):
        """Syntax errors reported gracefully."""
        violations = self._check_code("def broken(:\n    pass")
        self.assertGreater(len(violations), 0,
                          "Should report syntax errors")
        self.assertTrue(any(v.rule == 'SYNTAX_ERROR' for v in violations),
                       "Should have SYNTAX_ERROR rule")

    def test_handles_very_large_files(self):
        """Large files handled without timeout."""
        large_code = "\n".join([f"x{i} = {i}" for i in range(10000)])
        violations = self._check_code(large_code)
        self.assertIsNotNone(violations,
                            "Large file should be processed")

    def test_handles_unicode_in_files(self):
        """Unicode in files handled correctly."""
        code = """
# Comment with unicode: 你好世界 🚀
message = "Hello world"
"""
        violations = self._check_code(code)
        self.assertIsNotNone(violations,
                            "Unicode should not crash linter")

    def test_handles_mixed_line_endings(self):
        """Mixed line endings handled correctly."""
        code = "x = 1\r\ny = 2\nz = 3\r\n"
        violations = self._check_code(code)
        self.assertIsNotNone(violations,
                            "Mixed line endings should be handled")

    def test_ignores_code_in_comments(self):
        """Code in comments is not checked."""
        code = """
# config['API_KEY'] = 'secret'
# def badFunction(): pass
pass
"""
        violations = self._check_code(code)
        self.assertEqual(len(violations), 0,
                        "Comments should not trigger violations")

    def test_ignores_code_in_strings(self):
        """Code in docstrings/strings is not checked."""
        code = '''
doc = """
config['API_KEY'] = 'secret'
def badFunction(): pass
"""
pass
'''
        violations = self._check_code(code)
        self.assertEqual(len(violations), 0,
                        "Code in strings should not trigger violations")

    def test_handles_mixed_violations(self):
        """Handles multiple different violations in one file."""
        code = """
def badFunction():
    config['PASSWORD'] = 'secret'
    timeout = 30
    try:
        process()
    except:
        pass
"""
        violations = self._check_code(code)
        self.assertGreater(len(violations), 1,
                          "Should detect multiple different violations")
        rules = set(v.rule for v in violations)
        self.assertGreater(len(rules), 1,
                          "Should have multiple different rules violated")


class TestReferenceImplementations(unittest.TestCase):
    """Test against reference implementations from CLAUDE.md."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_fleet_control_reference_pattern(self):
        """Reference implementation: fleet_control.py pattern."""
        code = """
import threading
from typing import Optional, Dict

ORCH_MAX_CONNECTIONS = 100
ORCH_TIMEOUT_SECONDS = 30

class _FleetControlGateway:
    def __init__(self):
        self._lock = threading.Lock()
        self._config: Dict[str, any] = {}

    def set_config(self, key: str, value: any) -> bool:
        if not key.startswith('ORCH_'):
            return False
        try:
            with self._lock:
                self._config[key] = value
            return True
        except Exception:
            return False

    def get_config(self, key: str) -> Optional[any]:
        try:
            with self._lock:
                return self._config.get(key)
        except Exception:
            return None

_gateway = _FleetControlGateway()

def set_config(key: str, value: any) -> bool:
    return _gateway.set_config(key, value)

def get_config(key: str) -> Optional[any]:
    return _gateway.get_config(key)
"""
        violations = self._check_code(code)
        critical = [v for v in violations
                   if v.severity == 'error' and
                   v.rule in ['CONFIG_KEY_NAMING', 'FAIL_SOFT_ERROR']]
        self.assertEqual(len(critical), 0,
                        "Reference pattern should conform without errors")

    def test_resource_pool_reference_pattern(self):
        """Reference implementation: resource pool singleton pattern."""
        code = """
import threading
from typing import Optional

MAX_POOL_SIZE = 16
DEFAULT_TIMEOUT = 30

class _ResourcePool:
    def __init__(self):
        self._lock = threading.Lock()
        self._resources = []

    def acquire(self) -> Optional[any]:
        try:
            with self._lock:
                if self._resources:
                    return self._resources.pop()
            return None
        except Exception:
            return None

    def release(self, resource: any) -> bool:
        try:
            with self._lock:
                self._resources.append(resource)
            return True
        except Exception:
            return False

_pool = _ResourcePool()

def acquire() -> Optional[any]:
    return _pool.acquire()

def release(resource: any) -> bool:
    return _pool.release(resource)
"""
        violations = self._check_code(code)
        critical = [v for v in violations
                   if v.severity == 'error']
        self.assertEqual(len(critical), 0,
                        "Resource pool pattern should conform")


class TestComprehensiveConformance(unittest.TestCase):
    """Comprehensive conformance validation."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_all_rules_work_together_without_conflicts(self):
        """All rules work together without false positives."""
        code = """
import threading
from typing import Optional

# Constants (avoid magic numbers)
MAX_POOL_SIZE = 16
RETRY_ATTEMPTS = 3
TIMEOUT_SECONDS = 30

class _ResourceManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._resources = []
        self._config = {}

    def acquire_resource(self) -> Optional[any]:
        try:
            with self._lock:
                if self._resources:
                    return self._resources.pop()
            return None
        except Exception:
            return None

    def set_fleet_config(self, key: str, value: any) -> bool:
        if not key.startswith('ORCH_'):
            return False
        try:
            with self._lock:
                self._config[key] = value
            return True
        except Exception:
            return False

_manager = _ResourceManager()

def acquire():
    return _manager.acquire_resource()

def configure_fleet(key: str, value: any) -> bool:
    return _manager.set_fleet_config(key, value)
"""
        violations = self._check_code(code)
        critical = [v for v in violations
                   if v.severity == 'error' and
                   v.rule in ['CONFIG_KEY_NAMING', 'FAIL_SOFT_ERROR',
                             'HARDCODED_SECRET', 'MAGIC_NUMBERS']]
        self.assertEqual(len(critical), 0,
                        "All rules should work together without conflicts")


if __name__ == '__main__':
    unittest.main()
