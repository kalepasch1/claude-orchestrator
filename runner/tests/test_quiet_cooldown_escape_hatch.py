"""The push guard's load cool-down must be switchable off without a restart.

production_push_guard._wait_for_quiet_machine sleeps in 5-second steps until the
1-minute load average falls below cores x ORCH_QUIET_LOAD_PER_CPU, for up to
ORCH_QUIET_MAX_WAIT_S seconds. Both knobs were read ONCE, at module import, into
QUIET_MAX_WAIT_S / QUIET_LOAD_PER_CPU. The comment above them has always claimed
ORCH_QUIET_MAX_WAIT_S=0 is an off switch "and the tests use it". Neither half was
true on 2026-09-01:

  * no file in this repo besides production_push_guard.py mentioned the variable,
    so no test used it; and
  * setting it after import — which is the only kind of setting a test, or an
    operator editing runner/.env or fleet_config, can do — changed nothing,
    because the value had already been frozen into a module constant.

The visible cost was tests/test_production_push_guard.py::
test_escape_hatch_allow_red_tests, which drives verify_tests through a red suite,
reached the real cool-down, and blocked the whole runner suite at 53% until
pytest-timeout killed it at 25s. The invisible cost is the operator case: a gate
stalling on this at 3am could not be released without restarting the runner.

Three tests, and the third is the one that carries the weight. The behavioural
ones can pass on an idle machine even with the bug back, because the cool-down
returns immediately when the load is already low — which is precisely how this
survived. So the load is forced high with a stub, and there is a structural test
that reads conftest.py and fails if the suite-wide off switch is removed.
"""
import os
import re
import time
from pathlib import Path
from unittest.mock import patch

import pytest

import production_push_guard


CONFTEST = Path(__file__).resolve().parent / "conftest.py"


def _busy(_self=None):
    """A load average far above any plausible cores x 0.5 threshold."""
    return (10_000.0, 10_000.0, 10_000.0)


def test_off_switch_works_when_set_after_import():
    """ORCH_QUIET_MAX_WAIT_S=0 must be honoured at call time, not import time.

    With the bug, max_wait comes from the import-time constant (180 by default),
    the stubbed load never settles, and this call sleeps for three minutes.
    """
    with patch.object(production_push_guard.os, "getloadavg", _busy):
        with patch.dict(os.environ, {"ORCH_QUIET_MAX_WAIT_S": "0"}):
            started = time.monotonic()
            assert production_push_guard._wait_for_quiet_machine() is None
            assert time.monotonic() - started < 2.0, (
                "the off switch was set but the cool-down still waited — "
                "ORCH_QUIET_MAX_WAIT_S is being read at import instead of at call"
            )


def test_a_nonzero_budget_set_after_import_is_also_honoured():
    """The fix is 'read it now', not 'special-case zero'.

    A budget of 1s on a permanently-busy machine must give up after ~1s, not
    after the module-constant 180.
    """
    with patch.object(production_push_guard.os, "getloadavg", _busy):
        with patch.dict(os.environ, {"ORCH_QUIET_MAX_WAIT_S": "1"}):
            started = time.monotonic()
            production_push_guard._wait_for_quiet_machine()
            waited = time.monotonic() - started
    assert waited < 30.0, (
        f"waited {waited:.0f}s against a 1s budget — the env budget was ignored"
    )


@pytest.mark.parametrize("junk", ["", "   ", "not-a-number", "12.5.3"])
def test_unparseable_budgets_fall_back_instead_of_raising(junk):
    """A typo in the env must never be able to break a production push."""
    with patch.dict(os.environ, {"ORCH_QUIET_MAX_WAIT_S": junk}):
        assert production_push_guard._quiet_setting(
            "ORCH_QUIET_MAX_WAIT_S", 180, int
        ) == 180


def test_per_cpu_threshold_is_also_read_at_call_time():
    """The sibling knob had the same defect and must not be left behind."""
    with patch.dict(os.environ, {"ORCH_QUIET_LOAD_PER_CPU": "9999"}):
        assert production_push_guard._quiet_setting(
            "ORCH_QUIET_LOAD_PER_CPU", 0.5, float
        ) == 9999.0


def test_the_suite_turns_the_cooldown_off_for_itself():
    """Structural. This is the assertion that cannot pass by luck.

    The behavioural tests above force the load average high with a stub, so they
    fail correctly with the bug reintroduced. Nothing, however, stops someone
    deleting the conftest fixture — at which point every future test that reaches
    a red suite silently costs 180 seconds again, exactly as before, and no test
    fails. So: read conftest.py and require that it still sets the variable to 0.
    """
    source = CONFTEST.read_text(encoding="utf-8")
    assert "ORCH_QUIET_MAX_WAIT_S" in source, (
        "tests/conftest.py no longer neutralises the push guard's load cool-down. "
        "Any test that drives verify_tests through a red suite will now block for "
        "ORCH_QUIET_MAX_WAIT_S seconds on a machine that is busy running this "
        "suite. Restore _the_quiet_cooldown_is_off_under_pytest."
    )
    assert re.search(
        r"""ORCH_QUIET_MAX_WAIT_S["']\]\s*=\s*["']0["']""", source
    ), "conftest mentions ORCH_QUIET_MAX_WAIT_S but no longer sets it to 0"


def test_the_fixture_is_actually_in_effect_right_now():
    """The fixture is autouse and session-scoped, so it applies to this test too."""
    assert os.environ.get("ORCH_QUIET_MAX_WAIT_S") == "0"
