"""Unit tests for the economic scheduler's revenue prediction.

SCOPE NOTE. The originating request asked for tests of `estimate_task_revenue` asserting
that a task with `priority: 5` scores 50 and `priority: 10` scores 100. No such function
exists in this repository, and the real owner — `economic_scheduler.predict_revenue` —
does not read `priority` at all: the estimate comes from the historical per-KIND return,
scaled by growth/keyword/error-rate/pricing-tier multipliers. Asserting 5 -> 50 would have
required inventing that behaviour, so these tests pin what the function actually
guarantees. Test-only; no existing file is modified.
"""
import os
import sys

import pytest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import economic_scheduler as es  # noqa: E402


def ctx(**over):
    base = {"kind_roi": {"build": 50.0, "bugfix": 20.0},
            "high_growth_projects": set(),
            "error_rates": {}}
    base.update(over)
    return base


# --- the base case: historical return for the kind --------------------------------------

def test_normal_task_scores_its_kinds_historical_return():
    out = es.predict_revenue({"kind": "build", "project": "p"}, ctx())
    assert out.point_estimate == 50.0


def test_a_higher_earning_kind_scores_higher():
    high = es.predict_revenue({"kind": "build", "project": "p"}, ctx())
    low = es.predict_revenue({"kind": "bugfix", "project": "p"}, ctx())
    assert high.point_estimate > low.point_estimate


def test_unknown_kind_scores_zero_not_a_guess():
    out = es.predict_revenue({"kind": "mystery", "project": "p"}, ctx())
    assert out.point_estimate == 0.0


# --- multipliers ------------------------------------------------------------------------

def test_high_growth_project_doubles_the_estimate():
    out = es.predict_revenue({"kind": "build", "project": "p"},
                             ctx(high_growth_projects={"p"}))
    assert out.point_estimate == 100.0


def test_revenue_keyword_in_the_prompt_boosts_by_half():
    out = es.predict_revenue(
        {"kind": "build", "project": "p", "prompt": "rework the pricing page"}, ctx())
    assert out.point_estimate == 75.0


def test_error_rate_spike_boosts_bugfix_work_only():
    spiking = ctx(error_rates={"p": 0.9})
    fix = es.predict_revenue({"kind": "bugfix", "project": "p"}, spiking)
    build = es.predict_revenue({"kind": "build", "project": "p"}, spiking)
    assert fix.point_estimate == 30.0          # 20 * 1.5
    assert build.point_estimate == 50.0        # unboosted


def test_multipliers_compound():
    out = es.predict_revenue(
        {"kind": "build", "project": "p", "prompt": "billing revamp"},
        ctx(high_growth_projects={"p"}))
    assert out.point_estimate == 150.0         # 50 * 2 * 1.5


# --- confidence interval ------------------------------------------------------------------

def test_confidence_band_brackets_the_estimate():
    out = es.predict_revenue({"kind": "build", "project": "p"}, ctx())
    assert out.confidence_low < out.point_estimate < out.confidence_high


def test_no_signal_gives_a_zero_floor_not_a_negative_low():
    out = es.predict_revenue({"kind": "mystery", "project": "p"}, ctx())
    assert out.confidence_low == 0.0
    assert out.confidence_high >= 0.0


# --- fail-soft contract -------------------------------------------------------------------

@pytest.mark.parametrize("task", [None, "not-a-task", 42, []])
def test_a_non_dict_task_scores_zero_instead_of_raising(task):
    assert es.predict_revenue(task, ctx()).point_estimate == 0.0


def test_empty_context_scores_zero_instead_of_raising():
    assert es.predict_revenue({"kind": "build", "project": "p"}, {}).point_estimate == 0.0


@pytest.mark.parametrize("bad", ["oops", None, True, float("nan"), float("inf")])
def test_unusable_historical_value_degrades_to_zero(bad):
    out = es.predict_revenue({"kind": "build", "project": "p"}, ctx(kind_roi={"build": bad}))
    assert out.point_estimate == 0.0


def test_nested_telemetry_error_rate_is_read_not_just_survived():
    out = es.predict_revenue({"kind": "bugfix", "project": "p"},
                             ctx(error_rates={"p": {"error_rate": 0.9}}))
    assert out.point_estimate == 30.0


def test_negative_history_never_produces_a_negative_estimate():
    out = es.predict_revenue({"kind": "build", "project": "p"}, ctx(kind_roi={"build": -100.0}))
    assert out.point_estimate == 0.0


# --- result shape --------------------------------------------------------------------------

def test_result_supports_both_attribute_and_index_access():
    out = es.predict_revenue({"kind": "build", "project": "p"}, ctx())
    assert out.point_estimate == out[0]
    assert out.confidence_low == out[1]
    assert out.confidence_high == out[2]
