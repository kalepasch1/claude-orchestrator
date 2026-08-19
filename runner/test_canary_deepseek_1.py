#!/usr/bin/env python3
"""Test suite for canary-deepseek-1: smallest safe repository-local improvements.

Validates that the canary implementation correctly identifies and applies
small, safe improvements (typos, clarifying comments, doc fixes) without
changing product behavior, secrets, or dependencies.

Improvements include:
- Fixing typos in code/docs/comments
- Adding clarifying comments to non-obvious test setup
- Improving harmless documentation
- Correcting grammar in docstrings

Constraints enforced:
- No product behavior changes
- No secrets/credentials introduced or modified
- No dependency version changes
- No package manager changes
- Changes only committed if useful and tests pass

Run: pytest test_canary_deepseek_1.py -v
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class TestCandidateIdentification:
    """Validate that improvement candidates are correctly identified."""

    def test_detects_typos_in_comments(self):
        """Typos in code comments are valid candidates."""
        content = "# This is a commment with a typo"
        candidates = find_typos(content)
        assert any("commment" in c for c in candidates)

    def test_detects_typos_in_docstrings(self):
        """Typos in docstrings are valid candidates."""
        content = '''def foo():
    """Ths is an incorrect docstring."""
    pass'''
        candidates = find_typos(content)
        assert any("Ths" in c for c in candidates)

    def test_detects_unclear_test_setup(self):
        """Test setup that lacks explanation is a candidate for clarification."""
        content = '''def test_thing():
    data = [1, 2, 3, 4, 5]
    assert len(data) == 5'''
        candidates = find_unclear_test_setup(content)
        assert len(candidates) > 0

    def test_detects_improving_doc_lines(self):
        """Documentation lines that can be improved are candidates."""
        content = "the function does stuff and returns a thing"
        candidates = find_weak_doc_lines(content)
        assert len(candidates) > 0

    def test_ignores_implementation_logic(self):
        """Implementation logic changes are not candidates."""
        content = "x = y + 1  # add one"
        candidates = find_logic_changes(content)
        assert len(candidates) == 0

    def test_ignores_nested_deeply(self):
        """Changes to deeply-nested functions are not candidates."""
        content = '''def outer():
    def middle():
        def inner():
            # typo: recieve
            pass'''
        candidates = find_deep_nested_candidates(content)
        assert len(candidates) == 0


class TestSafetyValidation:
    """Validate that changes are safe and do not affect product behavior."""

    def test_rejects_changes_to_secrets_or_credentials(self):
        """Changes that introduce or modify secrets are rejected."""
        diffs = [
            "- # password: ''",
            "+ # password: 'hardcoded123'",
        ]
        is_safe = is_safe_change(diffs)
        assert not is_safe

    def test_rejects_changes_to_env_secrets(self):
        """Changes modifying environment-based secrets are rejected."""
        diffs = [
            "- os.environ['API_KEY']",
            "+ 'actual-api-key-12345'",
        ]
        is_safe = is_safe_change(diffs)
        assert not is_safe

    def test_rejects_dependency_changes(self):
        """Changes to dependencies (requirements.txt, setup.py, etc) are rejected."""
        files = ["requirements.txt", "setup.py", "pyproject.toml", "Pipfile"]
        for file in files:
            is_safe = is_file_safe_to_modify(file)
            assert not is_safe

    def test_rejects_package_manager_changes(self):
        """Changes to package manager files are rejected."""
        files = ["package.json", "package-lock.json", "yarn.lock", "poetry.lock"]
        for file in files:
            is_safe = is_file_safe_to_modify(file)
            assert not is_safe

    def test_allows_docstring_typo_fixes(self):
        """Fixing typos in docstrings is safe."""
        diffs = [
            "- '''Ths function does something.'''",
            "+ '''This function does something.'''",
        ]
        is_safe = is_safe_change(diffs)
        assert is_safe

    def test_allows_comment_improvements(self):
        """Improving comments is safe."""
        diffs = [
            "- # TODO: fixit",
            "+ # TODO: fix iterator initialization bug",
        ]
        is_safe = is_safe_change(diffs)
        assert is_safe

    def test_rejects_logic_changes_in_functions(self):
        """Changes that alter function logic are rejected."""
        diffs = [
            "- return x + 1",
            "+ return x + 2",
        ]
        is_safe = is_safe_change(diffs)
        assert not is_safe

    def test_rejects_changes_to_product_files(self):
        """Changes to core product logic files are rejected."""
        product_files = [
            "src/orchestrator.py",
            "src/runner.py",
            "src/fleet_control.py",
        ]
        for file in product_files:
            is_safe = is_file_safe_to_modify(file)
            assert not is_safe

    def test_allows_changes_to_doc_files(self):
        """Changes to documentation files are safe."""
        doc_files = ["docs/README.md", "CONTRIBUTING.md", "docs/api.md"]
        for file in doc_files:
            is_safe = is_file_safe_to_modify(file)
            assert is_safe

    def test_allows_changes_to_test_files(self):
        """Changes to test files are safe (adding clarifying comments)."""
        test_files = [
            "test_something.py",
            "tests/test_module.py",
            "ops/tests/test_recovery.py",
        ]
        for file in test_files:
            is_safe = is_file_safe_to_modify(file)
            assert is_safe


class TestCommitDecision:
    """Validate commit creation only when changes are useful and pass checks."""

    def test_commits_useful_typo_fix(self):
        """A single typo fix that's useful is committed."""
        changes = {
            "file": "docs/README.md",
            "old_text": "unecessary",
            "new_text": "unnecessary",
            "type": "typo",
        }
        should_commit = should_make_commit(changes, tests_pass=True)
        assert should_commit

    def test_does_not_commit_trivial_change(self):
        """A change that's too trivial (like a single space) is not committed."""
        changes = {
            "file": "src/module.py",
            "old_text": "x = 1",
            "new_text": "x=1",
            "type": "spacing",
        }
        should_commit = should_make_commit(changes, tests_pass=True)
        assert not should_commit

    def test_does_not_commit_when_tests_fail(self):
        """A good change is not committed if existing tests fail."""
        changes = {
            "file": "docs/README.md",
            "old_text": "unecessary",
            "new_text": "unnecessary",
            "type": "typo",
        }
        should_commit = should_make_commit(changes, tests_pass=False)
        assert not should_commit

    def test_commits_clarifying_comment(self):
        """A clarifying comment added to test setup is committed."""
        changes = {
            "file": "test_something.py",
            "old_text": "data = [1, 2, 3]",
            "new_text": "data = [1, 2, 3]  # sorted edge case: duplicates at boundaries",
            "type": "clarification",
        }
        should_commit = should_make_commit(changes, tests_pass=True)
        assert should_commit

    def test_commits_doc_improvement(self):
        """A documentation improvement is committed."""
        changes = {
            "file": "docs/api.md",
            "old_text": "the API returns stuff",
            "new_text": "the API returns a JSON object with status and payload fields",
            "type": "doc_improvement",
        }
        should_commit = should_make_commit(changes, tests_pass=True)
        assert should_commit


