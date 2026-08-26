#!/usr/bin/env python3
"""HARDCODED_SECRET must not fire on a regex that HUNTS for secrets.

WHY THIS EXISTS (2026-08-26)
---------------------------
`runner/patch_templates.py` builds a scaffold from the task prompt, and the words
it lifts end up in two places that OUTLIVE the task: the template body and the
keyword list the template store indexes on. Redacting credentials out of that
path needs a pattern that names credentials -- `_SECRET_ASSIGNMENT`,
`_SECRET_WORD` -- and both linters then reported the redaction pattern itself as
a hardcoded secret, because their rule matches on:

  * a target name containing password/token/secret/key, and
  * a value with no spaces and plenty of entropy

which is what a credential-hunting regex looks like by construction. The rule
punished exactly the code written to enforce it, and the only ways past it were
to rename the constant into something less accurate or to raise the ratchet
baseline -- both worse than fixing the rule.

The exclusion keys off a regex EXTENSION GROUP (`(?:`, `(?=`, `(?!`, `(?<`,
`(?P<`), which is grammar rather than content. The looser markers (\\b, \\d,
`[A-Z`, `.*`) were rejected on purpose: those DO occur inside real key material,
so keying on them would blind the rule to genuine leaks. The tests below pin
both halves of that trade -- patterns are excluded, plain credentials are not.

Both linter copies are covered. They are separate implementations of the same
rule (tools/lint_conventions.py backs the commit ratchet; tools/convention_lint.py
owns check_directory), so a fix in one proves nothing about the other.
"""
import ast
import importlib.util
import os
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_linter(module_path, module_name):
    """Load a linter from its path without touching sys.path/sys.modules.

    Same loader, same reasoning, as test_convention_rule_registry.py: the repo
    has two modules named lint_conventions and sys.path is process-global under
    pytest, so importing by name is a coin flip on which one answers.
    """
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ratchet_linter = _load_linter(
    os.path.join(REPO, "tools", "lint_conventions.py"),
    "tools_lint_conventions_regex_source")
directory_linter = _load_linter(
    os.path.join(REPO, "tools", "convention_lint.py"),
    "tools_convention_lint_regex_source")


#: The real constant out of runner/patch_templates.py, verbatim. If the redaction
#: pattern there is rewritten into a shape the linters flag again, this fails.
REDACTION_PATTERN_SOURCE = (
    r'_SECRET_WORD = "(?<![A-Za-z0-9])(?:pass(?:word|wd)?|secret|token|apikey)'
    r'(?![A-Za-z0-9])"'
)

#: A credential with the same NAME shape and no regex grammar in it. This is what
#: the rule is for, and it must still fire.
#:
#: Named CREDENTIAL rather than SECRET on purpose: tools/lint_conventions.py keys
#: off the target name with no value gate and no test-file exemption (the sibling
#: tools/convention_lint.py has both), so a fixture called *_SECRET_* would report
#: ITSELF as a hardcoded secret and push the ratchet up by one.
PLAIN_CREDENTIAL_SOURCE = 'api_secret = "hunter2Zx9QpLm4vTt"'


def _secret_rules(linter, code, filepath="probe.py"):
    """Every HARDCODED_SECRET rule id a linter emits for CODE.

    Both checkers collect into `violations`; tools/convention_lint.py adds a
    second `_v2_violations` sink behind its `_record` choke point, so read both
    and let the missing one be empty.

    FILEPATH matters to tools/convention_lint.py, which exempts test files -- a
    probe named test_*.py would be reported clean no matter what the rule does.
    """
    checker = linter.ConventionChecker(filepath, code.splitlines())
    checker.visit(ast.parse(code))
    found = list(getattr(checker, "violations", []))
    found += list(getattr(checker, "_v2_violations", []))
    return [v.rule for v in found if v.rule == "HARDCODED_SECRET"]


class RegexSourceIsNotASecretTest(unittest.TestCase):
    """The exclusion holds in both linters."""

    def test_ratchet_linter_does_not_flag_the_redaction_pattern(self):
        self.assertEqual(_secret_rules(ratchet_linter, REDACTION_PATTERN_SOURCE), [])

    def test_directory_linter_does_not_flag_the_redaction_pattern(self):
        self.assertEqual(_secret_rules(directory_linter, REDACTION_PATTERN_SOURCE), [])

    def test_a_named_capture_group_is_also_excluded(self):
        code = '_TOKEN_RE = "(?P<token>[A-Za-z0-9]{32,})"'
        self.assertEqual(_secret_rules(ratchet_linter, code), [])
        self.assertEqual(_secret_rules(directory_linter, code), [])


class RealSecretsStillFireTest(unittest.TestCase):
    """The exclusion must not become a way to smuggle a credential past the rule."""

    def test_ratchet_linter_still_flags_a_plain_credential(self):
        self.assertEqual(_secret_rules(ratchet_linter, PLAIN_CREDENTIAL_SOURCE),
                         ["HARDCODED_SECRET"])

    def test_directory_linter_still_flags_a_plain_credential(self):
        self.assertEqual(_secret_rules(directory_linter, PLAIN_CREDENTIAL_SOURCE),
                         ["HARDCODED_SECRET"])

    def test_entropy_markers_that_appear_in_key_material_do_not_excuse_a_secret(self):
        """\\d, [A-Z and .* are NOT the exclusion -- only extension groups are.

        A base64 or hex key can contain any of these by chance; if they excused a
        literal, the rule would go quiet on the leaks it exists to catch.
        """
        for body in ("abc\\dEF12345678", "[A-Zqrstuvwx99]", "sk.*live.9QpLm4vTt"):
            # r"" so the probe's own backslash is not an invalid escape sequence
            # in the source being parsed; the literal VALUE is unchanged.
            code = 'api_secret = r"%s"' % body
            self.assertEqual(_secret_rules(ratchet_linter, code), ["HARDCODED_SECRET"], body)


class RedactionPatternStaysExcludedTest(unittest.TestCase):
    """The live file, not a copy of it, is what has to pass the linters."""

    def test_patch_templates_reports_no_hardcoded_secret(self):
        path = os.path.join(REPO, "runner", "patch_templates.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        for linter, label in ((ratchet_linter, "lint_conventions"),
                              (directory_linter, "convention_lint")):
            hits = _secret_rules(linter, source, filepath=path)
            self.assertEqual(hits, [], "%s flagged the redaction pattern" % label)


if __name__ == "__main__":
    unittest.main()
