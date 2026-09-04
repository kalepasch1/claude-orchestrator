"""Tests for the SILENT_ERROR_NO_DIAGNOSTIC convention rule.

Consolidated backlog intent: "enhance error handling and logging". The repo's
dominant failure mode is not missing error handling, it is error handling that
succeeds at being fail-soft and fails at being diagnosable — the handler runs, the
error vanishes, and the operator sees a working-looking system that quietly does
nothing. This rule names that pattern.
"""
import ast
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "lint_conventions", REPO_ROOT / "runner" / "tools" / "lint_conventions.py"
)
lint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lint)

RULE = "SILENT_ERROR_NO_DIAGNOSTIC"


def _rules(source: str):
    checker = lint.ConventionChecker("<test>")
    checker.visit(ast.parse(source))
    return [v.rule for v in checker._v2_violations]


def test_flags_handler_that_discards_error_with_pass():
    src = "def f():\n    try:\n        g()\n    except ValueError:\n        pass\n"
    assert RULE in _rules(src)


def test_flags_handler_that_returns_default_without_reporting():
    """Returning a default satisfies fail-soft but still leaves no evidence."""
    src = "def f():\n    try:\n        return g()\n    except ValueError:\n        return None\n"
    assert RULE in _rules(src)


def test_does_not_flag_when_exception_is_bound():
    src = "def f():\n    try:\n        g()\n    except ValueError as e:\n        pass\n"
    assert RULE not in _rules(src)


def test_does_not_flag_when_handler_prints():
    src = "def f():\n    try:\n        g()\n    except ValueError:\n        print('g failed')\n"
    assert RULE not in _rules(src)


def test_does_not_flag_when_handler_logs():
    src = (
        "def f():\n    try:\n        g()\n"
        "    except ValueError:\n        logger.warning('g failed')\n"
    )
    assert RULE not in _rules(src)


def test_does_not_flag_when_handler_writes_to_stderr():
    src = (
        "def f():\n    try:\n        g()\n"
        "    except ValueError:\n        sys.stderr.write('g failed\\n')\n"
    )
    assert RULE not in _rules(src)


def test_does_not_flag_when_handler_reraises():
    src = "def f():\n    try:\n        g()\n    except ValueError:\n        raise\n"
    assert RULE not in _rules(src)


def test_does_not_flag_when_diagnostic_is_nested():
    """A report inside an if still counts as reporting."""
    src = (
        "def f():\n    try:\n        g()\n"
        "    except ValueError:\n        if verbose:\n            print('g failed')\n"
    )
    assert RULE not in _rules(src)


def test_flags_bare_except_with_no_diagnostic():
    src = "def f():\n    try:\n        g()\n    except:\n        pass\n"
    assert RULE in _rules(src)


def test_severity_is_warning_not_error():
    """Intentional swallows must be triageable, not build-blocking."""
    src = "def f():\n    try:\n        g()\n    except ValueError:\n        pass\n"
    checker = lint.ConventionChecker("<test>")
    checker.visit(ast.parse(src))
    silent = [v for v in checker._v2_violations if v.rule == RULE]
    assert silent and all(v.severity == "warning" for v in silent)


def test_multiple_handlers_are_each_evaluated():
    src = (
        "def f():\n    try:\n        g()\n"
        "    except ValueError:\n        print('reported')\n"
        "    except KeyError:\n        pass\n"
    )
    checker = lint.ConventionChecker("<test>")
    checker.visit(ast.parse(src))
    silent = [v for v in checker._v2_violations if v.rule == RULE]
    assert len(silent) == 1


def test_clean_code_produces_no_silent_error_violations():
    src = (
        "def f():\n    try:\n        return g()\n"
        "    except ValueError as e:\n        logger.warning('g failed: %s', e)\n"
        "        return None\n"
    )
    assert RULE not in _rules(src)


def _messages(source: str):
    checker = lint.ConventionChecker("<test>")
    checker.visit(ast.parse(source))
    return [v.message for v in checker._v2_violations if v.rule == RULE]


# The rule's remediation text is the only instruction most callers ever read, so
# it has to describe what the rule actually accepts. It used to offer "or add a
# comment naming why it is safe to ignore" while _is_silently_discarded ignores
# comments by design -- callers followed it literally (branch_lease.py:114,
# regression.py:36) and stayed flagged, which is how a linter earns a reputation
# for lying and starts getting skipped.
_COMMENTED_SWALLOW = (
    "def f():\n"
    "    try:\n"
    "        g()\n"
    "    except ValueError:\n"
    "        # the finite TTL is the fail-safe here, so dropping this is fine\n"
    "        pass\n"
)


def test_commented_swallow_is_still_flagged():
    """Documents the deliberate choice: a comment is not a runtime diagnostic."""
    assert RULE in _rules(_COMMENTED_SWALLOW)


def test_message_does_not_promise_a_comment_escape_hatch():
    messages = _messages(_COMMENTED_SWALLOW)
    assert messages
    for msg in messages:
        assert "safe to ignore" not in msg, (
            "remediation text offers a comment escape the rule does not honour"
        )


def test_message_names_remedies_that_actually_clear_the_rule():
    """bind-and-log and re-raise are the two paths _emits_diagnostic accepts."""
    for msg in _messages(_COMMENTED_SWALLOW):
        assert "except X as e" in msg
        assert "re-raise" in msg


def test_message_states_that_a_comment_is_insufficient():
    for msg in _messages(_COMMENTED_SWALLOW):
        assert "comment does not clear this warning" in msg


def test_documented_remedies_do_clear_the_rule():
    """The message is only honest if following it silences the warning."""
    bound_and_logged = (
        "def f():\n    try:\n        g()\n"
        "    except ValueError as e:\n        print('g failed', e)\n"
    )
    reraised = "def f():\n    try:\n        g()\n    except ValueError:\n        raise\n"
    assert RULE not in _rules(bound_and_logged)
    assert RULE not in _rules(reraised)
