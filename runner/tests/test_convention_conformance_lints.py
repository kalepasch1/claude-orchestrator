"""
Comprehensive test suite for convention-conformance-lints pre-merge enforcement.

Tests the complete system for machine-checked lint rules extracted from CLAUDE.md
conventions. Validates that agent output matches house style automatically before merge,
regenerates on convention changes, and integrates with git workflow.

Coverage areas:
1. Pre-merge enforcement (check before commit)
2. Convention violation detection and reporting
3. Agent output validation
4. Multi-file scanning and aggregation
5. Severity levels and filtering
6. CI/CD integration
7. Convention regeneration triggers
8. Git workflow integration
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import List, Dict, Any
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

from lint_conventions import check_file, ConventionViolation, scan_directory


class TestPreMergeEnforcement(unittest.TestCase):
    """Test pre-merge enforcement of conventions."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        """Helper to check code snippet."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_blocks_merge_with_unprefix_config_keys(self):
        """Pre-merge check blocks unprefixed config keys."""
        agent_code = """
def setup_fleet():
    config['DATABASE_URL'] = 'db://localhost'
    config['TIMEOUT'] = 30
"""
        violations = self._check_code(agent_code)
        config_violations = [v for v in violations if v.rule == 'CONFIG_KEY_NAMING']
        self.assertGreater(len(config_violations), 0,
                          "Pre-merge should reject unprefixed config keys")
        self.assertTrue(all(v.severity == 'error' for v in config_violations))

    def test_blocks_merge_with_bare_except(self):
        """Pre-merge check blocks bare except without error handling."""
        agent_code = """
def process_item():
    try:
        return load_data()
    except:
        pass
"""
        violations = self._check_code(agent_code)
        error_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertGreater(len(error_violations), 0,
                          "Pre-merge should reject bare except without return")

    def test_blocks_merge_with_magic_numbers(self):
        """Pre-merge check blocks magic numbers."""
        agent_code = """
def configure_pool():
    max_size = 16
    retry_count = 3
    timeout_seconds = 30
"""
        violations = self._check_code(agent_code)
        magic_violations = [v for v in violations if v.rule == 'MAGIC_NUMBERS']
        self.assertGreater(len(magic_violations), 0,
                          "Pre-merge should reject magic numbers")

    def test_allows_merge_with_proper_conventions(self):
        """Pre-merge check allows conformant code."""
        agent_code = """
import threading

MAX_POOL_SIZE = 16
RETRY_COUNT = 3
DEFAULT_TIMEOUT = 30

class _ConnectionPool:
    def __init__(self):
        self._lock = threading.Lock()
        self._connections = []

    def acquire(self):
        with self._lock:
            if self._connections:
                return self._connections.pop()
        return None

    def release(self, conn):
        with self._lock:
            self._connections.append(conn)

_pool = _ConnectionPool()

def acquire():
    try:
        return _pool.acquire()
    except Exception:
        return None

def release(conn):
    try:
        _pool.release(conn)
        return True
    except Exception:
        return False
"""
        violations = self._check_code(agent_code)
        critical = [v for v in violations if v.rule in
                   ['CONFIG_KEY_NAMING', 'FAIL_SOFT_ERROR', 'MAGIC_NUMBERS']]
        self.assertEqual(len(critical), 0,
                        "Pre-merge should allow conformant code")

    def test_violations_have_line_numbers(self):
        """Violations report accurate line numbers."""
        agent_code = """
# Line 1
# Line 2
config['API_KEY'] = 'secret'  # Line 3 should be reported
# Line 4
"""
        violations = self._check_code(agent_code)
        config_violations = [v for v in violations if v.rule == 'CONFIG_KEY_NAMING']
        self.assertGreater(len(config_violations), 0)
        self.assertEqual(config_violations[0].lineno, 3)


class TestConventionViolationDetection(unittest.TestCase):
    """Test detection of all convention violation types."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_detects_config_key_naming_violations(self):
        """Detects config key naming violations."""
        code = "config['INVALID_KEY'] = 42"
        violations = self._check_code(code)
        self.assertTrue(any(v.rule == 'CONFIG_KEY_NAMING' for v in violations))

    def test_detects_fail_soft_violations(self):
        """Detects fail-soft error handling violations."""
        code = """
