import route_value_optimizer as rvo


def test_small_samples_never_drive_production_allocation(monkeypatch):
    monkeypatch.setattr(rvo, "MIN_SAMPLES", 20)
    monkeypatch.setattr(rvo, "MIN_DEPLOYS", 2)
    rows = [{"model": "deepseek-v4-flash", "deployed": True,
             "integrated": True, "tests_passed": True, "wall_ms": 1000, "usd": 0.001}]
    result = rvo.summarize(rows, "deepseek")
    assert result["confident"] is False
    assert result["score"] == 0


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
