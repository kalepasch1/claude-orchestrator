import improvement_miner


def test_full_review_lane_keeps_bounded_discovery_running(monkeypatch):
    monkeypatch.setattr(improvement_miner, "PER_RUN", 4)
    assert improvement_miner._draft_slots({"limited": True, "slots": 0}) == 4


def test_open_review_lane_respects_available_slots(monkeypatch):
    monkeypatch.setattr(improvement_miner, "PER_RUN", 4)
    assert improvement_miner._draft_slots({"limited": False, "slots": 2}) == 2
