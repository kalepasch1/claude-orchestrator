from __future__ import annotations
import threading, uuid
from typing import Dict, List, Optional
from triage.types import EVIDENCE_GRADE_ORDER, EvidenceGrade, GoldEndorsement, RiskReport

class _DualLedger:
    def __init__(self):
        self._lock = threading.Lock()
        self._rr: Dict[str, List[RiskReport]] = {}
        self._ge: Dict[str, List[GoldEndorsement]] = {}

    def write_report(self, subject_id, reporter_id, evidence_grade, summary, details="", witnesses=None, severity=1):
        try:
            if not subject_id or not reporter_id or not summary: return None
            if evidence_grade not in EVIDENCE_GRADE_ORDER: return None
            r = RiskReport(subject_id=subject_id, reporter_id=reporter_id, evidence_grade=evidence_grade,
                           summary=summary, details=details, witnesses=witnesses or [],
                           severity=max(1,min(5,severity)), id=uuid.uuid4().hex[:12])
            with self._lock: self._rr.setdefault(subject_id, []).append(r)
            return r
        except Exception: return None

    def write_endorsement(self, subject_id, endorser_id, evidence_grade, summary, details=""):
        try:
            if not subject_id or not endorser_id or not summary: return None
            if evidence_grade not in EVIDENCE_GRADE_ORDER: return None
            e = GoldEndorsement(subject_id=subject_id, endorser_id=endorser_id, evidence_grade=evidence_grade,
                                summary=summary, details=details, id=uuid.uuid4().hex[:12])
            with self._lock: self._ge.setdefault(subject_id, []).append(e)
            return e
        except Exception: return None

    def get_reports(self, sid):
        try:
            with self._lock: return list(self._rr.get(sid, []))
        except Exception: return []

    def get_endorsements(self, sid):
        try:
            with self._lock: return list(self._ge.get(sid, []))
        except Exception: return []

    def stats(self):
        with self._lock: return {"total_reports": sum(len(v) for v in self._rr.values()),
                                 "total_endorsements": sum(len(v) for v in self._ge.values())}

    def invalidate(self):
        with self._lock: self._rr.clear(); self._ge.clear()

_ledger = _DualLedger()
write_report=_ledger.write_report; write_endorsement=_ledger.write_endorsement
get_reports=_ledger.get_reports; get_endorsements=_ledger.get_endorsements
stats=_ledger.stats; invalidate=_ledger.invalidate
