import pytest
from triage.types import PropositionKind, StakeOutcome
import triage.staking_engine as engine

@pytest.fixture(autouse=True)
def _c():
    engine.invalidate(); yield; engine.invalidate()

def test_rejects_personal():
    assert engine.create_proposition(kind="PERSONAL", subject_id="n1", statement="x") is None

def test_accepts_professional():
    p = engine.create_proposition(kind=PropositionKind.CREDENTIAL_ACTION, subject_id="n1", statement="x")
    assert p is not None and p.kind == PropositionKind.CREDENTIAL_ACTION

def test_confirmed_boosts():
    p = engine.create_proposition(kind=PropositionKind.RETENTION_RISK, subject_id="d1", statement="x")
    engine.place_stake("sA", p.id, amount=2.0, direction="FOR")
    entries = engine.resolve(p.id, StakeOutcome.CONFIRMED)
    assert len(entries)==1 and entries[0].credibility_delta > 0 and engine.get_credibility("sA") > 1.0

def test_contradicted_burns():
    p = engine.create_proposition(kind=PropositionKind.RETENTION_RISK, subject_id="d1", statement="x")
    engine.place_stake("sB", p.id, amount=2.0, direction="FOR")
    entries = engine.resolve(p.id, StakeOutcome.CONTRADICTED)
    assert len(entries)==1 and entries[0].credibility_delta < 0 and engine.get_credibility("sB") < 1.0

def test_peer_prediction():
    p = engine.create_proposition(kind=PropositionKind.PERFORMANCE_PERCENTILE, subject_id="d2", statement="x")
    engine.place_stake("p1", p.id, 1.0, "FOR"); engine.place_stake("p2", p.id, 1.0, "FOR")
    engine.place_stake("p3", p.id, 1.0, "AGAINST")
    assert abs(engine.peer_prediction_score(p.id) - 2.0/3.0) < 0.01

def test_market_risk():
    p = engine.create_proposition(kind=PropositionKind.UNIT_SAFETY_SCORE_DIRECTION, subject_id="u7", statement="x")
    engine.place_stake("s1", p.id, 3.0, "AGAINST")
    r = engine.market_implied_risk("u7")
    assert r.score > 0 and r.contributing_propositions == 1

def test_fail_soft():
    assert engine.place_stake("","",1.0) is None
    assert engine.resolve("x", StakeOutcome.CONFIRMED) == []
    assert engine.peer_prediction_score("x") == 0.0