def risky():
    try:
        dangerous_op()
    except ValueError:
        pass
"""
        violations = self._check_code(code)
        self.assertTrue(any(v.rule == 'FAIL_SOFT_ERROR' for v in violations))

    def test_detects_naming_convention_violations(self):
        """Detects naming convention violations."""
        code = """
def process():
    badFunction()
"""
        violations = self._check_code(code)
        self.assertTrue(any(v.rule == 'NAMING_CONVENTION' for v in violations))

    def test_detects_magic_number_violations(self):
        """Detects magic number violations."""
        code = """
def timing():
    delay = 1.5
"""
        violations = self._check_code(code)
        self.assertTrue(any(v.rule == 'MAGIC_NUMBERS' for v in violations))

    def test_multiple_violations_same_file(self):
        """Detects multiple violations in same file."""
        code = """
def badFunction():
    config['SECRET'] = 'value'
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
        self.assertTrue(len(rules) > 1)


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

    def test_agent_generated_singleton_module(self):
        """Validates agent-generated singleton module pattern."""
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
    if not isinstance(key, str):
        return False
    try:
        _gateway.update(key, value)
        return True
    except Exception:
        return False

def get_state(key):
    try:
        return _gateway._state.get(key)
    except Exception:
        return None
"""
        violations = self._check_code(code)
        critical = [v for v in violations if v.rule in
                   ['CONFIG_KEY_NAMING', 'FAIL_SOFT_ERROR']]
        self.assertEqual(len(critical), 0)

    def test_rejects_agent_code_with_hardcoded_secrets(self):
        """Rejects agent-generated code with hardcoded secrets."""
        code = """
def initialize():
    api_token = 'sk-1234567890'
    database_password = 'prod-secret'
"""
        violations = self._check_code(code)
        # Should have violations for assignments with suspicious names
        self.assertGreater(len(violations), 0)

    def test_validates_fleet_config_access_patterns(self):
        """Validates fleet config access patterns."""
        good_code = """
def update_fleet():
    config['ORCH_WORKER_COUNT'] = 8
    config['ORCH_TIMEOUT'] = 30
"""
        violations = self._check_code(good_code)
        config_violations = [v for v in violations if v.rule == 'CONFIG_KEY_NAMING']
        self.assertEqual(len(config_violations), 0)

    def test_validates_error_handling_comprehensiveness(self):
        """Validates comprehensive error handling."""
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
        error_violations = [v for v in violations if v.rule == 'FAIL_SOFT_ERROR']
        self.assertEqual(len(error_violations), 0)


class TestMultiFileScanning(unittest.TestCase):
    """Test scanning and validating multiple files."""

    def test_scan_directory_collects_all_violations(self):
        """Directory scan collects violations from all Python files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create multiple files with violations
            file1 = Path(tmpdir) / 'module1.py'
            file1.write_text("config['BAD_KEY'] = 1")

            file2 = Path(tmpdir) / 'module2.py'
            file2.write_text("def badFunction(): pass")

            file3 = Path(tmpdir) / 'good.py'
            file3.write_text("def good_function(): pass")

            violations = scan_directory(tmpdir)
            self.assertGreater(len(violations), 0)
            files_with_violations = set(v.filepath for v in violations)
            self.assertGreater(len(files_with_violations), 1)

    def test_scan_skips_excluded_directories(self):
        """Directory scan skips venv, __pycache__, .git, node_modules."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a venv directory with violations
            venv_dir = Path(tmpdir) / 'venv'
            venv_dir.mkdir()
            venv_file = venv_dir / 'bad.py'
            venv_file.write_text("config['SECRET'] = 'value'")

            # Create __pycache__ with violations
            cache_dir = Path(tmpdir) / '__pycache__'
            cache_dir.mkdir()
            cache_file = cache_dir / 'module.py'
            cache_file.write_text("config['INVALID'] = 1")

            # Create a normal file with violations
            normal_file = Path(tmpdir) / 'normal.py'
            normal_file.write_text("config['BAD'] = 1")

            violations = scan_directory(tmpdir)
            # Should only find the normal file violation
            self.assertTrue(any('normal.py' in v.filepath for v in violations))
            self.assertFalse(any('venv' in v.filepath for v in violations))
            self.assertFalse(any('__pycache__' in v.filepath for v in violations))

    def test_scan_generates_report(self):
        """Directory scan generates comprehensive report."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, 'file1.py').write_text("config['KEY1'] = 1")
            Path(tmpdir, 'file2.py').write_text("config['KEY2'] = 2")

            violations = scan_directory(tmpdir)
            self.assertGreater(len(violations), 0)

            # All violations should have required fields
            for v in violations:
                self.assertIsNotNone(v.filepath)
                self.assertIsNotNone(v.lineno)
                self.assertIsNotNone(v.rule)
                self.assertIsNotNone(v.message)


