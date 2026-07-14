import improvement_scrutiny


def _idea():
    return {
        "title": "Route by production-deployed value per minute",
        "current_state": "Only one of fifty test-passing attempts reaches a verified production release.",
        "proposal": "Attribute release verification to each route and optimize allocations using that conversion.",
        "expected_multiplier": "50x",
        "multiplier_basis": "Raise deployed conversion from 1/50 to 1/1: 50/1 = 50x upper-bound hypothesis.",
        "baseline_metric": "tests-passed to verified-deployment conversion = 2% over 30 days",
        "target_metric": "verified-deployment conversion >= 20% without rollback regression",
        "acceptance_tests": ["release attribution joins to route", "shadow allocator improves held-out conversion"],
        "measurement_plan": "Run a 14-day shadow control with at least 50 attempts before allocation changes.",
        "rollback_plan": "Restore prior weights if conversion falls 5% or rollback rate rises 2%.",
        "rationale": "This attacks the measured conversion constraint instead of increasing draft volume.",
    }


def test_measurable_50x_hypothesis_is_admitted_for_committee_scrutiny():
    result = improvement_scrutiny.assess(_idea())

    assert result["pass"] is True
    assert result["multiplier_hypothesis"] == 50
    assert result["label"] == "scrutiny-ready-hypothesis"


def test_unfalsifiable_multiplier_is_not_allowed_to_auto_queue():
    idea = _idea()
    idea["multiplier_basis"] = "This should be dramatically better."
    idea["acceptance_tests"] = ["looks good"]

    result = improvement_scrutiny.assess(idea)

    assert result["pass"] is False
    assert "50x-claim-lacks-baseline-math" in result["reasons"]
    assert "needs-two-acceptance-tests" in result["reasons"]


def test_claimed_50x_is_rejected_when_its_numbers_only_imply_5x():
    idea = _idea()
    idea["multiplier_basis"] = "Reduce the bottleneck from 40 percent of runtime to 8 percent."

    result = improvement_scrutiny.assess(idea)

    assert result["pass"] is False
    assert "multiplier-math-does-not-match-claim" in result["reasons"]


def test_implementation_spec_labels_multiplier_as_hypothesis_and_carries_rollback():
    spec = improvement_scrutiny.implementation_spec(_idea(), "orchestration")

    assert "not a measured result" in spec
    assert "Rollback:" in spec
    assert "Acceptance tests:" in spec


def test_legacy_redirect_only_quarantines_untouched_queue():
    class DB:
        def __init__(self):
            self.updates = []

        def select(self, table, params):
            if table == "improvement_proposals":
                return [{"id": "p1", "task_slug": "improve-one", "status": "queued"},
                        {"id": "p2", "task_slug": "improve-two", "status": "queued"}]
            return [{"id": "t1", "slug": "improve-one", "state": "QUEUED", "note": ""},
                    {"id": "t2", "slug": "improve-two", "state": "DECOMPOSED", "note": ""}]

        def update(self, table, where, patch):
            self.updates.append((table, where, patch))

    db = DB()
    result = improvement_scrutiny.redirect_legacy_direct_queue(db)

    assert result == {"redirected": 1, "preserved_active_or_decomposed": 1}
    assert any(table == "tasks" and patch["state"] == "QUARANTINED"
               for table, _, patch in db.updates)
    assert any(table == "improvement_proposals" and patch["status"] == "for_review"
               for table, _, patch in db.updates)