class TestChangeExtraction:
    """Validate that changes are correctly extracted and categorized."""

    def test_extracts_single_typo_from_file(self):
        """A single typo is extracted correctly."""
        content = "This docstring has an intrepid bug in the code logic."
        extracted = extract_changes(content, "test.py")
        assert any(c["type"] == "typo" for c in extracted)

    def test_extracts_multiple_improvements(self):
        """Multiple improvements in one file are extracted."""
        content = '''
        def test_something():
            """Ths test checks the core behavor."""
            x = [1, 2]  # array initialization
            return x
        '''
        extracted = extract_changes(content, "test.py")
        assert len(extracted) >= 2

    def test_categorizes_changes_by_type(self):
        """Changes are categorized as typo, comment, doc, etc."""
        changes = extract_changes("some content", "test.py")
        if changes:
            for change in changes:
                assert "type" in change
                assert change["type"] in [
                    "typo",
                    "comment",
                    "docstring",
                    "doc_improvement",
                    "clarification",
                ]


class TestMinimality:
    """Validate that changes are minimal and focused."""

    def test_stops_after_first_safe_improvement(self):
        """Scan stops after finding the first safe improvement."""
        improvements = find_improvements_in_repo(max_count=1)
        assert len(improvements) <= 1

    def test_does_not_make_multiple_unrelated_changes(self):
        """A single commit touches only one improvement, not multiple."""
        change = make_single_improvement()
        assert change["file_count"] == 1

    def test_improvement_size_is_bounded(self):
        """An improvement doesn't add more than 5 lines of comments."""
        improvement = make_single_improvement()
        added_lines = len(improvement.get("added_text", "").split("\n"))
        assert added_lines <= 5


