"""The orch config-consumption layer is actually consumed by production code.

`runner/config_consumer.py` implements the ORCH_* read — prefix, whitespace stripping,
empty-as-absent, fail-soft, plus a TTL cache whose TTL is itself fleet-pushable. It
shipped with five test files and ZERO production callers: grepping the repo for the
module outside its own tests returned nothing. A config layer nobody consumes cannot
deliver a config change, however well tested it is in isolation.

`fleet_control.get_fleet_config` now delegates to it. These tests prove the delegation
(the layer is really on the path), and prove the read behaviour is unchanged — the whole
point of routing through a shared implementation is that callers cannot tell, except that
a fleet-pushed value now arrives through one code path instead of two.
"""
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(REPO, "runner")
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import config_consumer  # noqa: E402
import fleet_control as fc  # noqa: E402

KEY = "TEST_ORCH_CONSUMED_KNOB"
ENV = f"ORCH_{KEY}"


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    config_consumer.invalidate_cache()
    yield
    config_consumer.invalidate_cache()


# --- the layer is on the path -------------------------------------------------------

def test_get_fleet_config_delegates_to_the_config_consumer(monkeypatch):
    """The regression this exists to prevent: the layer quietly losing its only caller."""
    seen = {}

    def spy(key, default=""):
        seen["key"] = key
        return "from-the-layer"

    monkeypatch.setattr(config_consumer, "get", spy)
    assert fc.get_fleet_config(KEY, "fallback") == "from-the-layer"
    assert seen["key"] == KEY


def test_it_falls_back_when_the_layer_is_unavailable(monkeypatch):
    """Fail-soft: a broken import must not break config reads."""
    def boom(*a, **k):
        raise RuntimeError("layer unavailable")

    monkeypatch.setattr(config_consumer, "get", boom)
    monkeypatch.setenv(ENV, "direct-value")
    assert fc.get_fleet_config(KEY, "fallback") == "direct-value"


# --- behaviour is unchanged ---------------------------------------------------------

def test_reads_the_orch_prefixed_variable():
    os.environ[ENV] = "live"
    try:
        assert fc.get_fleet_config(KEY, "fallback") == "live"
    finally:
        os.environ.pop(ENV, None)


def test_missing_key_returns_the_default():
    assert fc.get_fleet_config(KEY, "fallback") == "fallback"


def test_whitespace_only_value_is_treated_as_absent():
    os.environ[ENV] = "   "
    try:
        config_consumer.invalidate_cache()
        assert fc.get_fleet_config(KEY, "fallback") == "fallback"
    finally:
        os.environ.pop(ENV, None)


def test_value_is_stripped():
    os.environ[ENV] = "  padded  "
    try:
        config_consumer.invalidate_cache()
        assert fc.get_fleet_config(KEY, "fallback") == "padded"
    finally:
        os.environ.pop(ENV, None)


def test_the_key_is_case_normalised():
    os.environ[ENV] = "upper"
    try:
        config_consumer.invalidate_cache()
        assert fc.get_fleet_config(KEY.lower(), "fallback") == "upper"
    finally:
        os.environ.pop(ENV, None)


@pytest.mark.parametrize("bad", [None, "", 0, [], {}])
def test_an_invalid_key_returns_the_default_instead_of_raising(bad):
    assert fc.get_fleet_config(bad, "fallback") == "fallback"


def test_both_paths_agree_on_every_shape():
    """Delegation must be indistinguishable from the previous direct read."""
    for raw, expected in (("live", "live"), ("  padded  ", "padded"),
                          ("   ", "fallback"), (None, "fallback")):
        if raw is None:
            os.environ.pop(ENV, None)
        else:
            os.environ[ENV] = raw
        config_consumer.invalidate_cache()
        try:
            assert fc.get_fleet_config(KEY, "fallback") == expected, raw
            assert config_consumer.get(KEY, "fallback") == expected, raw
        finally:
            os.environ.pop(ENV, None)
