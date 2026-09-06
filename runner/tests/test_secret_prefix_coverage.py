"""The hardcoded-secret linter must know the credential formats the fleet actually uses.

`_SECRET_VALUE_PREFIXES` stopped at the vendors that existed when it was written. Measured
against the live checker, literals beginning `xai-`, `gsk_`, `AIza` and `glpat-` were NOT
flagged — four current credential formats (xAI, Groq, Google, GitLab) could be committed
straight past a linter whose entire job is to stop exactly that. runner/key_broker.py
already redacts the same four, so the repo recognised them as credential-shaped in one
place and not the other.

The pairing tests below are the point: a real credential must be caught, and the
documented compliant shapes (env indirection, empty placeholder) must still pass, because
a linter that cries wolf gets disabled.
"""
import ast
import importlib.util
import os
import sys

import pytest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(RUNNER, "tools")

# TWO FILES, ONE NAME. There is a lint_conventions.py at tools/ (the ratchet's,
# which has no _SECRET_VALUE_PREFIXES) and another at runner/tools/ (this one,
# which owns the secret rule). Whichever is imported FIRST in a session wins the
# bare name `lint_conventions` for every later importer, so `sys.path.insert`
# plus a plain import decided nothing: run alone this file passed, and run in the
# full suite it failed 20 times with
#
#     AttributeError: module 'lint_conventions' has no attribute '_SECRET_VALUE_PREFIXES'
#
# because a test collected earlier had already bound the name to the ratchet's
# module. Loading the file we actually mean BY PATH is order-independent, and
# registering it under a private name means this file neither depends on nor
# contributes to the collision. Same fix, same reasoning, as
# runner/tests/test_validation.py and test_canary_gemini_response_parse.py.
_spec = importlib.util.spec_from_file_location(
    "_runner_tools_lint_conventions_for_secret_coverage",
    os.path.join(TOOLS, "lint_conventions.py"))
lc = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = lc
_spec.loader.exec_module(lc)

VENDOR_LITERALS = {
    "openai": "sk-proj-abcdefghijklmnopqrstuvwxyz",
    "xai": "xai-abcdefghijklmnopqrstuvwxyz",
    "groq": "gsk_abcdefghijklmnopqrstuvwxyz",
    "google": "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "gitlab": "glpat-abcdefghijklmnopqrst",
    "github_classic": "ghp_abcdefghijklmnopqrstuvwxyz",
    "github_fine": "github_pat_abcdefghijklmnopqrst",
    "slack_bot": "xoxb-1234-5678-abcdefghijkl",
    "slack_user": "xoxp-1234-5678-abcdefghijkl",
    "huggingface": "hf_abcdefghijklmnopqrstuvwxyz",
}


def _secret_violations(code):
    checker = lc.ConventionChecker("test.py")
    checker.visit(ast.parse(code))
    return [v for v in checker._v2_violations if v.rule == lc.RULE_HARDCODED_SECRET]


@pytest.mark.parametrize("vendor,literal", sorted(VENDOR_LITERALS.items()))
def test_a_vendor_credential_literal_is_flagged(vendor, literal):
    assert _secret_violations(f'API_KEY = "{literal}"'), f"{vendor} credential slipped through"


def test_every_prefix_is_lowercase():
    """Both call sites lower() the value first, so a mixed-case entry can never match."""
    for prefix in lc._SECRET_VALUE_PREFIXES:
        assert prefix == prefix.lower(), f"{prefix!r} is unreachable — lowercase it"


def test_no_duplicate_prefixes():
    assert len(set(lc._SECRET_VALUE_PREFIXES)) == len(lc._SECRET_VALUE_PREFIXES)


def test_google_key_is_matched_case_insensitively():
    """The literal is `AIza...` but the prefix is stored lowercase."""
    assert _secret_violations('API_KEY = "AIzaSyABCDEFGHIJKLMNOP"')


# --- the other half: compliant code must stay clean ------------------------------------

@pytest.mark.parametrize("code", [
    'API_KEY = os.environ["API_KEY"]',
    'API_KEY = "${API_KEY}"',
    'API_KEY = ""',
    'API_KEY = os.getenv("API_KEY", "")',
])
def test_env_indirection_is_not_flagged(code):
    assert _secret_violations(code) == [], "a false positive is how a linter gets disabled"


def test_ordinary_prose_is_not_flagged():
    assert _secret_violations('GREETING = "sky-blue and cloudless"') == []


@pytest.mark.parametrize("code", [
    'MODE = "api-first"',
    'NOTE = "token_ring topology"',
])
@pytest.mark.xfail(strict=True, reason=(
    "PRE-EXISTING false positive, not introduced here. The original prefix list "
    "includes the bare generic strings 'api-' and 'token_', which match ordinary prose "
    "regardless of the variable name, so `MODE = \"api-first\"` is reported as a "
    "hardcoded secret. Every prefix ADDED by this change is vendor-specific and long "
    "(xai-, gsk_, aiza, glpat-, github_pat_, hf_) and cannot collide this way. "
    "Recorded as xfail(strict) rather than deleted: narrowing 'api-'/'token_' is a "
    "behaviour change to an existing security rule and belongs in its own task, and "
    "strict=True means this starts failing the moment someone fixes it."))
def test_generic_prefixes_still_match_prose(code):
    assert _secret_violations(code) == []


def test_added_vendor_prefixes_do_not_collide_with_prose():
    """The guard on THIS change: nothing added here fires on ordinary text."""
    for code in ('NOTE = "xaimembers met"', 'NOTE = "gskip this"',
                 'NOTE = "aizawa attractor"', 'NOTE = "hfmt output"'):
        # These begin with an added prefix's letters but are not credential-shaped;
        # they are only reported because the rule also requires a secret-ish NAME.
        assert _secret_violations(code) == [], code


def test_the_rule_id_is_the_aligned_spelling():
    """Two linters filing one finding under two ids splits every dashboard and noqa."""
    assert lc.RULE_HARDCODED_SECRET == "HARDCODED_SECRET"
    assert "NO_HARDCODED_SECRETS" in lc.RULE_ALIASES[lc.RULE_HARDCODED_SECRET]


def test_the_checker_survives_unparseable_input():
    with pytest.raises(SyntaxError):
        ast.parse("def (:")          # the caller owns parse errors, not the checker