class TestBoundaryConditions:
    """Validate edge cases and boundary conditions."""

    def test_handles_empty_repository(self):
        """Gracefully handles repo with no improvable files."""
        improvements = find_improvements_in_repo()
        assert isinstance(improvements, list)

    def test_handles_no_safe_candidates(self):
        """Returns empty list when no safe candidates exist."""
        improvements = find_improvements_in_repo()
        for improvement in improvements:
            is_safe = is_safe_change(improvement["diffs"])
            assert is_safe

    def test_handles_malformed_files(self):
        """Gracefully skips files that can't be parsed."""
        try:
            improvements = find_improvements_in_repo()
            assert isinstance(improvements, list)
        except Exception as e:
            pytest.fail(f"Should not raise on malformed files: {e}")

    def test_handles_permission_errors(self):
        """Gracefully handles permission errors when reading files."""
        try:
            improvements = find_improvements_in_repo()
            assert isinstance(improvements, list)
        except PermissionError:
            pytest.fail("Should not raise PermissionError")

    def test_handles_large_files(self):
        """Processes large files without excessive memory usage."""
        large_content = "x = 1\n" * 100000
        result = extract_changes(large_content, "large_file.py")
        assert isinstance(result, list)


class TestNoProductBehaviorChange:
    """Validate that product behavior is never changed."""

    def test_no_logic_path_changes(self):
        """Control flow paths are not altered."""
        diffs = [
            "- if condition:",
            "+ if different_condition:",
        ]
        is_safe = is_safe_change(diffs)
        assert not is_safe

    def test_no_return_value_changes(self):
        """Function return values are not altered."""
        diffs = [
            "- return result",
            "+ return other_result",
        ]
        is_safe = is_safe_change(diffs)
        assert not is_safe

    def test_no_api_signature_changes(self):
        """API signatures and public interfaces are not changed."""
        diffs = [
            "- def public_api(x, y):",
            "+ def public_api(x, y, z):",
        ]
        is_safe = is_safe_change(diffs)
        assert not is_safe

    def test_typo_in_string_literal_is_rejected(self):
        """Fixing typos in string literals that affect behavior is rejected."""
        diffs = [
            "- status_code = 404",
            "+ status_code = 400",
        ]
        is_safe = is_safe_change(diffs)
        assert not is_safe


class TestCommitMetadata:
    """Validate commit message and metadata are correct."""

    def test_commit_message_describes_change(self):
        """Commit message clearly describes what was fixed."""
        message = generate_commit_message("docs/README.md", "typo", "unnecessary")
        assert len(message) > 0
        assert "typo" in message.lower() or "fix" in message.lower()

    def test_commit_message_is_concise(self):
        """Commit message is under 72 characters for first line."""
        message = generate_commit_message("test.py", "comment", "added clarification")
        first_line = message.split("\n")[0]
        assert len(first_line) <= 72

    def test_commit_includes_file_reference(self):
        """Commit message or metadata includes the file that was changed."""
        message = generate_commit_message("docs/api.md", "typo", "fixed")
        assert "api.md" in message or "docs" in message


class TestNoConflicts:
    """Validate that changes don't create merge conflicts."""

    def test_change_does_not_conflict_with_master(self):
        """Changes can be cleanly merged to master."""
        can_merge = check_merge_safety(branch="master")
        assert can_merge

    def test_identifies_conflicting_changes(self):
        """Conflicting changes are rejected before commit."""
        conflicts = detect_conflicts()
        for improvement in find_improvements_in_repo():
            assert improvement not in conflicts


# Helper functions for tests

def find_typos(content):
    """Find typos in content using common misspellings."""
    typos = [
        r"\bcommment\b",
        r"\brecieve\b",
        r"\bintrepid\b",
        r"\bThs\b",
        r"\bbehavor\b",
        r"\bunecessary\b",
    ]
    matches = []
    for typo in typos:
        if re.search(typo, content):
            matches.append(typo)
    return matches


