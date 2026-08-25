"""Tests for scoreboard_metrics.py — pure logic, no db.

Six of these were asserting an older shape of the module and had been failing:
`m["deploy_rate"]` (a scalar) against the module's `deploy_success_rate` dict,
`m["knowledge_reuse"]` against `knowledge_reuse_rate`, and
`m["lead_times"]["median_hours"]` against a lead-times structure that grew two
legs (objective->prompt, prompt->merged) each with median, p90 and a count, in
MINUTES. The module docstring names the newer shape and the expansion is
deliberate, so the assertions are moved onto it rather than the module moved
back.

Rewriting them surfaced the defect in the third block below: the deploy success
rate could not be anything but 1.0.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scoreboard_metrics import compute_metrics  # noqa: E402

_ROWS = [
    {"model": "claude", "project": "alpha", "tests_passed": True,
     "integrated": True, "usd": 0.10, "input_tokens": 100,
     "output_tokens": 50, "wall_ms": 60000, "review_failures": 0},
    {"model": "claude", "project": "alpha", "tests_passed": True,
     "integrated": False, "usd": 0.05, "input_tokens": 80,
     "output_tokens": 40, "wall_ms": 45000, "review_failures": 1},
    {"model": "gemini", "project": "beta", "tests_passed": False,
     "integrated": False, "usd": 0.02, "input_tokens": 50,
     "output_tokens": 20, "wall_ms": 30000, "review_failures": 0},
]


# ── overall ──────────────────────────────────────────────────────────────────

def test_overall_attempts():
    assert compute_metrics(_ROWS)["overall"]["attempts"] == 3


def test_overall_tests_passed():
    assert compute_metrics(_ROWS)["overall"]["tests_passed"] == 2


def test_overall_merged():
    assert compute_metrics(_ROWS)["overall"]["merged"] == 1


def test_rates_are_none_not_zero_when_there_were_no_attempts():
    """Nothing attempted and nothing passed are different facts."""
    o = compute_metrics([])["overall"]
    assert o["attempts"] == 0
    assert o["first_pass_rate"] is None
    assert o["merge_rate"] is None


def test_per_merge_costs_are_none_when_nothing_merged():
    """Dividing by zero merges would be a crash; reporting 0 would be a lie."""
    o = compute_metrics(_ROWS[1:])["overall"]
    assert o["merged"] == 0
    assert o["usd_per_merge"] is None
    assert o["tokens_per_merge"] is None
    assert o["review_failures_per_merge"] is None


def test_costs_are_summed_across_rows():
    o = compute_metrics(_ROWS)["overall"]
    assert round(o["usd"], 4) == 0.17
    assert o["tokens"] == 340
    assert o["review_failures"] == 1


# ── grouping ─────────────────────────────────────────────────────────────────

def test_by_model_keys():
    m = compute_metrics(_ROWS)
    assert "claude" in m["by_model"]
    assert "gemini" in m["by_model"]


def test_by_project_keys():
    m = compute_metrics(_ROWS)
    assert "alpha" in m["by_project"]
    assert "beta" in m["by_project"]


def test_a_row_with_no_model_is_grouped_rather_than_dropped():
    """Losing rows silently is how a total stops matching its parts."""
    m = compute_metrics([{"project": "alpha", "tests_passed": True}])
    assert m["by_model"]["unknown"]["attempts"] == 1
    assert m["overall"]["attempts"] == sum(v["attempts"] for v in m["by_model"].values())


def test_coder_is_accepted_as_an_alias_for_model():
    m = compute_metrics([{"coder": "codex", "tests_passed": True}])
    assert "codex" in m["by_model"]


# ── lead times ───────────────────────────────────────────────────────────────

def test_lead_times_empty_when_no_timestamps():
    lt = compute_metrics(_ROWS)["lead_times"]
    assert lt["objective_to_prompt"] == {"median_min": None, "p90_min": None, "count": 0}
    assert lt["prompt_to_merged"] == {"median_min": None, "p90_min": None, "count": 0}


def test_lead_times_with_data():
    """Two hours from prompt to merged, reported in minutes."""
    rows = [{
        "integrated": True,
        "created_at": "2025-01-01T00:00:00Z",
        "started_at": "2025-01-01T00:30:00Z",
        "completed_at": "2025-01-01T02:30:00Z",
        "tests_passed": True, "usd": 0, "input_tokens": 0,
        "output_tokens": 0, "wall_ms": 0, "review_failures": 0,
    }]
    lt = compute_metrics(rows)["lead_times"]
    assert lt["objective_to_prompt"]["median_min"] == 30.0
    assert lt["prompt_to_merged"]["median_min"] == 120.0
    assert lt["prompt_to_merged"]["count"] == 1


def test_merged_at_is_accepted_as_completed_at():
    rows = [{"started_at": "2025-01-01T00:00:00Z",
             "merged_at": "2025-01-01T01:00:00Z"}]
    assert compute_metrics(rows)["lead_times"]["prompt_to_merged"]["median_min"] == 60.0


def test_an_unparseable_timestamp_is_skipped_not_fatal():
    rows = [{"started_at": "whenever", "completed_at": "2025-01-01T01:00:00Z"},
            {"started_at": "2025-01-01T00:00:00Z", "completed_at": "2025-01-01T01:00:00Z"}]
    lt = compute_metrics(rows)["lead_times"]
    assert lt["prompt_to_merged"]["count"] == 1


def test_a_negative_or_absurd_span_is_excluded():
    """A completed_at before started_at is corrupt data, and a span over the
    7-day cap is a stalled row rather than a lead time."""
    rows = [
        {"started_at": "2025-01-02T00:00:00Z", "completed_at": "2025-01-01T00:00:00Z"},
        {"started_at": "2025-01-01T00:00:00Z", "completed_at": "2025-03-01T00:00:00Z"},
    ]
    assert compute_metrics(rows)["lead_times"]["prompt_to_merged"]["count"] == 0


def test_p90_is_reported_alongside_the_median():
    rows = [{"started_at": "2025-01-01T00:00:00Z",
             "completed_at": "2025-01-01T%02d:00:00Z" % h} for h in range(1, 11)]
    st = compute_metrics(rows)["lead_times"]["prompt_to_merged"]
    assert st["count"] == 10
    assert st["p90_min"] >= st["median_min"]


# ── deploy success ───────────────────────────────────────────────────────────

def test_deploy_rate_is_none_when_no_deploy_was_observed():
    """The defect this replaced: `r.get("deploy_ok", True)` counted a MISSING
    flag as a success, and nothing in the repo writes deploy_ok to an outcomes
    row — so the rate was structurally incapable of being anything but 1.0."""
    d = compute_metrics(_ROWS)["deploy_success_rate"]
    assert d["rate"] is None
    assert d["attempted"] == 0
    assert d["unknown"] == 1


def test_a_failed_deploy_moves_the_rate():
    rows = [{"integrated": True, "deploy_ok": True},
            {"integrated": True, "deploy_ok": False}]
    d = compute_metrics(rows)["deploy_success_rate"]
    assert d["rate"] == 0.5
    assert d["succeeded"] == 1
    assert d["attempted"] == 2
    assert d["unknown"] == 0


def test_rows_without_a_signal_do_not_dilute_the_rate():
    rows = [{"integrated": True, "deploy_ok": False},
            {"integrated": True}, {"integrated": True}]
    d = compute_metrics(rows)["deploy_success_rate"]
    assert d["rate"] == 0.0
    assert d["attempted"] == 1
    assert d["unknown"] == 2


def test_unmerged_rows_are_not_deploy_candidates():
    rows = [{"integrated": False, "deploy_ok": False}]
    d = compute_metrics(rows)["deploy_success_rate"]
    assert d["rate"] is None
    assert d["unknown"] == 0


# ── knowledge reuse ──────────────────────────────────────────────────────────

def test_knowledge_reuse_none():
    assert compute_metrics(_ROWS)["knowledge_reuse_rate"]["rate"] == 0.0


def test_knowledge_reuse_present():
    rows = [{"context_reuse": True, "tests_passed": True, "integrated": True}]
    k = compute_metrics(rows)["knowledge_reuse_rate"]
    assert k["rate"] == 1.0
    assert k["reused"] == 1


def test_reuse_hit_is_accepted_as_an_alias():
    assert compute_metrics([{"reuse_hit": True}])["knowledge_reuse_rate"]["rate"] == 1.0


def test_knowledge_reuse_is_none_on_empty_input():
    k = compute_metrics([])["knowledge_reuse_rate"]
    assert k["rate"] is None
    assert k["total"] == 0


# ── shape ────────────────────────────────────────────────────────────────────

def test_empty_input_produces_every_key():
    m = compute_metrics([])
    assert m["overall"]["attempts"] == 0
    assert set(m) == {"overall", "by_model", "by_project", "lead_times",
                      "deploy_success_rate", "knowledge_reuse_rate"}
    assert m["by_model"] == {} and m["by_project"] == {}
