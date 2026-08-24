#!/usr/bin/env python3
"""Does an identifier NAME a credential, or merely mention one?

tools/lint_conventions.py asked that question with
``any(k in var_name.lower() for k in ('password','token','secret','key','api_key'))``.
The bare token ``key`` matches every KV-namespace constant in the runner — ``_ALERT_KEY``,
``PRESSURE_KEY``, ``STATE_KEY``, ``DONE_KEY``, ``problem_key`` — so HARDCODED_SECRET
reported 144 findings of which essentially none were credentials. A rule whose output is
all noise is a rule people learn to ignore, and it sat above its ratchet baseline of 133,
keeping the whole pre-commit gate red for every other rule too.

runner/tools/lint_conventions.py already worked this out and carries a precise token list.
This module is that logic in one importable place so the two linters cannot drift, and so
the fix for a noisy name test is a precise name test rather than disabling the rule.

Fail-soft by contract: never raises, whatever it is handed.
"""

#: Tokens that actually denote a credential. Note the absence of a bare "key" and "pat".
SECRET_NAME_TOKENS = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "api_key",
    "apikey",
    "private_key",
    "privatekey",
    "secret_key",
    "access_key",
    "signing_key",
    "encryption_key",
    "client_secret",
)

#: Names that contain a secret token but denote configuration, not a credential:
#: ``TOKEN_ENV``, ``SECRET_PATH``, ``API_KEY_NAME`` hold where to look, not the value.
SECRET_NAME_EXEMPT_SUFFIXES = (
    "_env", "_var", "_name", "_key_name", "_path", "_file", "_url", "_prefix",
)

#: Reason-code / sentinel constants — e.g. fleet_control's
#: ``IGNORE_UNSAFE_KEY = "..."``, where the word is the thing being classified.
SECRET_NAME_EXEMPT_PREFIXES = ("ignore_", "_ignore_", "reason_", "_reason_")


def names_a_secret(name) -> bool:
    """True when an identifier names a credential rather than merely mentioning one.

    >>> names_a_secret("db_password"), names_a_secret("PRESSURE_KEY")
    (True, False)
    """
    try:
        lowered = str(name or "").lower()
        if not lowered:
            return False
        if lowered.startswith(SECRET_NAME_EXEMPT_PREFIXES):
            return False
        if lowered.endswith(SECRET_NAME_EXEMPT_SUFFIXES):
            return False
        return any(token in lowered for token in SECRET_NAME_TOKENS)
    except Exception:
        return False
