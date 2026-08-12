"""Proof for the calibrated filing optimizer (the file named in the task's Proof line).

The Round 8 audit found that `filing_optimizer_v2` is deterministic heuristics with four
hardcoded coefficients, one of which — `estimated_volume_discount = (n - groups) * 0.02` —
asserts a percentage SAVING from a function that has never observed a price.

So the four required properties are each tested, and each is tested from the sceptical
side: the gate must REFUSE on thin data, the fallback must be labelled, the ordering must
be reproducible, and no savings figure may appear without measurement.
"""
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_RUNNER = os.path.dirname(_HERE)
sys.path.insert(0, _RUNNER)

import filing_optimizer_calibration as foc  # noqa: E402
from datetime import date  # noqa: E402

TODAY = date(2026, 8, 12)


def _outcome(i, amended, jurisdiction="US-NY", ftype="annual", prior=0, completeness=1.0,
             deadline="2026-09-01"):
    return {"id": "o-%03d" % i, "jurisdiction": jurisdiction, "type": ftype,
            "prior_amendments": prior, "evidence_completeness": completeness,
            "deadline": deadline, "amended": amended}


def _learnable(n=200):
    """A set where amendment IS predictable from the features, so a real model can win."""
    rows = []
    for i in range(n):
        incomplete = (i % 3 == 0)
        prior = 2 if i % 5 == 0 else 0
        amended = incomplete or prior > 0
        rows.append(_outcome(i, amended,
                             jurisdiction="US-NY" if i % 2 else "US-NJ",
                             ftype="annual" if i % 4 else "quarterly",
                             prior=prior,
                             completeness=0.4 if incomplete else 1.0))
    return rows


FILINGS = [
    {"id": "f1", "jurisdiction": "US-NY", "type": "annual", "deadline": "2026-08-20",
     "prior_amendments": 2, "evidence_completeness": 0.5},
    {"id": "f2", "jurisdiction": "US-NJ", "type": "quarterly", "deadline": "2026-08-15",
     "prior_amendments": 0, "evidence_completeness": 1.0},
    {"id": "f3", "jurisdiction": "US-NY", "type": "annual", "deadline": "2026-12-01",
     "prior_amendments": 0, "evidence_completeness": 0.9},
]


# ─── 1. Calibration threshold ───────────────────────────────────────────────

def test_a_thin_sample_is_refused_by_the_gate():
    model = foc.train([_outcome(i, i % 2 == 0) for i in range(10)])
    assert model["calibrated"] is False
    assert any("floor is" in r for r in model["reasons"])
    assert "decoration" in " ".join(model["reasons"])


def test_a_single_class_outcome_set_is_refused():
    model = foc.train([_outcome(i, True) for i in range(120)])
    assert model["calibrated"] is False
    assert any("single-class" in r for r in model["reasons"])


def test_the_gate_measures_against_the_INCUMBENT_not_against_zero():
    model = foc.train(_learnable(), today=TODAY)
    assert "heuristic_brier" in model["metrics"]
    assert "model_brier" in model["metrics"]
    # The margin is applied to the difference, not to the model score alone.
    improvement = model["metrics"]["improvement"]
    assert model["calibrated"] == (improvement >= foc.required_brier_margin())


def test_a_model_that_does_not_beat_the_heuristic_does_not_ship(monkeypatch):
    monkeypatch.setenv("ORCH_FILING_BRIER_MARGIN", "0.9")  # unreachable margin
    model = foc.train(_learnable(), today=TODAY)
    assert model["calibrated"] is False
    assert any("is not beaten" in r for r in model["reasons"])


def test_the_validation_split_is_deterministic():
    outcomes = _learnable()
    a_train, a_val = foc.split_outcomes(outcomes)
    b_train, b_val = foc.split_outcomes(outcomes)
    assert [o["id"] for o in a_train] == [o["id"] for o in b_train]
    assert [o["id"] for o in a_val] == [o["id"] for o in b_val]
    assert a_train and a_val


def test_the_feature_store_is_built_from_the_TRAINING_half_only():
    # Building rate features from everything leaks validation labels and inflates the score.
    model = foc.train(_learnable(), today=TODAY)
    trained_on = model["store"]["provenance"]["sample_size"]
    assert trained_on == model["metrics"]["train_n"]
    assert trained_on < model["sample_size"]


