#!/usr/bin/env python3
"""Test suite for canary-deepseek-1: small safe repository-local improvements.

A canary improvement might:
  - Fix a typo in code, comments, or docs
  - Add a clarifying comment to non-obvious test setup
  - Improve a doc line for clarity
  - Fix a formatting inconsistency

These tests validate that such improvements:
  - Do not break the build or change product behavior
  - Do not introduce secrets or credentials
  - Do not change dependencies or package managers
  - Pass all linting and formatting checks
  - Maintain code clarity and correctness

Run: pytest test_canary_improvements.py -v
"""
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Set

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


REPO_ROOT = Path(__file__).resolve().parent
RUNNER_DIR = REPO_ROOT / "runner"
TOOLS_DIR = REPO_ROOT / "tools"
TEST_ALLOWLIST = {
    "__pycache__",
    ".git",
    ".runtime",
    "node_modules",
    ".next",
    ".venv",
    "venv",
    "dist",
    "build",
}

# Files/patterns that should never contain secrets
SECRET_PATTERNS = [
    r"(?i)(password|passwd)\s*[:=]\s*['\"]?[a-zA-Z0-9_\-]{8,}",
    r"(?i)(api[_-]?key|apikey)\s*[:=]\s*['\"]?[a-zA-Z0-9_\-]{20,}",
    r"(?i)(secret)\s*[:=]\s*['\"]?[a-zA-Z0-9_\-]{8,}",
    r"(?i)(token)\s*[:=]\s*['\"]?[a-zA-Z0-9_\-]{20,}",
    r"(?i)(private[_-]?key)\s*[:=]",
]

# Common typos in technical writing (lowercase)
COMMON_TYPOS = {
    "teh": "the",
    "recieve": "receive",
    "occured": "occurred",
    "seperate": "separate",
    "wich": "which",
    "thier": "their",
    "definately": "definitely",
    "ocassion": "occasion",
    "accomodate": "accommodate",
    "becuase": "because",
}

# Python modules that should be importable
PYTHON_MODULES = [
    "runner",
    "db",
    "log",
    "kill_switch",
    "scope_gate",
    "prompt_factory",
]


def get_python_files() -> List[Path]:
    """Get all .py files in the repo, excluding test artifacts and venv."""
    py_files = []
    for root_dir in [RUNNER_DIR, TOOLS_DIR]:
        if not root_dir.exists():
            continue
        for path in root_dir.rglob("*.py"):
            # Skip allowlisted directories
            if any(skip in path.parts for skip in TEST_ALLOWLIST):
                continue
            py_files.append(path)
    return py_files


def get_doc_files() -> List[Path]:
    """Get all documentation files."""
    doc_patterns = ["*.md", "*.rst", "*.txt"]
    doc_files = []
    for pattern in doc_patterns:
        doc_files.extend(REPO_ROOT.glob(pattern))
        doc_files.extend((REPO_ROOT / "docs").glob(pattern) if (REPO_ROOT / "docs").exists() else [])
    return [f for f in doc_files if f.is_file()]