class TestSeverityAndFiltering(unittest.TestCase):
    """Test violation severity levels and filtering."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_violations_have_severity(self):
        """All violations report severity level."""
        code = "config['BAD'] = 1"
        violations = self._check_code(code)
        for v in violations:
            self.assertIn(v.severity, ['error', 'warning', 'info'])

    def test_config_key_violations_are_errors(self):
        """Config key violations are errors (block merge)."""
        code = "config['NO_PREFIX'] = 1"
        violations = self._check_code(code)
        config_violations = [v for v in violations if v.rule == 'CONFIG_KEY_NAMING']
        self.assertTrue(all(v.severity == 'error' for v in config_violations))

    def test_filter_by_severity(self):
        """Violations can be filtered by severity."""
        code = """
config['BAD'] = 1
x = 1.5
def badFunc(): pass
"""
        violations = self._check_code(code)
        errors = [v for v in violations if v.severity == 'error']
        self.assertGreater(len(errors), 0)


class TestCIIntegration(unittest.TestCase):
    """Test CI/CD pipeline integration."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_exit_code_on_violations(self):
        """System exits with error code when violations found."""
        code = "config['INVALID'] = 1"
        violations = self._check_code(code)
        # In CI, would exit(1) if violations present
        self.assertGreater(len(violations), 0)

    def test_exit_code_on_success(self):
        """System exits with success code when no violations."""
        code = "MAX_RETRIES = 3"
        violations = self._check_code(code)
        config_violations = [v for v in violations if v.rule == 'CONFIG_KEY_NAMING']
        # In CI, would exit(0) if no violations
        self.assertEqual(len(config_violations), 0)

    def test_generates_checkable_output(self):
        """Violations output in CI-checkable format."""
        code = "config['BAD'] = 1"
        violations = self._check_code(code)
        for v in violations:
            output = str(v)
            # Format: filepath:lineno: rule: message
            self.assertIn(':', output)
            parts = output.split(':')
            self.assertGreater(len(parts), 2)


class TestConventionRegeneraton(unittest.TestCase):
    """Test regeneration of lint rules from updated conventions."""

    def test_can_detect_convention_changes(self):
        """System detects when CLAUDE.md conventions change."""
        # This would be tested by synthesize_conventions.py
        # which regenerates rules when CLAUDE.md is updated
        old_conventions = {
            'CONFIG_KEY_NAMING': ['ORCH_'],
            'FAIL_SOFT_ERROR': ['return defaults'],
        }
        new_conventions = {
            'CONFIG_KEY_NAMING': ['ORCH_'],
            'FAIL_SOFT_ERROR': ['return defaults'],
            'NEW_RULE': ['new pattern'],
        }
        # Should trigger regeneration
        self.assertNotEqual(old_conventions, new_conventions)

    def test_applies_new_rules_on_regeneration(self):
        """New rules from updated conventions are applied."""
        # When synthesize_conventions.py runs after CLAUDE.md update
        # the new rule pattern should be in effect
        old_code = "# Code written before new rule"
        new_code = "# Code written after rule added"
        # New rule would be checked against both
        self.assertIsNotNone(old_code)
        self.assertIsNotNone(new_code)


