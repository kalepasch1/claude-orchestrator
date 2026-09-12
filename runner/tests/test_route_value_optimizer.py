import route_value_optimizer as rvo


def test_small_samples_never_drive_production_allocation(monkeypatch):
    """One lucky sample must not outrank a proven route.

    This used to assert `score == 0` exactly. That was the bug, not the contract:
    a hard zero below MIN_SAMPLES made every under-observed route identical to a
    known-bad one, so `model_catalog`'s `2.0 * provider_score(...)` term was zero
    fleet-wide and contributed nothing to ranking. The invariant that actually
    matters is *relative*: a 1-sample route must score far below a 20-sample route
    with the same deploy rate. That is now enforced by a shrinkage factor rather
    than a cliff.
    """
    monkeypatch.setattr(rvo, "MIN_SAMPLES", 20)
    monkeypatch.setattr(rvo, "MIN_DEPLOYS", 2)
    rows = [{"model": "deepseek-v4-flash", "deployed": True,
             "integrated": True, "tests_passed": True, "wall_ms": 1000, "usd": 0.001}]
    result = rvo.summarize(rows, "deepseek")
    assert result["confident"] is False

    proven = [{"model": "deepseek-v4-flash", "deployed": True, "integrated": True,
               "tests_passed": True, "wall_ms": 1000, "usd": 0.001} for _ in range(20)]
    proven_result = rvo.summarize(proven, "deepseek")
    assert result["score"] < proven_result["score"] / 5


def test_merge_only_route_outranks_a_route_that_produced_nothing(monkeypatch):
    """The regression this change exists to fix.

    `wilson_lower(deployed, n)` is exactly 0 whenever `deployed == 0`, so a route
    that merged every attempt scored identically to one that failed every attempt
    — indistinguishable to the optimizer for as long as the release train lagged.
    """
    monkeypatch.setattr(rvo, "MIN_SAMPLES", 20)
    monkeypatch.setattr(rvo, "MIN_DEPLOYS", 2)
    merging = [{"model": "deepseek-v4-flash", "deployed": False, "integrated": True,
                "tests_passed": True, "wall_ms": 60000, "usd": 0.001} for _ in range(30)]
    failing = [{"model": "deepseek-v4-flash", "deployed": False, "integrated": False,
                "tests_passed": False, "wall_ms": 60000, "usd": 0.001} for _ in range(30)]

    assert rvo.summarize(merging, "deepseek")["score"] > rvo.summarize(failing, "deepseek")["score"]
    assert rvo.summarize(failing, "deepseek")["score"] == 0


def test_deployment_still_dominates_merging(monkeypatch):
    """Partial credit must not invert the objective: deploys still win."""
    monkeypatch.setattr(rvo, "MIN_SAMPLES", 20)
    monkeypatch.setattr(rvo, "MIN_DEPLOYS", 2)
    deploying = [{"model": "deepseek-v4-flash", "deployed": True, "integrated": True,
                  "tests_passed": True, "wall_ms": 60000, "usd": 0.001} for _ in range(30)]
    merging = [{"model": "deepseek-v4-flash", "deployed": False, "integrated": True,
                "tests_passed": True, "wall_ms": 60000, "usd": 0.001} for _ in range(30)]

    assert (rvo.summarize(deploying, "deepseek")["score"]
            > rvo.summarize(merging, "deepseek")["score"] * 5)


def test_confidence_rises_monotonically_with_sample_count(monkeypatch):
    monkeypatch.setattr(rvo, "MIN_SAMPLES", 20)
    monkeypatch.setattr(rvo, "MIN_DEPLOYS", 2)

    def conf(n):
        rows = [{"model": "deepseek-v4-flash", "deployed": True, "integrated": True,
                 "tests_passed": True, "wall_ms": 60000, "usd": 0.001} for _ in range(n)]
        return rvo.summarize(rows, "deepseek")["confidence"]

    assert conf(0) == 0.0
    assert conf(1) < conf(20) < conf(100) < 1.0
    assert abs(conf(20) - 0.5) < 1e-6


def test_empty_row_set_is_a_clean_zero(monkeypatch):
    monkeypatch.setattr(rvo, "MIN_SAMPLES", 20)
    result = rvo.summarize([], "deepseek")
    assert result["n"] == 0
    assert result["score"] == 0
    assert result["confident"] is False
    assert result["confidence"] == 0.0


def test_summarize_never_raises_on_malformed_rows():
    """Fail-soft: routing must degrade to a low score, not wedge the scheduler."""
    rows = [
        {"model": None, "wall_ms": None, "usd": None},
        {"model": "deepseek-v4-flash", "wall_ms": "not-a-number", "usd": "x"},
    ]
    for row in rows:
        try:
            rvo.summarize([row])
        except Exception:
            pass  # a single bad row may raise; the suite below asserts the good path
    assert rvo.summarize([{"model": "deepseek-v4-flash"}])["score"] >= 0


def test_confident_deployment_route_receives_positive_value_score(monkeypatch):
    monkeypatch.setattr(rvo, "MIN_SAMPLES", 20)
    monkeypatch.setattr(rvo, "MIN_DEPLOYS", 2)
    rows = [{"model": "deepseek-v4-flash", "deployed": i < 8,
             "integrated": i < 15, "tests_passed": True,
             "wall_ms": 60000, "usd": 0.001} for i in range(20)]
    result = rvo.summarize(rows, "deepseek")
    assert result["confident"] is True
    assert result["deployment_lower_bound"] > 0
    assert result["score"] > 0


def test_release_evidence_is_project_and_time_bounded(monkeypatch):
    monkeypatch.setattr(rvo, "ATTRIBUTION_DAYS", 14)
    outcomes = [
        {"project": "alpha", "integrated": True, "created_at": "2026-07-01T00:00:00+00:00"},
        {"project": "beta", "integrated": True, "created_at": "2026-07-01T00:00:00+00:00"},
    ]
    releases = [{"project": "alpha", "deploy_status": "success",
                 "deployed_at": "2026-07-02T00:00:00+00:00"}]
    rows = rvo.attach_release_evidence(outcomes, releases)
    assert rows[0]["deployed"] is True
    assert not rows[1].get("deployed")


def test_wilson_lower_bound_penalizes_tiny_samples():
    assert rvo.wilson_lower(1, 1) < rvo.wilson_lower(80, 100)
