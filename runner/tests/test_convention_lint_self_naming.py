#!/usr/bin/env python3
"""A constant assigned its own name is a name, not a credential.

THE FALSE POSITIVE
------------------
    runner/tools/lint_conventions.py:46: HARDCODED_SECRET:
      Variable "RULE_HARDCODED_SECRET" is assigned a literal that looks like a
      credential; read it from the environment instead

The linter reported a lint rule's own name constant as a hardcoded secret. That is the
most corrosive kind of false positive: it lands on the one rule whose entire value is
that people trust it, and the only available response is to suppress it — which is how
a security rule stops being read.

The exemption is deliberately narrow: the literal must BE the variable's name, or its
tail. A real credential does not happen to equal its own variable name, so this cannot
launder one — and the tests below assert exactly that, because an over-broad fix here
would be far worse than the false positive it removes.
"""
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tools"))

import convention_lint as cl  # noqa: E402


# ── the predicate ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,value", [
    ("RULE_HARDCODED_SECRET", "HARDCODED_SECRET"),
    ("SECRET", "SECRET"),
    ("_TOKEN_KIND", "TOKEN_KIND"),
    ("RULE_NO_HARDCODED_SECRETS", "NO_HARDCODED_SECRETS"),
    ("AUTH_TOKEN", "AUTH_TOKEN"),
    ("rule_hardcoded_secret", "hardcoded_secret"),
    ("RULE_HARDCODED_SECRET", "hardcoded-secret"),
])
def test_self_naming_constants_are_recognised(name, value):
    assert cl._is_self_naming_constant(name, value) is True


@pytest.mark.parametrize("name,value", [
    ("API_TOKEN", "ghp_16CharsOfRealLookingCredential"),
    ("PASSWORD", "hunter2hunter2"),
    ("AUTH_TOKEN", "Bearer abcdef123456"),
    ("SECRET", "s3cr3t-value-here"),
    ("RULE_HARDCODED_SECRET", "HARDCODED_SECRET_BUT_LONGER_AND_DIFFERENT"),
    ("TOKEN", "TOKENS"),
])
def test_a_real_looking_credential_is_never_exempted(name, value):
    """The property that matters: the exemption must not launder a secret."""
    assert cl._is_self_naming_constant(name, value) is False


@pytest.mark.parametrize("name,value", [
    ("", "SECRET"), ("SECRET", ""), (None, "SECRET"), ("SECRET", None),
])
def test_the_predicate_is_fail_soft_on_empty_input(name, value):
    assert cl._is_self_naming_constant(name, value) is False


def test_a_prefix_match_is_not_enough():
    """Only the TAIL of the name counts, so a value cannot match by coincidence."""
    assert cl._is_self_naming_constant("SECRET_MATERIAL", "SECRET") is False


# ── end to end through the linter ───────────────────────────────────────────

def _lint(tmp_path, source):
    target = tmp_path / "sample.py"
    target.write_text(source)
    proc = subprocess.run(
        [sys.executable, os.path.join(REPO, "tools", "convention_lint.py"), str(target)],
        capture_output=True, text=True, timeout=120)
    return (proc.stdout or "") + (proc.stderr or "")


def test_a_rule_name_constant_is_not_reported(tmp_path):
    out = _lint(tmp_path, 'RULE_HARDCODED_SECRET = "HARDCODED_SECRET"\n')
    assert "HARDCODED_SECRET:" not in out


def test_an_actual_hardcoded_credential_is_still_reported(tmp_path):
    """The rule must keep working. This is the whole point of keeping it narrow."""
    out = _lint(tmp_path, 'API_TOKEN = "ghp_R3alL00kingT0kenValue123"\n')
    assert "HARDCODED_SECRET" in out


def test_the_repo_no_longer_reports_a_hardcoded_secret():
    """The finding this task was opened against."""
    proc = subprocess.run(
        [sys.executable, os.path.join(REPO, "tools", "convention_lint.py")],
        cwd=REPO, capture_output=True, text=True, timeout=900)
    output = (proc.stdout or "") + (proc.stderr or "")
    offenders = [ln for ln in output.splitlines() if "HARDCODED_SECRET:" in ln]
    assert offenders == [], "\n".join(offenders)
