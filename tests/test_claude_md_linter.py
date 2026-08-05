"""Tests for claude_md_linter.py"""

import sys
import os
from pathlib import Path
import tempfile
import pytest

# Add tools directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'tools'))

from claude_md_linter import (
    lint_file, check_config_keys, check_hardcoded_secrets,
    check_test_coverage, Violation
)


class TestConfigKeyRule:
    """Test config key naming rule."""

    def test_detects_unadorned_config_key(self):
        """Detects uppercase config keys without ORCH_ prefix."""
        content = """
FLEET_CONFIG = "value"
"""
        lines = content.split('\n')
        violations = check_config_keys('test.py', lines)
        assert len(violations) == 1
        assert violations[0].rule_id == 'orch-prefix'

    def test_allows_orch_prefixed_keys(self):
        """Allows keys with ORCH_ prefix."""
        content = """
ORCH_FLEET_CONFIG = "value"
ORCH_POOL_SIZE = 10
"""
        lines = content.split('\n')
        violations = check_config_keys('test.py', lines)
        assert len(violations) == 0

    def test_detects_config_setting_pattern(self):
        """Detects CONFIG and SETTING patterns."""
        content = """
MY_CONFIG = "foo"
WORKER_SETTING = "bar"
"""
        lines = content.split('\n')
        violations = check_config_keys('test.py', lines)
        assert len(violations) == 2

    def test_ignores_regular_variables(self):
        """Ignores regular uppercase variables."""
        content = """
MAX_RETRIES = 3
TIMEOUT = 30
"""
        lines = content.split('\n')
        violations = check_config_keys('test.py', lines)
        assert len(violations) == 0

    def test_ignores_comments(self):
        """Ignores config keys in comments."""
        content = """
# FLEET_CONFIG = "value"
x = 1
"""
        lines = content.split('\n')
        violations = check_config_keys('test.py', lines)
        assert len(violations) == 0


class TestHardcodedSecretsRule:
    """Test hardcoded secrets detection."""

    def test_detects_hardcoded_password(self):
        """Detects hardcoded password patterns."""
        content = """
password = "supersecret123"
"""
        lines = content.split('\n')
        violations = check_hardcoded_secrets('test.py', lines)
        assert len(violations) == 1
        assert violations[0].rule_id == 'hardcoded-secret'

    def test_detects_hardcoded_token(self):
        """Detects hardcoded token patterns."""
        content = """
auth_token = "abc123xyz"
api_key = "secret"
"""
        lines = content.split('\n')
        violations = check_hardcoded_secrets('test.py', lines)
        assert len(violations) == 2

    def test_detects_with_colon_separator(self):
        """Detects secrets with colon separator (YAML style)."""
        content = """
secret: "my_secret_value"
"""
        lines = content.split('\n')
        violations = check_hardcoded_secrets('test.py', lines)
        assert len(violations) == 1

    def test_ignores_example_files(self):
        """Ignores secrets in .example files."""
        content = """
password = "value"
"""
        lines = content.split('\n')
        violations = check_hardcoded_secrets('test.example.py', lines)
        assert len(violations) == 0

    def test_ignores_comments(self):
        """Ignores secrets in comments."""
        content = """
# password = "secret"
x = 1
"""
        lines = content.split('\n')
        violations = check_hardcoded_secrets('test.py', lines)
        assert len(violations) == 0

    def test_case_insensitive(self):
        """Detects PASSWORD, SECRET, etc. (case-insensitive)."""
        content = """
PASSWORD = "value"
SECRET = "value"
"""
        lines = content.split('\n')
        violations = check_hardcoded_secrets('test.py', lines)
        assert len(violations) == 2


