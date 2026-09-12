"""The knobs that stop a job being shelved by the queue-velocity PID must be live.

`ev_scheduler` declared LOW_EV_THRESHOLD / LOW_EV_EARLY_EXIT / EV_FIELDS and the exempt
lanes TWICE, under two different env spellings (`ORCH_LOW_EV_*` and `ORCH_EV_LOW_*`).
Python kept the later binding, so:

  * raising `ORCH_LOW_EV_THRESHOLD` — the documented mitigation for
    "shelved by queue-velocity PID (low EV, integral too high)" — did nothing, and
  * `_ev_exempt()` and the second exemption check read different tuples, so a
    qafix/relfix/buildfix task was exempt on one path and shelved on the other.

These tests pin one source of truth for both.
"""
import importlib
import os
import sys

import pytest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import ev_scheduler  # noqa: E402


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("ORCH_LOW_EV_THRESHOLD", "ORCH_EV_LOW_THRESHOLD",
                 "ORCH_LOW_EV_EARLY_EXIT", "ORCH_EV_LOW_EARLY_EXIT"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("var", ["ORCH_LOW_EV_THRESHOLD", "ORCH_EV_LOW_THRESHOLD"])
def test_either_threshold_spelling_is_honoured(monkeypatch, var):
    monkeypatch.setenv(var, "-2.5")
    assert ev_scheduler.low_ev_threshold() == -2.5
    mod = importlib.reload(ev_scheduler)
    try:
        assert mod.LOW_EV_THRESHOLD == -2.5
    finally:
        monkeypatch.delenv(var, raising=False)
        importlib.reload(ev_scheduler)


@pytest.mark.parametrize("var", ["ORCH_LOW_EV_EARLY_EXIT", "ORCH_EV_LOW_EARLY_EXIT"])
def test_either_early_exit_spelling_disarms_refusal(monkeypatch, var):
    monkeypatch.setenv(var, "false")
    assert ev_scheduler.low_ev_early_exit() is False
    monkeypatch.setenv(var, "ON")
    assert ev_scheduler.low_ev_early_exit() is True


def test_threshold_is_fail_soft_on_garbage(monkeypatch):
    monkeypatch.setenv("ORCH_LOW_EV_THRESHOLD", "not-a-number")
    assert ev_scheduler.low_ev_threshold() == 0.0
    monkeypatch.setenv("ORCH_LOW_EV_THRESHOLD", "nan")
    assert ev_scheduler.low_ev_threshold() == 0.0
    monkeypatch.setenv("ORCH_LOW_EV_THRESHOLD", "inf")
    assert ev_scheduler.low_ev_threshold() == 0.0


def test_default_threshold_unchanged():
    assert ev_scheduler.low_ev_threshold() == 0.0
    assert ev_scheduler.low_ev_early_exit() is True


def test_exempt_lists_are_one_definition():
    assert ev_scheduler.EV_EXEMPT_KINDS is ev_scheduler.EXEMPT_KINDS
    assert ev_scheduler.EV_EXEMPT_PREFIXES is ev_scheduler.EXEMPT_SLUG_PREFIXES


@pytest.mark.parametrize("kind", ["qafix", "relfix", "buildfix", "deployfix",
                                  "remediation", "recovery", "canary",
                                  "toolchain-repair", "rework"])
def test_repair_lanes_are_exempt_on_the_shared_path(kind):
    assert ev_scheduler._ev_exempt({"kind": kind, "slug": "x"}) is True


@pytest.mark.parametrize("slug", ["qafix-kalepasch-com", "relfix-beethoven-1",
                                  "buildfix-abc", "recover-build-x",
                                  "breach-remediation-1", "toolchain-repair-x"])
def test_repair_slugs_are_exempt_on_the_shared_path(slug):
    assert ev_scheduler._ev_exempt({"kind": "build", "slug": slug}) is True


def test_ordinary_build_is_not_exempt():
    assert ev_scheduler._ev_exempt({"kind": "build", "slug": "add-a-feature"}) is False