def test_thresholds_are_orch_prefixed_and_fail_soft(monkeypatch):
    monkeypatch.setenv("ORCH_FILING_MIN_SAMPLES", "7")
    assert foc.min_training_samples() == 7
    monkeypatch.setenv("ORCH_FILING_MIN_SAMPLES", "not-a-number")
    assert foc.min_training_samples() == 60


# ─── 2. Fallback ────────────────────────────────────────────────────────────

def test_the_fallback_is_labelled_as_a_heuristic_not_as_a_model():
    result = foc.recommend(FILINGS, outcomes=[], today=TODAY)
    assert result["method"] == "heuristic"
    assert result["calibrated"] is False
    assert result["fallback_reasons"]


def test_the_fallback_explanation_says_the_coefficients_were_not_fitted():
    result = foc.recommend(FILINGS, outcomes=[], today=TODAY)
    meanings = " ".join(c["meaning"] for r in result["filings"] for c in r["explanation"])
    assert "NOT fitted to data" in meanings


def test_the_fallback_risk_matches_the_incumbent_exactly():
    result = foc.recommend(FILINGS, outcomes=[], today=TODAY)
    for row, filing in zip(sorted(result["filings"], key=lambda r: r["id"]),
                           sorted(FILINGS, key=lambda f: f["id"])):
        assert row["amendment_risk"] == pytest.approx(foc.heuristic_risk(filing))


def test_the_incumbent_is_kept_not_deleted():
    baseline = foc.heuristic_baseline(FILINGS, today=TODAY)
    assert "filings" in baseline
    assert len(baseline["filings"]) == 3


def test_recommend_falls_back_rather_than_raising_on_garbage():
    for bad in (None, "not-a-list", [{"id": None}]):
        result = foc.recommend(bad, outcomes=None, today=TODAY)
        assert result["method"] in ("heuristic", "calibrated_model")
        assert isinstance(result["filings"], list)


# ─── 3. Deadline prioritization ─────────────────────────────────────────────

def test_the_nearest_deadline_is_ordered_first():
    result = foc.recommend(FILINGS, outcomes=[], today=TODAY)
    deadlines = [r["deadline"] for r in result["filings"]]
    assert deadlines == sorted(deadlines)
    assert result["filings"][0]["id"] == "f2"  # 2026-08-15


def test_risk_breaks_a_deadline_tie_highest_first():
    same_day = [
        {"id": "low", "jurisdiction": "US-NY", "type": "annual", "deadline": "2026-08-20",
         "prior_amendments": 0, "evidence_completeness": 1.0},
        {"id": "high", "jurisdiction": "US-NY", "type": "annual", "deadline": "2026-08-20",
         "prior_amendments": 3, "evidence_completeness": 0.2},
    ]
    result = foc.recommend(same_day, outcomes=[], today=TODAY)
    assert [r["id"] for r in result["filings"]] == ["high", "low"]


def test_urgency_is_a_model_feature_not_only_a_sort_key():
    assert "days_to_deadline_inv" in foc.FEATURES
    values, _ = foc.extract_features(FILINGS[0], foc.build_feature_store([]), today=TODAY)
    near, _ = foc.extract_features({"deadline": "2026-08-13"}, {}, today=TODAY)
    far, _ = foc.extract_features({"deadline": "2027-08-13"}, {}, today=TODAY)
    assert near["days_to_deadline_inv"] > far["days_to_deadline_inv"]
    assert 0 <= values["days_to_deadline_inv"] <= 1


# ─── 4. Reproducible recommendations ────────────────────────────────────────

def test_the_same_inputs_produce_an_identical_ordering_and_digest():
    a = foc.recommend(FILINGS, outcomes=_learnable(), today=TODAY)
    b = foc.recommend(FILINGS, outcomes=_learnable(), today=TODAY)
    assert [r["id"] for r in a["filings"]] == [r["id"] for r in b["filings"]]
    assert [r["amendment_risk"] for r in a["filings"]] == [r["amendment_risk"] for r in b["filings"]]
    assert foc.recommendation_digest(a) == foc.recommendation_digest(b)


def test_input_order_does_not_change_the_output():
    a = foc.recommend(FILINGS, outcomes=[], today=TODAY)
    b = foc.recommend(list(reversed(FILINGS)), outcomes=[], today=TODAY)
    assert foc.recommendation_digest(a) == foc.recommendation_digest(b)


def test_the_digest_changes_when_the_method_changes():
    heuristic = foc.recommend(FILINGS, outcomes=[], today=TODAY)
    trained = foc.recommend(FILINGS, outcomes=_learnable(), today=TODAY)
    if trained["calibrated"]:
        assert foc.recommendation_digest(heuristic) != foc.recommendation_digest(trained)


