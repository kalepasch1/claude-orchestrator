from triage.types import PropositionKind, RiskReport, GoldEndorsement, EVIDENCE_GRADE_ORDER

ALLOWED = {"CREDENTIAL_ACTION","PERFORMANCE_PERCENTILE","UNIT_SAFETY_SCORE_DIRECTION","RETENTION_RISK"}

def test_exactly_4():
    assert {k.name for k in PropositionKind} == ALLOWED

def test_no_personal():
    names = {k.name for k in PropositionKind}
    for p in ["PERSONAL_RELATIONSHIP","FAMILY_STATUS","DATING","HOBBY"]:
        assert p not in names

def test_grade_order():
    assert EVIDENCE_GRADE_ORDER["Documented"] < EVIDENCE_GRADE_ORDER["Corroborated-pattern"] < EVIDENCE_GRADE_ORDER["Single-observation"]

def test_risk_report():
    r = RiskReport(subject_id="s1", reporter_id="r1", evidence_grade="Documented", summary="t")
    assert r.subject_id == "s1"

def test_endorsement():
    e = GoldEndorsement(subject_id="s1", endorser_id="e1", evidence_grade="Corroborated-pattern", summary="g")
    assert e.endorser_id == "e1"

def test_import():
    import triage.types
