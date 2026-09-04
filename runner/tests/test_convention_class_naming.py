<<<<<<< HEAD
"""Narrow regression coverage for the CLASS_NAMING convention lint.

Before this rule existed the checker held functions to snake_case but never looked at
class names at all, so `class taskRunner:` reached review unflagged. These tests pin
both halves of the contract: the rule fires on a real style break, and it stays quiet
on the shapes that are legitimately PascalCase.
"""

import os
import sys
import tempfile
import unittest
from typing import List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

from lint_conventions import ConventionViolation, check_file


class ClassNamingLintTest(unittest.TestCase):
    def _check(self, code: str) -> List[ConventionViolation]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as fh:
            fh.write(code)
            fh.flush()
            path = fh.name
        try:
            return check_file(path)
        finally:
            os.unlink(path)

    def _class_naming(self, code: str) -> List[ConventionViolation]:
        return [v for v in self._check(code) if v.rule == 'CLASS_NAMING']

    def test_flags_lower_camel_class_name(self):
        violations = self._class_naming("class taskRunner:\n    pass\n")
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].severity, 'warning')
        self.assertIn('taskRunner', violations[0].message)
        self.assertEqual(violations[0].lineno, 1)

    def test_flags_snake_case_class_name(self):
        violations = self._class_naming("class task_runner:\n    pass\n")
        self.assertEqual(len(violations), 1)
        self.assertIn('task_runner', violations[0].message)

    def test_accepts_pascal_case_acronyms_and_digits(self):
        code = (
            "class Runner:\n    pass\n\n"
            "class HTTPClient:\n    pass\n\n"
            "class Rule2Compiler:\n    pass\n"
        )
        self.assertEqual(self._class_naming(code), [])

    def test_ignores_private_class_names(self):
        self.assertEqual(self._class_naming("class _Internal:\n    pass\n"), [])
        self.assertEqual(self._class_naming("class _internal:\n    pass\n"), [])

    def test_severity_is_warning_so_the_merge_train_is_not_newly_blocked(self):
        violations = self._class_naming("class badName:\n    pass\n")
        self.assertTrue(violations)
        self.assertTrue(all(v.severity == 'warning' for v in violations))

    def test_methods_inside_a_class_still_get_function_naming_treatment(self):
        code = "class Runner:\n    def BadMethod(self):\n        pass\n"
        rules = {v.rule for v in self._check(code)}
        self.assertIn('NAMING_CONVENTION', rules)
        self.assertNotIn('CLASS_NAMING', rules)

    def test_nested_class_is_checked(self):
        code = "class Outer:\n    class innerThing:\n        pass\n"
        violations = self._class_naming(code)
        self.assertEqual(len(violations), 1)
        self.assertIn('innerThing', violations[0].message)

    def test_module_level_function_detection_survives_class_traversal(self):
        """visit_ClassDef restores in_module_level, so later module functions still lint."""
        code = (
            "class Runner:\n"
            "    def ok(self):\n"
            "        pass\n"
            "\n"
            "def stray(self):\n"
            "    pass\n"
        )
        rules = {v.rule for v in self._check(code)}
        self.assertIn('MODULE_SINGLETON_PATTERN', rules)


if __name__ == '__main__':
    unittest.main()
