import pytest
import triage.ledger as ledger

@pytest.fixture(autouse=True)
def _c():
    ledger.invalidate(); yield; ledger.invalidate()

def test_separate_ledgers():
    r = ledger.write_report(subject_id="d1", reporter_id="n1", evidence_grade="Documented", summary="Unsafe")
    e = ledger.write_endorsement(subject_id="d1", endorser_id="n2", evidence_grade="Corroborated-pattern", summary="Great")
    assert r and e
    assert len(ledger.get_reports("d1"))==1 and len(ledger.get_endorsements("d1"))==1

def test_grade_enforced():
    assert ledger.write_report("d2","r1","Documented","t") is not None
    assert ledger.write_report("d2","r1","INVALID","t") is None

def test_grade_travels():
    ledger.write_report("d3","r1","Single-observation","x")
    assert ledger.get_reports("d3")[0].evidence_grade == "Single-observation"

def test_fail_soft():
    assert ledger.write_report("","","Documented","") is None
    assert ledger.get_reports("none") == []
