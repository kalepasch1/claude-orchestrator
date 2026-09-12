"""The governor could not see the resource that was actually exhausted.

On 2026-09-01 this Mac ran at load average 82-92 across 18 cores — five times
oversubscribed — while resource_governor held the throttle at the top of its
lane band and reported healthy. It was right about everything it measured: RAM
free, disk fine. There was no CPU signal anywhere in the file.

These tests exist so that stays fixed, and they are written to FAIL if the brake
is removed rather than to describe it. Deleting cpu_budget's clamp, raising the
thresholds past use, or routing a branch around the clamp all turn at least one
of these red.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import resource_governor as rg  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("CPU_SOFT_LOAD", "CPU_HARD_LOAD", "ORCH_DISABLE_CPU_GATE"):
        monkeypatch.delenv(k, raising=False)


def test_idle_machine_is_not_braked():
    # The brake must not cost throughput on a machine that is fine. A governor
    # that throttles a healthy fleet gets disabled, and then protects nothing.
    assert rg.cpu_budget(8, per_core=0.2) == 8
    assert rg.cpu_budget(8, per_core=1.5) == 8


def test_thrashing_machine_is_clamped_to_one_lane():
    # 92 load over 18 cores is 5.1 — the number this was built for.
    assert rg.cpu_budget(8, per_core=5.1) == 1
    assert rg.cpu_budget(24, per_core=3.0) == 1


def test_between_soft_and_hard_it_scales_rather_than_cliffs():
    # Proportional, so a loaded machine sheds load smoothly instead of dropping
    # to one lane and starving — which is what makes the brake survivable in
    # normal use rather than something someone switches off.
    midpoint = rg.cpu_budget(8, per_core=2.25)
    assert 1 < midpoint < 8
    # Monotonic: more load never returns MORE lanes.
    lanes = [rg.cpu_budget(8, per_core=x) for x in (1.5, 1.9, 2.3, 2.7, 3.0)]
    assert lanes == sorted(lanes, reverse=True), lanes


def test_an_unreadable_probe_does_not_brake():
    # None means "no signal". A probe that cannot read the machine must not be
    # able to throttle the fleet to a stop — the failure mode has to be
    # "governor does nothing", never "fleet stops".
    assert rg.cpu_budget(8, per_core=None) == 8


def test_thresholds_are_live_from_env(monkeypatch):
    # fleet_control pushes tuning into os.environ every loop. Constants
    # snapshotted at import are why a Mac stayed clamped at 4 lanes against a
    # 16-lane ceiling; see the module header. Read live or repeat that bug.
    monkeypatch.setenv("CPU_SOFT_LOAD", "0.5")
    monkeypatch.setenv("CPU_HARD_LOAD", "1.0")
    assert rg._cpu_soft() == 0.5
    assert rg._cpu_hard() == 1.0
    assert rg.cpu_budget(8, per_core=1.2) == 1


def test_inverted_thresholds_do_not_divide_by_zero(monkeypatch):
    # A bad central push must degrade, not crash the governor loop.
    monkeypatch.setenv("CPU_SOFT_LOAD", "3.0")
    monkeypatch.setenv("CPU_HARD_LOAD", "1.0")
    assert rg.cpu_budget(8, per_core=2.0) >= 1
    assert rg.cpu_budget(8, per_core=9.0) == 1


def test_load_per_core_is_a_ratio_not_a_raw_load():
    # The distinction the original file was missing. Raw load says nothing
    # without the core count: 16 is idle on 64 cores and fatal on 4.
    per_core = rg.load_per_core()
    assert per_core is None or 0 <= per_core < 200


def test_the_clamp_is_reachable_from_govern():
    # The clamp has to sit after every branch that sets a throttle, or a
    # healthy-path decision routes around it — which is exactly how the fleet
    # held its band maximum at load 92. Asserted against the source because the
    # behavioural version needs a genuinely overloaded machine to fail on.
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "resource_governor.py"), encoding="utf-8").read()
    body = src[src.index("def govern("):]
    clamp = body.index("cpu_budget(current_limit()")
    for branch in ("set_throttle(_target)", "action = \"ease up\"", "mem-clamp"):
        assert body.index(branch) < clamp, f"{branch} must be decided before the CPU clamp"


def test_the_gauge_reports_the_signal_it_brakes_on():
    # A brake nobody can see is one that gets blamed for something else.
    gauge = rg.dashboard_gauge()
    for key in ("load_per_core", "cpu_soft", "cpu_hard"):
        assert key in gauge, key
