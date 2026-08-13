"""FAIL_SOFT_ERROR must fire on silence, not on breadth — plus the documented `# noqa`.

Backlog batch 01b6ed7 collapsed four intents; the two live ones were
"enhance error handling and logging" and "convention-conformance-lints". They meet here:
the linter's error-handling rule flagged every handler without a `return`, which is the
opposite of this repo's convention and produced 5,849 findings in runner/ alone. A rule
that fires 5,849 times is a rule nobody reads, so real silent swallows shipped underneath
it. After this change the same scan reports 1,328 — every one an actual
`except ...: pass`.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))

from lint_conventions import check_file, is_suppressed  # noqa: E402


def findings(code, rule='FAIL_SOFT_ERROR'):
    with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False) as fh:
        fh.write(code)
        path = fh.name
    try:
        return [v for v in check_file(path) if v.rule == rule]
    finally:
        os.unlink(path)


class TestSilenceIsTheDefect(unittest.TestCase):
    def test_bare_pass_is_flagged(self):
        self.assertEqual(len(findings("try:\n    f()\nexcept Exception:\n    pass\n")), 1)

    def test_logged_and_continued_is_the_convention(self):
        # branch_lease's documented shape: "heartbeat RPC infra error (...); fail-soft ALIVE".
        self.assertEqual(findings(
            "try:\n    f()\nexcept Exception as e:\n    logger.warning('infra error: %s', e)\n"), [])

    def test_returning_a_default_is_fine(self):
        self.assertEqual(findings("def g():\n    try:\n        return f()\n"
                                  "    except Exception:\n        return ''\n"), [])

    def test_reraise_is_fine(self):
        self.assertEqual(findings("try:\n    f()\nexcept Exception:\n    raise\n"), [])

    def test_continue_in_a_loop_is_fine(self):
        self.assertEqual(findings(
            "for x in y:\n    try:\n        f(x)\n    except Exception:\n        continue\n"), [])

    def test_conditional_log_still_clears(self):
        # The handler body is walked, so a log nested under `if` counts.
        self.assertEqual(findings(
            "try:\n    f()\nexcept Exception:\n    if verbose:\n        print('failed')\n"), [])

    def test_recovery_assignment_counts_as_observable(self):
        self.assertEqual(findings(
            "def g():\n    try:\n        v = f()\n    except Exception:\n        v = None\n"
            "    return v\n"), [])

    def test_each_handler_is_reported_once(self):
        # The rule was evaluated twice per handler (visit_Try plus a walk of the enclosing
        # function), so every finding appeared as two identical lines.
        found = findings("def g():\n    try:\n        f()\n    except Exception:\n        pass\n")
        self.assertEqual(len(found), 1)

    def test_multiple_handlers_are_judged_independently(self):
        found = findings("try:\n    f()\nexcept ValueError:\n    pass\n"
                         "except KeyError:\n    logger.info('k')\n")
        self.assertEqual(len(found), 1)


class TestNoqaSuppression(unittest.TestCase):
    """CONVENTION_LINT.md promised `# noqa: RULE_NAME` since Phase 1; nothing implemented it."""

    def test_targeted_noqa_suppresses_only_its_rule(self):
        self.assertTrue(is_suppressed("    except Exception:  # noqa: FAIL_SOFT_ERROR", "FAIL_SOFT_ERROR"))
        self.assertFalse(is_suppressed("    except Exception:  # noqa: FAIL_SOFT_ERROR", "MODULE_SINGLETON"))

    def test_bare_noqa_suppresses_everything_on_the_line(self):
        self.assertTrue(is_suppressed("x = 1  # noqa", "ANY_RULE"))

    def test_rule_lists_and_casing_are_accepted(self):
        line = "x = 1  # NOQA: fail_soft_error, MODULE_SINGLETON"
        self.assertTrue(is_suppressed(line, "FAIL_SOFT_ERROR"))
        self.assertTrue(is_suppressed(line, "MODULE_SINGLETON"))
        self.assertFalse(is_suppressed(line, "HARDCODED_SECRET"))

    def test_no_comment_suppresses_nothing(self):
        self.assertFalse(is_suppressed("    pass", "FAIL_SOFT_ERROR"))

    def test_end_to_end_suppression_through_check_file(self):
        # Without the escape hatch the only override is `--no-verify`, which drops every
        # rule for the whole commit instead of one line that stays visible in the diff.
        self.assertEqual(
            findings("try:\n    f()\nexcept Exception:  # noqa: FAIL_SOFT_ERROR\n    pass\n"), [])
        self.assertEqual(
            len(findings("try:\n    f()\nexcept Exception:  # noqa: OTHER_RULE\n    pass\n")), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
