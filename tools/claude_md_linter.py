#!/usr/bin/env python3
"""
Convention conformance linter for claude-orchestrator.

Checks Python code against conventions documented in CLAUDE.md.
Phase 1 rules:
1. Config key naming: fleet-wide keys must be prefixed ORCH_
2. Hardcoded secrets: flag password/secret/token/key patterns
3. Test coverage: Python test files must have @coverage: <N> docstrings
"""

import re
import sys
from pathlib import Path
from typing import List, Dict, Optional
import logging

logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


class Violation:
    """Represents a single linting violation."""

    def __init__(self, file: str, line: int, rule_id: str, message: str, severity: str = "warn"):
        self.file = file
        self.line = line
        self.rule_id = rule_id
        self.message = message
        self.severity = severity

    def to_dict(self) -> Dict:
        """Convert violation to dictionary."""
        return {
            'file': self.file,
            'line': self.line,
            'rule_id': self.rule_id,
            'message': self.message,
            'severity': self.severity
        }


def check_config_keys(file_path: str, lines: List[str]) -> List[Violation]:
    """
    Rule: Fleet-wide config keys must be prefixed ORCH_.

    Check for patterns like:
    - FLEET_CONFIG = "value"
    - MY_CONFIG = "value"
    - POOL_SETTING = "value"

    But allow ORCH_PREFIXED_KEY patterns.
    """
    violations = []

    for line_num, line in enumerate(lines, 1):
        # Skip comments and blank lines
        if line.strip().startswith('#') or not line.strip():
            continue

        # Look for uppercase assignments that look like config keys
        match = re.search(r'^\s*([A-Z][A-Z0-9_]*)\s*=', line)
        if match:
            var_name = match.group(1)
            # Flag if it looks like a config but isn't ORCH_ prefixed
            if any(x in var_name for x in ['CONFIG', 'SETTING', 'FLEET', 'PARAM']):
                if not var_name.startswith('ORCH_'):
                    violations.append(Violation(
                        file_path, line_num,
                        'orch-prefix',
                        f"Config key '{var_name}' should be prefixed with ORCH_",
                        'warn'
                    ))

    return violations


def check_hardcoded_secrets(file_path: str, lines: List[str]) -> List[Violation]:
    """
    Rule: Flag hardcoded secrets (password, secret, token, key patterns).

    Severity: warn
    Skips .example files.
    """
    violations = []

    # Skip .example files
    if '.example' in file_path:
        return violations

    pattern = r'(password|secret|token|key|api_key|apikey)\s*[=:]\s*["\']'

    for line_num, line in enumerate(lines, 1):
        # Skip comment lines
        if line.strip().startswith('#'):
            continue

        if re.search(pattern, line, re.IGNORECASE):
            violations.append(Violation(
                file_path, line_num,
                'hardcoded-secret',
                "Hardcoded secret or credential detected",
                'warn'
            ))

    return violations


def check_test_coverage(file_path: str, lines: List[str]) -> List[Violation]:
    """
    Rule: Test functions must have @coverage: N docstring.

    Only checks files under tests/ or named test_*.py.
    Severity: warn
    """
    violations = []

    # Only check test files
    if not any(x in file_path for x in ['test_', 'tests/']):
        return violations

    i = 0
    while i < len(lines):
        line = lines[i]

        # Look for test function definition
        if re.match(r'^\s*def\s+test_\w+', line):
            func_line = i + 1
            has_coverage = False

            # Check docstring on next line(s)
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                if '"""' in next_line or "'''" in next_line:
                    # Extract coverage info from docstring
                    quote = '"""' if '"""' in next_line else "'''"
                    j = i + 1
                    docstring = ""
                    while j < len(lines) and j < i + 10:  # Limit search to 10 lines
                        docstring += lines[j]
                        if lines[j].count(quote) >= 2 or (j > i + 1 and quote in lines[j]):
                            break
                        j += 1

                    if '@coverage:' in docstring:
                        has_coverage = True

            if not has_coverage:
                func_match = re.search(r'def\s+(\w+)', line)
                func_name = func_match.group(1) if func_match else 'unknown'
                violations.append(Violation(
                    file_path, func_line,
                    'test-coverage',
                    f"Test function '{func_name}' missing @coverage docstring",
                    'warn'
                ))

        i += 1

    return violations


def lint_file(file_path: str) -> List[Violation]:
    """
    Lint a Python file against all Phase 1 rules.

    Fails soft: catches exceptions, logs warning, returns empty list.
    """
    violations = []

    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        # Run all checks
        try:
            violations.extend(check_config_keys(file_path, lines))
        except Exception as e:
            logger.warning(f"Error in config_keys check for {file_path}: {e}")

        try:
            violations.extend(check_hardcoded_secrets(file_path, lines))
        except Exception as e:
            logger.warning(f"Error in hardcoded_secrets check for {file_path}: {e}")

        try:
            violations.extend(check_test_coverage(file_path, lines))
        except Exception as e:
            logger.warning(f"Error in test_coverage check for {file_path}: {e}")

    except Exception as e:
        logger.warning(f"Error reading {file_path}: {e}")

    return violations


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: python claude_md_linter.py <file> [file2 ...]", file=sys.stderr)
        sys.exit(0)

    all_violations = []

    for file_path in sys.argv[1:]:
        if not file_path.endswith('.py'):
            continue

        violations = lint_file(file_path)
        all_violations.extend(violations)

    # Print violations
    error_count = 0
    for v in all_violations:
        print(f"{v.file}:{v.line}: {v.severity.upper()}: [{v.rule_id}] {v.message}")
        if v.severity == 'error':
            error_count += 1

    # Only fail if there are error-severity violations
    sys.exit(1 if error_count > 0 else 0)


if __name__ == '__main__':
    main()