def test_there_is_no_hidden_clock_dependency():
    values_a, _ = foc.extract_features({"deadline": "2026-09-01"}, {}, today=date(2026, 8, 12))
    values_b, _ = foc.extract_features({"deadline": "2026-09-01"}, {}, today=date(2026, 8, 12))
    assert values_a == values_b


# ─── 5. Provenance ──────────────────────────────────────────────────────────

def test_every_history_derived_feature_carries_the_ids_that_produced_it():
    store = foc.build_feature_store(_learnable(80))
    _, provenance = foc.extract_features(FILINGS[0], store, today=TODAY)
    j = provenance["jurisdiction_amendment_rate"]
    assert j["source"] == "history"
    assert j["n"] > 0 and len(j["ids"]) == j["n"]


def test_an_unseen_key_is_marked_as_a_global_fallback_not_as_measured():
    store = foc.build_feature_store(_learnable(80))
    _, provenance = foc.extract_features(
        {"jurisdiction": "XX-NOWHERE", "type": "never-seen"}, store, today=TODAY)
    assert provenance["jurisdiction_amendment_rate"]["source"] == "global_fallback"
    assert provenance["type_amendment_rate"]["n"] == 0


def test_the_training_provenance_records_the_outcome_ids():
    store = foc.build_feature_store(_learnable(80))
    prov = store["provenance"]
    assert prov["source"] == "approved_historical_filing_outcomes"
    assert prov["sample_size"] == 80
    assert len(prov["outcome_ids"]) == 80


# ─── 6. No savings claim unless measured ────────────────────────────────────

def test_no_savings_are_claimed_without_realised_costs():
    result = foc.recommend(FILINGS, outcomes=_learnable(), today=TODAY)
    assert result["savings"]["measured"] is False
    assert result["savings"]["savings_usd"] is None
    assert "not a saving" in result["savings"]["note"]


def test_savings_are_reported_only_from_realised_costs():
    result = foc.recommend(FILINGS, outcomes=[], today=TODAY, realised_costs=[
        {"baseline_usd": 1000, "actual_usd": 850},
        {"baseline_usd": 500, "actual_usd": 500},
    ])
    assert result["savings"]["measured"] is True
    assert result["savings"]["savings_usd"] == 150.0
    assert result["savings"]["n"] == 2


def test_the_estimated_volume_discount_is_gone():
    # The specific unmeasured claim the audit flagged.
    result = foc.optimize(FILINGS, outcomes=[], today=TODAY)
    assert "estimated_volume_discount" not in result
    assert "savings" in result
    # f1 and f3 share US-NY:annual, so three filings batch into two keys — which under the
    # incumbent was precisely the input to the fabricated (3 - 2) * 0.02 "discount".
    assert result["batch_count"] == 2


def test_unparseable_realised_costs_claim_nothing():
    saving = foc.measured_savings([{"baseline_usd": "many", "actual_usd": None}])
    assert saving["measured"] is False
    assert saving["savings_usd"] is None


# ─── 7. Evidence trail and approval workflow ────────────────────────────────

def test_the_evidence_record_carries_the_refusal_not_just_the_result():
    result = foc.recommend(FILINGS, outcomes=[], today=TODAY)
    record = foc.evidence_record(result, task_id="t-1")
    assert record["kind"] == "filing_optimizer_recommendation"
    assert record["method"] == "heuristic"
    assert record["fallback_reasons"]
    assert record["digest"]
    assert record["reproducible"] is True


def test_an_uncalibrated_recommendation_always_requires_a_human():
    result = foc.recommend(FILINGS, outcomes=[], today=TODAY)
    approval = foc.approval_requirement(result)
    assert approval["requires_approval"] is True
    assert approval["tier"] == "human"
    assert "uncalibrated heuristic fallback" in approval["reason"]


def test_a_calibrated_recommendation_still_requires_review():
    result = foc.recommend(FILINGS, outcomes=_learnable(), today=TODAY)
    approval = foc.approval_requirement(result)
    assert approval["requires_approval"] is True
    assert approval["tier"] in ("review", "human")


def test_the_evidence_digest_is_stable_across_records():
    result = foc.recommend(FILINGS, outcomes=[], today=TODAY)
    assert foc.evidence_record(result)["digest"] == foc.evidence_record(result)["digest"]
