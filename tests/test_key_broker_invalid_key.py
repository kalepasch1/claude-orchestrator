"""An invalid provider key must surface as a broker error, not an upstream crash.

`key_broker.call` invoked `mg.complete()` unguarded. A rejected key raises out of the
provider SDK, so it propagated to whatever caller happened to be on the stack — while
every caller of this module already handles a result dict carrying an `error` string. A
bad key therefore appeared as an unrelated crash somewhere upstream, and never reached
app_triage, so the one place that would have shown a provider failing every call recorded
nothing.

These also pin the two things that make the classification useful: an auth failure is
distinguished from a transient one (opposite retry handling), and the rejected key is
never echoed into the error text.
"""
import os
import sys

import pytest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import key_broker as kb  # noqa: E402

LIVE_KEY = "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789"


@pytest.fixture(autouse=True)
def no_side_effects(monkeypatch):
    monkeypatch.setattr(kb, "_today_spend", lambda: 0.0)
    monkeypatch.setattr(kb, "_record", lambda usd: None)


# --- classification -------------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "Incorrect API key provided",
    "invalid_api_key",
    "AuthenticationError: invalid x-api-key",
    "401 Unauthorized",
    "403 Forbidden",
    "API key not valid. Please pass a valid API key.",
    "permission_denied",
])
def test_provider_key_rejections_are_auth_errors(message):
    assert kb.is_auth_error(message) is True


@pytest.mark.parametrize("message", [
    "Connection reset by peer",
    "429 rate limit exceeded",
    "500 internal server error",
    "read timed out",
])
def test_transient_failures_are_not_auth_errors(message):
    """Mislabelling a transient fault unretryable is the costlier mistake."""
    assert kb.is_auth_error(message) is False


def test_unknown_and_empty_are_not_auth_errors():
    assert kb.is_auth_error(None) is False
    assert kb.is_auth_error("") is False
    assert kb.is_auth_error("something we have never seen") is False


# --- redaction ------------------------------------------------------------------------

def test_a_rejected_key_is_redacted_from_the_message():
    out = kb.redact_secrets(f"Incorrect API key provided: {LIVE_KEY}")
    assert LIVE_KEY not in out
    assert "<redacted>" in out


@pytest.mark.parametrize("secret", [
    "sk-abcdefghijklmnop", "xai-abcdefghijklmnop", "gsk_abcdefghijklmnop",
    "AIzaSyABCDEFGHIJKLMNOP", "ghp_abcdefghijklmnop",
])
def test_credential_shapes_are_masked(secret):
    assert secret not in kb.redact_secrets(f"rejected {secret} end")


def test_ordinary_text_survives_redaction():
    assert kb.redact_secrets("model gpt-4 timed out") == "model gpt-4 timed out"


def test_redaction_is_fail_soft():
    assert kb.redact_secrets(None) == ""
    assert kb.redact_secrets(12345) == "12345"


# --- describe -------------------------------------------------------------------------

def test_auth_error_description_points_at_the_credential():
    msg = kb.describe_provider_error("openai", ValueError("Incorrect API key provided"))
    assert "rejected the API key" in msg
    assert "openai" in msg


def test_non_auth_error_description_does_not_blame_the_key():
    msg = kb.describe_provider_error("openai", TimeoutError("read timed out"))
    assert "rejected the API key" not in msg
    assert "TimeoutError" in msg


# --- call() ---------------------------------------------------------------------------

def test_invalid_key_returns_a_result_dict_instead_of_raising(monkeypatch):
    def reject(*a, **k):
        raise ValueError(f"Incorrect API key provided: {LIVE_KEY}")
    monkeypatch.setattr(kb.mg, "complete", reject)

    res = kb.call("openai", "gpt-4", "hello")

    assert isinstance(res, dict)
    assert res["text"] == "" and res["cost_usd"] == 0
    assert res["auth_error"] is True
    assert "rejected the API key" in res["error"]
    assert LIVE_KEY not in res["error"], "the rejected key must not be echoed back"


def test_transient_provider_exception_is_reported_but_not_as_auth(monkeypatch):
    monkeypatch.setattr(kb.mg, "complete",
                        lambda *a, **k: (_ for _ in ()).throw(TimeoutError("read timed out")))
    res = kb.call("openai", "gpt-4", "hello")
    assert res["auth_error"] is False
    assert res["error"]


def test_in_band_auth_error_is_classified_the_same_way(monkeypatch):
    """A provider that returns (rather than raises) an auth error gets the same flag."""
    monkeypatch.setattr(kb.mg, "complete",
                        lambda *a, **k: {"text": "", "cost_usd": 0,
                                         "error": "401 Unauthorized"})
    assert kb.call("openai", "gpt-4", "hello")["auth_error"] is True


def test_a_successful_call_is_untouched(monkeypatch):
    monkeypatch.setattr(kb.mg, "complete",
                        lambda *a, **k: {"text": "hi", "cost_usd": 0.001})
    res = kb.call("openai", "gpt-4", "hello")
    assert res["text"] == "hi"
    assert res.get("error") is None
    assert "auth_error" not in res


def test_a_non_dict_provider_response_becomes_a_reported_error(monkeypatch):
    monkeypatch.setattr(kb.mg, "complete", lambda *a, **k: "surprise string")
    res = kb.call("openai", "gpt-4", "hello")
    assert res["error"] and "expected a result dict" in res["error"]


def test_a_failed_call_is_still_recorded_for_triage(monkeypatch):
    """The failure has to reach app_triage — that is where a dead provider shows up."""
    seen = []
    monkeypatch.setattr(kb.mg, "complete",
                        lambda *a, **k: (_ for _ in ()).throw(ValueError("401 Unauthorized")))
    fake = type(sys)("app_triage")
    fake.record = lambda *a, **k: seen.append(k.get("ok"))
    monkeypatch.setitem(sys.modules, "app_triage", fake)

    kb.call("openai", "gpt-4", "hello")
    assert seen == [False]