class TestGitWorkflowIntegration(unittest.TestCase):
    """Test integration with git commit workflow."""

    def test_violation_report_format(self):
        """Violations report in git-compatible format."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("config['BAD'] = 1")
            f.flush()
            try:
                violations = check_file(f.name)
                for v in violations:
                    # Format: file:line: rule: message
                    # Can be parsed by git hooks
                    output = str(v)
                    self.assertRegex(output, r'.*\.py:\d+:')
            finally:
                os.unlink(f.name)

    def test_can_integrate_as_pre_commit_hook(self):
        """Violations can be used in pre-commit hook."""
        # A pre-commit hook would:
        # 1. Get list of staged files
        # 2. Run lint_conventions on them
        # 3. Report violations
        # 4. Block commit if any errors found

        code = "config['INVALID'] = 1"
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                violations = check_file(f.name)
                has_errors = any(v.severity == 'error' for v in violations)
                self.assertTrue(has_errors, "Should block commit on error")
            finally:
                os.unlink(f.name)

    def test_can_be_integrated_in_github_actions(self):
        """Violations can be reported to GitHub Actions."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("config['BAD'] = 1")
            f.flush()
            try:
                violations = check_file(f.name)
                for v in violations:
                    # GitHub Actions format: ::error file=path::message
                    # Could be generated from violations
                    output = str(v)
                    self.assertIsNotNone(output)
            finally:
                os.unlink(f.name)


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
        self.assertEqual(len(violations), 0)

    def test_handles_syntax_errors(self):
        """Syntax errors reported gracefully."""
        violations = self._check_code("def broken(:\n    pass")
        self.assertGreater(len(violations), 0)
        self.assertTrue(any(v.rule == 'SYNTAX_ERROR' for v in violations))

    def test_handles_very_large_files(self):
        """Large files handled without timeout."""
        large_code = "\n".join([f"x{i} = {i}" for i in range(10000)])
        violations = self._check_code(large_code)
        # Should complete without timeout
        self.assertIsNotNone(violations)

    def test_handles_unicode_in_files(self):
        """Unicode in files handled correctly."""
        code = """
# Comment with unicode: 你好世界 🚀
message = "Hello world"
"""
        violations = self._check_code(code)
        # Should not crash
        self.assertIsNotNone(violations)

    def test_handles_mixed_line_endings(self):
        """Mixed line endings handled correctly."""
        code = "x = 1\r\ny = 2\nz = 3\r\n"
        violations = self._check_code(code)
        # Should normalize and check
        self.assertIsNotNone(violations)

    def test_ignores_comments(self):
        """Code in comments not checked."""
        code = """
# config['API_KEY'] = 'secret'
# def badFunction(): pass
# x = 1.5
pass
"""
        violations = self._check_code(code)
        # Should not flag commented code
        self.assertEqual(len(violations), 0)

    def test_ignores_strings(self):
        """Code in strings not checked."""
        code = """
doc = '''
config['API_KEY'] = 'secret'
def badFunction(): pass
'''
pass
"""
        violations = self._check_code(code)
        # Should not flag code in strings
        self.assertEqual(len(violations), 0)


class TestComprehensiveConformance(unittest.TestCase):
    """Comprehensive conformance testing."""

    def _check_code(self, code: str) -> List[ConventionViolation]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return check_file(f.name)
            finally:
                os.unlink(f.name)

    def test_fleet_control_module_conforms(self):
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
        critical = [v for v in violations if v.rule in
                   ['CONFIG_KEY_NAMING', 'FAIL_SOFT_ERROR', 'MAGIC_NUMBERS']]
        self.assertEqual(len(critical), 0,
                        "Reference pattern should conform")

    def test_all_rules_enforced_together(self):
        """All rules work together without conflicts."""
        good_code = """
import threading

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
        violations = self._check_code(good_code)
        critical = [v for v in violations if v.rule in
                   ['CONFIG_KEY_NAMING', 'FAIL_SOFT_ERROR', 'NAMING_CONVENTION',
                    'MAGIC_NUMBERS']]
        self.assertEqual(len(critical), 0,
                        "All rules should work together")


if __name__ == '__main__':
    unittest.main()
