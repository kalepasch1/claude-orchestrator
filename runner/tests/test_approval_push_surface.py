#!/usr/bin/env python3
"""approval_push must survive a bad rebase, and say so loudly if it does not.

WHY
---
Three existing files (test_approval_push_batcher.py and the two digest-batching ones)
exercise the batcher and the digest. None asserts the module's SURFACE, and none covers
the security-relevant helpers — which is the shape of damage a bad rebase does: it does
not usually corrupt behaviour subtly, it drops a function or a regex and leaves valid
Python behind. The approval-digest-batching wave has repeatedly been queued against a
supposed conflict in this file, so a standing guard is worth more than another
one-off inspection.

Everything here is deterministic: no network, no filesystem, no database, no clock
dependence beyond a bounded TTL arithmetic check.

Two of these cover things that leak credentials if they break:

  * `scrub()` redacts sig/signature/token/key/apikey query parameters before anything is
    printed or handed to a notifier. If its regex is broken by a rebase, signed
    one-click approval links go out in plaintext.
  * `_signing_key()` must refuse a too-short key rather than sign with it. An empty-key
    HMAC is publicly computable, so a forgeable approval link is worse than no link.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import approval_push  # noqa: E402

# The surface other modules and the digest path depend on. A rebase that drops any of
# these leaves importable, valid Python — and a silently broken approval pipeline.
PUBLIC_CALLABLES = (
    "append_to_batch",
    "get_pending_approvals",
    "flush_approvals",
    "approval_batcher_stats",
    "scrub",
    "cockpit_url",
    "build_digest",
    "run",
)


# ── the module is intact ────────────────────────────────────────────────────

def test_the_module_imports():
    assert approval_push is not None


@pytest.mark.parametrize("name", PUBLIC_CALLABLES)
def test_public_callable_exists(name):
    assert callable(getattr(approval_push, name, None)), \
        f"approval_push.{name} is missing — a rebase may have dropped it"


def test_the_batcher_class_exists():
    assert isinstance(getattr(approval_push, "ApprovalBatcher", None), type)


def test_the_signing_failure_type_exists():
    """Callers catch this by name; losing it turns a refusal into an uncaught error."""
    exc = getattr(approval_push, "SigningKeyUnavailable", None)
    assert isinstance(exc, type) and issubclass(exc, Exception)


def test_the_source_has_no_conflict_markers():
    path = approval_push.__file__
    with open(path, encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
    hits = [i for i, line in enumerate(lines, 1)
            if line.startswith(("<<<<<<< ", ">>>>>>> "))]
    assert not hits, f"{path} contains conflict markers at lines {hits}"


# ── scrub: redaction must not silently stop working ─────────────────────────

@pytest.mark.parametrize("param", ["sig", "signature", "token", "key", "apikey"])
def test_scrub_redacts_every_credential_parameter(param):
    scrubbed = approval_push.scrub(f"https://x/api?id=1&{param}=SUPERSECRETVALUE")
    assert "SUPERSECRETVALUE" not in scrubbed
    assert "[REDACTED]" in scrubbed


def test_scrub_is_case_insensitive():
    assert "ABC123" not in approval_push.scrub("https://x/api?SIG=ABC123")


def test_scrub_redacts_a_leading_query_parameter():
    assert "ABC123" not in approval_push.scrub("https://x/api?sig=ABC123")


def test_scrub_keeps_the_rest_of_the_url_readable():
    """A redactor that eats the whole line makes logs useless and gets removed."""
    scrubbed = approval_push.scrub("https://x/functions/v1/approvals-api?id=42&sig=AAA")
    assert "id=42" in scrubbed and "approvals-api" in scrubbed


def test_scrub_leaves_innocent_text_alone():
    assert approval_push.scrub("nothing secret here") == "nothing secret here"


@pytest.mark.parametrize("value", [None, "", 0, False])
def test_scrub_is_fail_soft_on_falsey_input(value):
    """`str(text or "")` collapses every falsey value to "".

    Pinned rather than argued with: scrub's job is redacting URLs out of notification
    text, and no caller passes it a 0. Recorded so the behaviour is a decision rather
    than a surprise if someone later feeds it something numeric.
    """
    assert approval_push.scrub(value) == ""


def test_scrub_stringifies_non_string_input():
    assert approval_push.scrub(42) == "42"


# ── the signing key must be refused, not weakened ───────────────────────────

def test_a_missing_signing_key_is_refused(monkeypatch):
    """An empty-key HMAC is publicly computable — a forgeable link is worse than none."""
    for name in ("APPROVAL_SIGNING_KEY", "AGENT_SIGNING_SECRET", "SUPABASE_SERVICE_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(approval_push.SigningKeyUnavailable):
        approval_push._signing_key()


def test_a_too_short_signing_key_is_refused(monkeypatch):
    monkeypatch.setenv("APPROVAL_SIGNING_KEY", "short")
    with pytest.raises(approval_push.SigningKeyUnavailable):
        approval_push._signing_key()


def test_the_minimum_key_length_is_not_trivial():
    assert approval_push._MIN_KEY_LEN >= 32


# ── TTL bounds ──────────────────────────────────────────────────────────────

def test_the_default_ttl_is_within_bounds():
    assert approval_push._TTL_MIN_S <= approval_push.LINK_TTL_S <= approval_push._TTL_MAX_S


def test_an_absurdly_long_ttl_is_clamped(monkeypatch):
    """A link that never expires is a standing credential."""
    monkeypatch.setenv("APPROVAL_LINK_TTL_S", str(10 ** 9))
    assert approval_push._ttl_seconds() == approval_push._TTL_MAX_S


def test_an_absurdly_short_ttl_is_floored(monkeypatch):
    monkeypatch.setenv("APPROVAL_LINK_TTL_S", "1")
    assert approval_push._ttl_seconds() == approval_push._TTL_MIN_S


def test_a_garbage_ttl_falls_back_to_the_maximum(monkeypatch):
    monkeypatch.setenv("APPROVAL_LINK_TTL_S", "not-a-number")
    assert approval_push._ttl_seconds() == approval_push._TTL_MAX_S


# ── cockpit_url never returns nothing ───────────────────────────────────────

def test_cockpit_url_always_returns_something_printable(monkeypatch):
    """It is used as the fallback when a link cannot be signed."""
    monkeypatch.delenv("APPROVAL_COCKPIT_URL", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    assert approval_push.cockpit_url()


def test_cockpit_url_prefers_the_explicit_setting(monkeypatch):
    monkeypatch.setenv("APPROVAL_COCKPIT_URL", "https://cockpit.example")
    assert approval_push.cockpit_url() == "https://cockpit.example"


# ── build_digest is deterministic and does not explode on bad input ─────────

def test_build_digest_handles_no_cards():
    result = approval_push.build_digest([])
    assert result is None or isinstance(result, (str, dict, tuple))


def test_build_digest_is_deterministic_for_the_same_cards():
    cards = [{"id": "a1", "title": "one", "kind": "verify"},
             {"id": "a2", "title": "two", "kind": "material"}]
    assert approval_push.build_digest(list(cards)) == approval_push.build_digest(list(cards))


def test_build_digest_does_not_raise_on_sparse_cards():
    """Cards come from the DB; a missing optional column must not take the digest down."""
    assert approval_push.build_digest([{"id": "a1"}]) is not None or True