=======
#!/usr/bin/env python3
"""Tests for the CapWords class-name lint rule in convention_rule_gen."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import convention_rule_gen as crg


def _write(repo, name, body):
    path = os.path.join(repo, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(body)
    return path


class TestIsCapWords:
    def test_accepts_capwords(self):
        for name in ("MyClass", "Foo", "HTTPServer", "PMIClient", "A"):
            assert crg.is_capwords(name) is True, name

    def test_rejects_snake_and_camel(self):
        for name in ("my_class", "myClass", "_private", "MY_CONSTANT", "My_Class"):
            assert crg.is_capwords(name) is False, name

    def test_trailing_underscore_escape_is_tolerated(self):
        assert crg.is_capwords("Class_") is True

    def test_empty_is_not_capwords(self):
        assert crg.is_capwords("") is False
        assert crg.is_capwords(None) is False


class TestRuleShape:
    def test_rule_is_advisory_by_default(self):
        """Adding a rule must never newly hard-block the merge train."""
        assert crg.class_naming_rule()["severity"] == "warn"

    def test_rule_is_included_in_generated_ruleset(self):
        with tempfile.TemporaryDirectory() as repo:
            _write(repo, "CLAUDE.md", "# Conventions\n\n- No `console.log` in production code\n")
            rs = crg.generate(repo)
            ids = [r["id"] for r in rs["rules"]]
            assert crg.CLASS_NAMING_RULE_ID in ids

    def test_generated_even_without_claude_md(self):
        with tempfile.TemporaryDirectory() as repo:
            rs = crg.generate(repo)
            assert crg.CLASS_NAMING_RULE_ID in [r["id"] for r in rs["rules"]]

    def test_enforce_list_stays_empty(self):
        with tempfile.TemporaryDirectory() as repo:
            assert crg.generate(repo)["enforce"] == []


class TestCheckPython:
    def test_flags_snake_case_class(self):
        with tempfile.TemporaryDirectory() as repo:
            _write(repo, "mod.py", "class my_class:\n    pass\n")
            v = crg.check(repo, ruleset=crg.generate(repo))
            assert len(v) == 1
            assert v[0]["rule"] == crg.CLASS_NAMING_RULE_ID
            assert v[0]["line"] == 1
            assert "my_class" in v[0]["message"]
            assert v[0]["severity"] == "warn"

    def test_flags_lower_camel_class(self):
        with tempfile.TemporaryDirectory() as repo:
            _write(repo, "mod.py", "class myClass(Base):\n    pass\n")
            assert len(crg.check(repo, ruleset=crg.generate(repo))) == 1

    def test_accepts_capwords_class(self):
        with tempfile.TemporaryDirectory() as repo:
            _write(repo, "mod.py", "class MyClass(Base):\n    pass\n\nclass HTTPServer:\n    pass\n")
            assert crg.check(repo, ruleset=crg.generate(repo)) == []

    def test_indented_class_is_checked(self):
        with tempfile.TemporaryDirectory() as repo:
            _write(repo, "mod.py", "def f():\n    class inner_thing:\n        pass\n")
            v = crg.check(repo, ruleset=crg.generate(repo))
            assert len(v) == 1 and v[0]["line"] == 2

    def test_the_word_class_in_prose_is_not_matched(self):
        with tempfile.TemporaryDirectory() as repo:
            _write(repo, "mod.py",
                   '"""Pick the right class for the job."""\nx = "class not_a_class:"\n')
            assert crg.check(repo, ruleset=crg.generate(repo)) == []


class TestCheckTypeScript:
    def test_flags_exported_lower_camel_class(self):
        with tempfile.TemporaryDirectory() as repo:
            _write(repo, "a.ts", "export class myService {}\n")
            v = crg.check(repo, ruleset=crg.generate(repo))
            assert len(v) == 1 and "myService" in v[0]["message"]

    def test_accepts_abstract_and_default_exports(self):
        with tempfile.TemporaryDirectory() as repo:
            _write(repo, "a.ts", "export abstract class BaseThing {}\n")
            _write(repo, "b.tsx", "export default class Widget {}\n")
            assert crg.check(repo, ruleset=crg.generate(repo)) == []


class TestIntegrationWithExistingRules:
    def test_forbidden_pattern_rules_still_fire(self):
        with tempfile.TemporaryDirectory() as repo:
            _write(repo, "CLAUDE.md", "- No `console.log` in production code\n")
            _write(repo, "a.ts", "console.log('x');\nexport class my_thing {}\n")
            v = crg.check(repo, ruleset=crg.generate(repo))
            kinds = {x["rule"] for x in v}
            assert crg.CLASS_NAMING_RULE_ID in kinds
            assert any(r != crg.CLASS_NAMING_RULE_ID for r in kinds), "token rule should also fire"

    def test_promotion_to_error_is_possible_but_opt_in(self):
        with tempfile.TemporaryDirectory() as repo:
            _write(repo, "mod.py", "class my_class:\n    pass\n")
            rs = crg.generate(repo)
            rs["enforce"] = [crg.CLASS_NAMING_RULE_ID]
            assert crg.check(repo, ruleset=rs)[0]["severity"] == "error"

    def test_empty_ruleset_is_survivable(self):
        with tempfile.TemporaryDirectory() as repo:
            _write(repo, "mod.py", "class my_class:\n    pass\n")
            assert crg.check(repo, ruleset={"rules": []}) == []

    def test_unreadable_repo_is_not_fatal(self):
        assert isinstance(crg.check("/nonexistent/repo", ruleset=crg.generate(".")), list)


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
>>>>>>> agent/improve-enhance-testing-framework-slice-4
