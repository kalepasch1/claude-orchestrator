import improvement_optimizer as optimizer


def test_semantic_novelty_rejects_paraphrased_duplicate():
    old = {"id": "p1", "title": "Route models by deployed value",
           "proposal": "Select vendors using verified deployments per minute and cost."}
    new = {"title": "Optimize vendor routes for deployment value",
           "proposal": "Rank model vendors by verified deployed value per minute and dollar."}
    result = optimizer.novel(new, [old], threshold=0.35)
    assert result["novel"] is False
    assert result["nearest"] == "p1"


def test_unrelated_improvement_remains_novel():
    old = {"title": "Route models by deployed value", "proposal": "Rank vendors by releases."}
    new = {"title": "Repair inaccessible color contrast", "proposal": "Enforce WCAG contrast in CSS tokens."}
    assert optimizer.novel(new, [old])["novel"] is True


def test_generation_stops_when_review_capacity_is_full(monkeypatch):
    monkeypatch.setattr(optimizer, "REVIEW_CAP", 2)
    monkeypatch.setattr(optimizer, "BUILD_CAP", 2)

    class DB:
        def select(self, table, params):
            if table == "improvement_proposals":
                return [{"id": "a"}, {"id": "b"}]
            return []

    result = optimizer.capacity(DB())
    assert result["limited"] is True
    assert result["slots"] == 0


def test_generation_slots_follow_slowest_downstream_stage(monkeypatch):
    monkeypatch.setattr(optimizer, "REVIEW_CAP", 5)
    monkeypatch.setattr(optimizer, "BUILD_CAP", 3)

    class DB:
        def select(self, table, params):
            return [{"id": "one"}] if table == "improvement_proposals" else [{"id": "build"}, {"id": "build2"}]

    result = optimizer.capacity(DB())
    assert result["slots"] == 1
