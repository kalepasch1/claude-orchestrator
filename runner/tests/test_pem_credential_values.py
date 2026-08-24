"""PEM key material is a secret whatever the variable is called.

The hardcoded-secret rule decides mainly on the NAME, and the name heuristic
deliberately requires a compound token (`private_key`, not a bare `key`) — because
`key` is overwhelmingly a dict or cache key, and flagging it would drown the rule in
false positives and get it switched off.

That left a real hole:

    key = "-----BEGIN PRIVATE KEY-----"     # not flagged: the name is just "key"

A PEM header is not ambiguous the way a name is: no legitimate non-secret string begins
with one. Detecting the VALUE closes the hole without loosening the name heuristic, so
these tests come in pairs — the credential must be caught, and ordinary `key` variables
must stay clean.
"""
import ast
import os
import sys

import pytest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(RUNNER, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import lint_conventions as lc  # noqa: E402


def _secret_violations(code):
    checker = lc.ConventionChecker("test.py")
    checker.visit(ast.parse(code))
    return [v for v in checker._v2_violations if v.rule == lc.RULE_HARDCODED_SECRET]


PEM_HEADERS = [
    "-----BEGIN PRIVATE KEY-----",
    "-----BEGIN RSA PRIVATE KEY-----",
    "-----BEGIN OPENSSH PRIVATE KEY-----",
    "-----BEGIN EC PRIVATE KEY-----",
    "-----BEGIN DSA PRIVATE KEY-----",
    "-----BEGIN PGP PRIVATE KEY BLOCK-----",
    "-----BEGIN ENCRYPTED PRIVATE KEY-----",
    "-----BEGIN CERTIFICATE-----",
]


# --- caught regardless of name -----------------------------------------------------

@pytest.mark.parametrize("header", PEM_HEADERS)
def test_pem_material_is_flagged_under_an_innocuous_name(header):
    assert _secret_violations(f'key = "{header}"'), header


@pytest.mark.parametrize("name", ["key", "blob", "data", "cert", "value", "x"])
def test_any_variable_name_still_flags_pem_material(name):
    assert _secret_violations(f'{name} = "-----BEGIN PRIVATE KEY-----"')


def test_leading_whitespace_does_not_hide_it():
    assert _secret_violations('key = "\\n  -----BEGIN PRIVATE KEY-----"')


def test_case_does_not_hide_it():
    assert _secret_violations('key = "-----begin private key-----"')


# --- the other half: no new false positives ----------------------------------------

@pytest.mark.parametrize("code", [
    'key = "lookup-key"',
    'cache_key = "user:42"',
    'key = "id"',
    'sort_key = "created_at"',
    'primary_key = "id"',
])
def test_ordinary_key_variables_stay_clean(code):
    """The name heuristic is untouched, so these must behave exactly as before."""
    assert _secret_violations(code) == [], code


def test_a_string_merely_mentioning_pem_is_not_a_header():
    assert _secret_violations('note = "we store the -----BEGIN PRIVATE KEY----- in vault"') == []


def test_env_indirection_is_still_exempt():
    assert _secret_violations('private_key = os.environ["PRIVATE_KEY"]') == []
    assert _secret_violations('private_key = "${PRIVATE_KEY}"') == []


# --- the helper ---------------------------------------------------------------------

def test_credential_shaped_value_covers_both_families():
    assert lc._is_credential_shaped_value("sk-live-abcdef") is True
    assert lc._is_credential_shaped_value("-----BEGIN PRIVATE KEY-----") is True
    assert lc._is_credential_shaped_value("just a string") is False


@pytest.mark.parametrize("bad", [None, "", 0, [], {}])
def test_credential_shaped_value_is_fail_soft(bad):
    assert lc._is_credential_shaped_value(bad) is False


def test_every_marker_is_lowercase():
    """The check lowercases the value first, so a mixed-case marker is unreachable."""
    for marker in lc._SECRET_VALUE_MARKERS:
        assert marker == marker.lower(), marker