class TestCoverageRule:
    """Test test coverage documentation rule."""

    def test_detects_missing_coverage_docstring(self):
        """Detects test functions without @coverage docstring."""
        content = '''
def test_basic():
    """Test basic functionality."""
    assert True
'''
        lines = content.split('\n')
        violations = check_test_coverage('tests/test_example.py', lines)
        assert len(violations) == 1
        assert violations[0].rule_id == 'test-coverage'

    def test_allows_coverage_docstring(self):
        """Allows test functions with @coverage docstring."""
        content = '''
def test_comprehensive():
    """
    Test comprehensive behavior.

    @coverage: 25 cases
    """
    assert True
'''
        lines = content.split('\n')
        violations = check_test_coverage('tests/test_example.py', lines)
        assert len(violations) == 0

    def test_ignores_non_test_files(self):
        """Ignores non-test files."""
        content = '''
def test_function():
    """Test."""
    pass
'''
        lines = content.split('\n')
        violations = check_test_coverage('main.py', lines)
        assert len(violations) == 0

    def test_handles_multiple_test_functions(self):
        """Handles multiple test functions."""
        content = '''
def test_one():
    """Test."""
    pass

def test_two():
    """@coverage: 20 cases"""
    pass
'''
        lines = content.split('\n')
        violations = check_test_coverage('tests/test_example.py', lines)
        assert len(violations) == 1  # test_one is missing coverage

    def test_single_quote_docstring(self):
        """Handles single-quote docstrings."""
        content = """
def test_example():
    '''
    Test example.

    @coverage: 15 cases
    '''
    pass
"""
        lines = content.split('\n')
        violations = check_test_coverage('tests/test_example.py', lines)
        assert len(violations) == 0


class TestLintFileIntegration:
    """Integration tests for lint_file."""

    def test_passes_on_conforming_code(self):
        """Test passes on code that follows all conventions."""
        content = '''
import unittest

ORCH_MAX_RETRY = 3

class TestExample(unittest.TestCase):
    def test_feature(self):
        """
        Test the feature.

        @coverage: 20 cases
        """
        self.assertTrue(True)
'''
        with tempfile.NamedTemporaryFile(mode='w', suffix='_test.py', delete=False) as f:
            f.write(content)
            f.flush()
            try:
                violations = lint_file(f.name)
                assert len(violations) == 0
            finally:
                os.unlink(f.name)

    def test_detects_multiple_violations(self):
        """Test detects multiple types of violations."""
        content = '''
FLEET_CONFIG = "value"
password = "secret"

def test_something():
    """Test."""
    pass
'''
        with tempfile.NamedTemporaryFile(mode='w', suffix='_test.py', delete=False) as f:
            f.write(content)
            f.flush()
            try:
                violations = lint_file(f.name)
                # Should have: 1 config key, 1 hardcoded secret, 1 missing coverage
                assert len(violations) >= 2
            finally:
                os.unlink(f.name)

    def test_handles_nonexistent_file(self):
        """Test handles missing file gracefully."""
        violations = lint_file('/nonexistent/file.py')
        assert violations == []

    def test_handles_malformed_python(self):
        """Test handles malformed Python gracefully."""
        content = 'this is not python ['
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(content)
            f.flush()
            try:
                violations = lint_file(f.name)
                # Should not crash, may detect patterns
                assert isinstance(violations, list)
            finally:
                os.unlink(f.name)


class TestEdgeCases:
    """Edge case tests."""

    def test_empty_file(self):
        """Test on empty file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('')
            f.flush()
            try:
                violations = lint_file(f.name)
                assert violations == []
            finally:
                os.unlink(f.name)

    def test_unicode_content(self):
        """Test handling Unicode content."""
        content = '''
# Comment with emoji 🎯
ORCH_VALUE = "café"
'''
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
            f.write(content)
            f.flush()
            try:
                violations = lint_file(f.name)
                assert isinstance(violations, list)
            finally:
                os.unlink(f.name)

    def test_violation_to_dict(self):
        """Test Violation.to_dict() method."""
        v = Violation('test.py', 10, 'test-rule', 'Test message', 'error')
        d = v.to_dict()
        assert d['file'] == 'test.py'
        assert d['line'] == 10
        assert d['rule_id'] == 'test-rule'
        assert d['message'] == 'Test message'
        assert d['severity'] == 'error'

    def test_blank_lines(self):
        """Test handling blank lines."""
        content = '''

FLEET_CONFIG = "test"

'''
        lines = content.split('\n')
        violations = check_config_keys('test.py', lines)
        assert len(violations) == 1
