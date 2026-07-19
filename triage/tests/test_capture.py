import pytest
import triage.capture as capture
from triage.capture import scrub_patient_identifiers

@pytest.fixture(autouse=True)
def _c():
    capture.invalidate(); yield; capture.invalidate()

TX = ("Dr. Smith was negligent during the procedure yesterday. "
      "He administered the wrong dosage to patient John Doe in room 412. "
      "I'm so frustrated with this place. Nobody listens to safety concerns. "
      "Witness was Sarah Johnson. The patient's MRN: 12345678 and DOB: 01/15/1980. "
      "I need to vent, this is ridiculous.")

def test_structuring():
    r = capture.structure_transcript(TX, reporter_id="n1")
    assert r and r.who == "Smith" and r.when == "yesterday"
    assert "Sarah Johnson" in r.witnesses and r.severity >= 3

def test_venting_to_journal():
    r = capture.structure_transcript(TX, reporter_id="n1")
    assert "frustrated" not in r.what.lower()
    j = capture.get_journal("n1")
    assert len(j) > 0 and "frustrated" in " ".join(e.content for e in j).lower()

def test_scrub_ssn():
    s = scrub_patient_identifiers("SSN 123-45-6789 phone (555) 123-4567")
    assert "123-45-6789" not in s and "[REDACTED-SSN]" in s and "[REDACTED-PHONE]" in s

def test_scrub_mrn():
    s = scrub_patient_identifiers("MRN: 12345678")
    assert "12345678" not in s and "[REDACTED-MRN]" in s

def test_scrub_patient():
    s = scrub_patient_identifiers("patient John Smith was seen")
    assert "John Smith" not in s and "[REDACTED-PATIENT]" in s

def test_scrub_empty():
    assert scrub_patient_identifiers("") == ""
    assert scrub_patient_identifiers(None) == ""

def test_fail_soft():
    assert capture.structure_transcript("") is None
    assert capture.structure_transcript(None) is None