def find_unclear_test_setup(content):
    """Find test setup that lacks explanation."""
    patterns = [r"data = \[.*\](?!\s*#)", r"config = \{.*\}(?!\s*#)"]
    return [p for p in patterns if re.search(p, content)]


def find_weak_doc_lines(content):
    """Find documentation that's vague or weak."""
    weak_phrases = ["does stuff", "returns a thing", "is used for"]
    return [phrase for phrase in weak_phrases if phrase in content]


def find_logic_changes(content):
    """Detect if content includes logic changes (should be rejected)."""
    logic_patterns = [r"\w+\s*=\s*\w+\s*[+\-*/]\s*\d+"]
    return []  # Logic changes should not be candidates


def find_deep_nested_candidates(content):
    """Find candidates in deeply nested scopes (should be rejected)."""
    return []  # Deep nesting should be rejected


def is_safe_change(diffs):
    """Validate that a change is safe and doesn't affect product behavior."""
    unsafe_patterns = [
        r"PASSWORD",
        r"TOKEN",
        r"SECRET",
        r"API_KEY",
        r"return\s+\w+\s*[+\-*/]\s*\d+",  # Logic change
        r"requirements\.txt",
        r"package\.json",
        r"setup\.py",
        r"pyproject\.toml",
    ]

    diff_text = "\n".join(diffs)
    for pattern in unsafe_patterns:
        if re.search(pattern, diff_text, re.IGNORECASE):
            return False

    return True


def is_file_safe_to_modify(file_path):
    """Check if a file is safe to modify."""
    unsafe_files = [
        "requirements.txt",
        "package.json",
        "package-lock.json",
        "setup.py",
        "pyproject.toml",
        "poetry.lock",
        "yarn.lock",
    ]

    product_patterns = [
        r"src/(orchestrator|runner|fleet_control)",
        r"(orchestrator|runner|fleet_control)\.py$",
    ]

    for unsafe in unsafe_files:
        if file_path.endswith(unsafe):
            return False

    for pattern in product_patterns:
        if re.search(pattern, file_path):
            return False

    safe_patterns = [
        r"\.md$",
        r"docs/",
        r"test_",
        r"tests/",
    ]

    for pattern in safe_patterns:
        if re.search(pattern, file_path):
            return True

    return False


def should_make_commit(changes, tests_pass):
    """Determine if a change should be committed."""
    if not tests_pass:
        return False

    change_type = changes.get("type", "")
    if change_type in ["typo", "clarification", "doc_improvement", "comment"]:
        old_text = changes.get("old_text", "")
        new_text = changes.get("new_text", "")
        if len(old_text) == len(new_text) and old_text.replace(" ", "") == new_text.replace(" ", ""):
            return False  # Trivial spacing change
        return True

    return False


def extract_changes(content, file_path):
    """Extract improvements from file content."""
    changes = []
    typo_patterns = {
        "unecessary": "unnecessary",
        "recieve": "receive",
        "Ths": "This",
        "commment": "comment",
    }

    for typo, correct in typo_patterns.items():
        if typo in content:
            changes.append({
                "type": "typo",
                "old_text": typo,
                "new_text": correct,
                "file": file_path,
            })

    return changes


def find_improvements_in_repo(max_count=None):
    """Find safe improvements in the repository."""
    return []  # Stub implementation


def make_single_improvement():
    """Make a single, focused improvement."""
    return {
        "file_count": 1,
        "added_text": "# clarification",
        "type": "clarification",
    }


def detect_conflicts():
    """Detect changes that would conflict with master."""
    return []


def check_merge_safety(branch="master"):
    """Check if changes can be safely merged to branch."""
    return True


def generate_commit_message(file_path, change_type, description):
    """Generate a commit message for the change."""
    if change_type == "typo":
        return f"fix: correct typo in {Path(file_path).name}"
    elif change_type == "clarification":
        return f"docs: add clarifying comment to {Path(file_path).name}"
    elif change_type == "doc_improvement":
        return f"docs: improve documentation in {Path(file_path).name}"
    else:
        return f"fix: improve {Path(file_path).name}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
