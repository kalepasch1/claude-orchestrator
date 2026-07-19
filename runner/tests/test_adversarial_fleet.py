import adversarial_fleet as af


def test_simulation_is_reproducible_and_gates_failure():
    config = {"budget": 1, "capacity": .01, "max_failure_rate": .05}
    assert af.simulate(config, 20, 7) == af.simulate(config, 20, 7)
    assert not af.simulate(config, 20, 7)["passed"]


def test_did_and_reversible_experiment_verdict():
    assert af.difference_in_differences(10, 11, 10, 15) == 4.0
    assert af.experiment_verdict(4, 1, True) == "graduate"
    assert af.experiment_verdict(-1) == "rollback"
    assert af.experiment_verdict(4, 1, False) == "hold_for_human"


def test_meta_learning_and_vickrey_are_bounded():
    assert af.meta_initialize([1, 1], [[1, 3], [3, 1]], .1) == [0.8, 0.8]
    got = af.vickrey_allocate([{"agent":"a", "roi":10}, {"agent":"b", "roi":7}, {"agent":"c", "roi":3}], 2)
    assert [x["agent"] for x in got] == ["a", "b"]
    assert all(x["clearing_price"] == 3 for x in got)


def test_predictive_and_constitutional_safety():
    assert af.predictive_incident({"queue_growth":.3, "latency_drift":.3})["action"] == "scale"
    assert af.predictive_incident({"queue_growth":.3}) is None
    assert af.amendment_proposal("r", 100, 30)["requires_human_approval"]
    assert af.amendment_proposal("r", 10, 9) is None


def test_compliance_coverage():
    got = af.compliance_coverage([{"control":"a"}], ["a", "b"])
    assert got == {"coverage": .5, "missing": ["b"]}


def test_config_changes_are_simulation_gated(monkeypatch):
    import config_applier
    monkeypatch.setattr(config_applier, "_adversarial_gate", lambda *_: {"passed": False})
    assert config_applier.apply_config("ORCH_SAFE_TEST", "1")["reason"] == "adversarial_simulation"


def test_evidence_bus_spools_and_replays(monkeypatch, tmp_path):
    import evidence_bus
    monkeypatch.setattr(evidence_bus, "_OUTBOX", str(tmp_path / "outbox.jsonl"))
    monkeypatch.setattr(evidence_bus.db, "insert", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")))
    got = evidence_bus.append("app", "kind", "subject", {"x": 1})
    assert not got["persisted"]
    delivered = []
    monkeypatch.setattr(evidence_bus.db, "insert", lambda _table, row, **_kwargs: delivered.append(row))
    assert evidence_bus.flush() == 1
    assert delivered[0]["idempotency_key"] == got["idempotency_key"]