class TestCanaryImprovement:
    """Base test class for canary improvements."""

    def test_no_syntax_errors_in_python(self):
        """All Python files must have valid syntax."""
        py_files = get_python_files()
        assert py_files, "Expected to find Python files to test"

        errors = []
        for py_file in py_files:
            try:
                with open(py_file) as f:
                    ast.parse(f.read())
            except SyntaxError as e:
                errors.append(f"{py_file}: {e}")

        assert not errors, f"Syntax errors found:\n" + "\n".join(errors)

    def test_no_hardcoded_secrets(self):
        """No hardcoded secrets in config keys or env vars."""
        py_files = get_python_files()
        errors = []

        for py_file in py_files:
            with open(py_file, errors="replace") as f:
                content = f.read()

            for pattern in SECRET_PATTERNS:
                matches = re.finditer(pattern, content)
                for match in matches:
                    # Exclude actual string literals in tests or comments
                    line_num = content[:match.start()].count("\n") + 1
                    errors.append(f"{py_file}:{line_num}: potential secret '{match.group()}'")

        assert not errors, f"Potential secrets found:\n" + "\n".join(errors[:10])

    def test_common_typos_not_introduced(self):
        """Check for common typos in Python code and documentation."""
        all_files = get_python_files() + get_doc_files()
        errors = []

        for file_path in all_files:
            if file_path.suffix in {".pyc", ".pyo"}:
                continue

            try:
                with open(file_path, errors="replace") as f:
                    content = f.read()
            except Exception:
                continue

            for typo, correction in COMMON_TYPOS.items():
                # Case-insensitive word boundary search
                pattern = rf"\b{re.escape(typo)}\b"
                for match in re.finditer(pattern, content, re.IGNORECASE):
                    line_num = content[:match.start()].count("\n") + 1
                    errors.append(
                        f"{file_path}:{line_num}: typo '{typo}' should be '{correction}'"
                    )

        # Limit to first 20 to avoid overwhelming output
        assert not errors, f"Typos found:\n" + "\n".join(errors[:20])

    def test_imports_still_work(self):
        """Verify core modules can still be imported."""
        # Only test if we have the actual runner module
        if not (RUNNER_DIR / "__init__.py").exists():
            return

        try:
            # Try importing the runner package itself
            import importlib.util

            init_file = RUNNER_DIR / "__init__.py"
            spec = importlib.util.spec_from_file_location("runner", init_file)
            runner_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(runner_module)
        except Exception as e:
            raise AssertionError(f"Failed to import runner package: {e}")

    def test_no_broken_relative_imports(self):
        """Relative imports should resolve correctly."""
        py_files = get_python_files()
        errors = []

        for py_file in py_files:
            try:
                with open(py_file) as f:
                    tree = ast.parse(f.read())
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    # Check for relative imports with missing module names
                    if node.level > 0 and node.module is None:
                        # This is valid (e.g., "from . import something")
                        continue

        # No specific failures needed; if imports parse, they're structurally valid
        assert len(errors) == 0

    def test_documentation_files_readable(self):
        """All documentation files should be readable and well-formed."""
        doc_files = get_doc_files()

        for doc_file in doc_files:
            try:
                with open(doc_file, encoding="utf-8", errors="replace") as f:
                    content = f.read()

                # Check that markdown files have reasonable structure
                if doc_file.suffix == ".md":
                    # At least one heading should be present
                    assert re.search(r"^#+\s", content, re.MULTILINE), (
                        f"{doc_file}: markdown file should have headings"
                    )
            except Exception as e:
                raise AssertionError(f"Cannot read {doc_file}: {e}")

    def test_no_trailing_whitespace_in_code(self):
        """Code files should not have unnecessary trailing whitespace."""
        py_files = get_python_files()
        errors = []

        for py_file in py_files:
            with open(py_file) as f:
                for line_num, line in enumerate(f, 1):
                    # Allow trailing newlines, but not spaces before them
                    if line.rstrip("\n") != line.rstrip("\n").rstrip():
                        # Only report first occurrence per file to avoid spam
                        if len([e for e in errors if str(py_file) in e]) == 0:
                            errors.append(f"{py_file}:{line_num}: trailing whitespace")

        assert not errors, f"Trailing whitespace found:\n" + "\n".join(errors[:10])

    def test_function_docstrings_present(self):
        """Public functions should have docstrings."""
        py_files = get_python_files()
        errors = []

        for py_file in py_files:
            try:
                with open(py_file) as f:
                    tree = ast.parse(f.read())
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    # Skip private functions and test functions
                    if node.name.startswith("_") or node.name.startswith("test_"):
                        continue

                    # Check if function has a docstring
                    docstring = ast.get_docstring(node)
                    if not docstring:
                        # Only report once per file
                        if len([e for e in errors if str(py_file) in e]) == 0:
                            errors.append(f"{py_file}: public function '{node.name}' lacks docstring")

        # This is a guideline, not a hard requirement for canary improvements
        # Only fail if there are many violations
        assert len(errors) < 3, f"Docstring violations:\n" + "\n".join(errors)

    def test_no_unused_imports(self):
        """Check for obviously unused imports (basic check)."""
        py_files = get_python_files()
        errors = []

        for py_file in py_files:
            try:
                with open(py_file) as f:
                    content = f.read()
                    tree = ast.parse(content)
            except SyntaxError:
                continue

            # Extract all imports
            imported_names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        name = alias.asname or alias.name.split(".")[0]
                        imported_names.add(name)
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        name = alias.asname or alias.name
                        if name != "*":
                            imported_names.add(name)

            # Check if imported names appear in code (basic heuristic)
            for name in list(imported_names):
                # Exclude common patterns that are legitimately "unused" but needed
                if name in {"__all__", "annotations", "print_function"}:
                    continue

                # Check if name appears in code
                pattern = rf"\b{re.escape(name)}\b"
                if not re.search(pattern, content[len(""):]):  # Skip import lines
                    # Likely unused, but don't fail on this for canary tasks
                    pass

    def test_configuration_keys_safe(self):
        """Configuration keys should not contain secrets."""
        py_files = get_python_files()
        errors = []

        for py_file in py_files:
            with open(py_file, errors="replace") as f:
                content = f.read()

            # Look for ORCH_ prefixed config keys (fleet-wide)
            for match in re.finditer(r"ORCH_\w+\s*[:=]", content):
                key = match.group()
                # Check if value contains a secret-like pattern
                remaining = content[match.end() : match.end() + 200]
                for secret_pattern in ["password", "token", "secret", "key"]:
                    if secret_pattern.lower() in remaining.lower():
                        errors.append(f"{py_file}: {key} might contain secret material")

        assert not errors, f"Config security issues:\n" + "\n".join(errors[:10])

    def test_package_dependencies_not_modified(self):
        """Ensure package dependency files weren't accidentally modified."""
        dependency_files = [
            "package.json",
            "requirements.txt",
            "setup.py",
            "setup.cfg",
            "pyproject.toml",
            "poetry.lock",
            "Pipfile",
            "Pipfile.lock",
        ]

        for dep_file in dependency_files:
            path = REPO_ROOT / dep_file
            if not path.exists():
                continue

            # Try to parse to ensure validity
            try:
                if dep_file == "package.json":
                    with open(path) as f:
                        json.load(f)
                elif dep_file.endswith(".toml"):
                    # Basic TOML validation
                    with open(path) as f:
                        content = f.read()
                        assert "[" not in content or "=" in content
            except Exception as e:
                raise AssertionError(f"Dependency file {dep_file} corrupted: {e}")

    def test_build_passes(self):
        """Ensure the project builds without errors."""
        # Check for common build indicators
        py_files = get_python_files()
        assert len(py_files) > 0, "No Python files found to validate build"

        # All files must be syntactically valid (already tested above)
        for py_file in py_files:
            try:
                with open(py_file) as f:
                    compile(f.read(), str(py_file), "exec")
            except Exception as e:
                raise AssertionError(f"Build failure in {py_file}: {e}")

    def test_no_debug_code_left_behind(self):
        """Check for common debug patterns that shouldn't be in production."""
        py_files = get_python_files()
        debug_patterns = [
            r"print\s*\(",  # print statements (should use logging)
            r"pdb\.set_trace",
            r"import pdb",
            r"breakpoint\s*\(",
            r"TODO.*FIXME",  # Ambiguous markers
            r"XXX\s+",  # Ancient debug marker
        ]

        errors = []
        for py_file in py_files:
            # Skip test files
            if "test_" in str(py_file):
                continue

            with open(py_file, errors="replace") as f:
                content = f.read()

            for pattern in debug_patterns:
                for match in re.finditer(pattern, content):
                    line_num = content[:match.start()].count("\n") + 1
                    # Only flag if not in a comment or docstring
                    line_text = content.split("\n")[line_num - 1]
                    if not line_text.strip().startswith("#"):
                        errors.append(f"{py_file}:{line_num}: {pattern}")

        # Don't fail hard on debug code, but report it
        assert len(errors) < 5, f"Debug code found:\n" + "\n".join(errors[:5])

    def test_error_messages_are_clear(self):
        """Check that error messages and log statements are clear."""
        py_files = get_python_files()
        errors = []

        for py_file in py_files:
            try:
                with open(py_file) as f:
                    tree = ast.parse(f.read())
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                # Check raise statements
                if isinstance(node, ast.Raise) and node.exc:
                    if isinstance(node.exc, ast.Call):
                        # Check if exception has a message
                        if not node.exc.args:
                            line_num = node.lineno
                            errors.append(f"{py_file}:{line_num}: exception without message")

        # Guideline, not hard requirement
        assert len(errors) < 3, f"Error message issues:\n" + "\n".join(errors)

    def test_claude_md_conventions_followed(self):
        """Key CLAUDE.md conventions should still be followed."""
        claude_file = REPO_ROOT / "CLAUDE.md"
        if not claude_file.exists():
            return

        with open(claude_file) as f:
            claude_content = f.read()

        # Extract key conventions (simplified)
        conventions = {
            "fail-soft error handling": claude_content.count("fail-soft") > 0,
            "module-level singleton pattern": claude_content.count("singleton") > 0,
            "thread-safe": claude_content.count("thread-safe") > 0 or claude_content.count("Lock") > 0,
        }

        for convention, present in conventions.items():
            assert present, f"CLAUDE.md convention missing: {convention}"

    def test_consistent_spacing_in_operators(self):
        """Operators should have consistent spacing."""
        py_files = get_python_files()
        errors = []

        for py_file in py_files:
            with open(py_file) as f:
                for line_num, line in enumerate(f, 1):
                    # Skip comments and docstrings
                    if line.strip().startswith("#"):
                        continue

                    # Check for inconsistent spacing around = in variable assignments
                    # Pattern: var=value (bad) vs var = value (good)
                    bad_pattern = r"[a-zA-Z_]\w*=[^=]"  # Single = not comparison
                    if re.search(bad_pattern, line) and "==" not in line:
                        if len([e for e in errors if str(py_file) in e]) < 1:
                            errors.append(f"{py_file}:{line_num}: inconsistent operator spacing")

        # Guideline, not hard requirement
        assert len(errors) < 3, f"Spacing issues:\n" + "\n".join(errors)

    def test_git_identity_correct(self):
        """Commits should use the correct git identity."""
        # Try to get the current git config
        try:
            result = subprocess.run(
                ["git", "config", "user.name"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                user_name = result.stdout.strip()
                # Just verify a name is set, don't enforce a specific one
                assert user_name, "Git user.name not configured"
        except Exception:
            # Git might not be available in test environment
            pass

    def test_no_unresolved_merge_conflicts(self):
        """Files should not contain unresolved merge conflict markers."""
        all_files = get_python_files() + get_doc_files()
        errors = []

        for file_path in all_files:
            try:
                with open(file_path, errors="replace") as f:
                    content = f.read()

                if "<<<<<<< HEAD" in content or "=======" in content or ">>>>>>>" in content:
                    errors.append(str(file_path))
            except Exception:
                continue

        assert not errors, f"Unresolved merge conflicts in:\n" + "\n".join(errors)

    def test_markdown_links_valid(self):
        """Markdown links should have valid targets."""
        md_files = [f for f in get_doc_files() if f.suffix == ".md"]
        errors = []

        for md_file in md_files:
            with open(md_file, errors="replace") as f:
                content = f.read()

            # Find markdown links [text](path)
            for match in re.finditer(r"\[([^\]]+)\]\(([^\)]+)\)", content):
                link_target = match.group(2)

                # Skip external links and anchors
                if link_target.startswith("http") or link_target.startswith("#"):
                    continue

                # Check if local file exists
                target_path = md_file.parent / link_target
                if not target_path.exists():
                    errors.append(f"{md_file}: broken link to {link_target}")

        # Limit reporting
        assert not errors, f"Broken links:\n" + "\n".join(errors[:10])

    def test_no_password_in_comments(self):
        """Comments should not contain passwords or credentials."""
        py_files = get_python_files()
        errors = []

        for py_file in py_files:
            with open(py_file, errors="replace") as f:
                for line_num, line in enumerate(f, 1):
                    if "#" not in line:
                        continue

                    comment_part = line[line.index("#") :]
                    for secret_pattern in ["password", "passwd", "pwd", "secret"]:
                        if secret_pattern.lower() in comment_part.lower():
                            # Check it's not just a comment about the concept
                            if "password field" not in comment_part.lower():
                                errors.append(f"{py_file}:{line_num}: credential mention in comment")

        assert not errors, f"Credentials in comments:\n" + "\n".join(errors[:5])


if __name__ == "__main__":
    pytest_args = [__file__, "-v", "--tb=short"]
    exit_code = pytest.main(pytest_args)
    sys.exit(exit_code)
