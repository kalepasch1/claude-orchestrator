from __future__ import annotations
import re, threading, uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from triage.types import EVIDENCE_GRADE_ORDER, EvidenceGrade

@dataclass
class StructuredReport:
    id: str; who: str = ""; what: str = ""; when: str = ""
    witnesses: List[str] = field(default_factory=list); severity: int = 1
    evidence_grade: EvidenceGrade = "Single-observation"; raw_transcript: str = ""

@dataclass
class JournalEntry:
    id: str; content: str = ""; source_transcript_id: str = ""

_PATTERNS = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED-SSN]"),
    (re.compile(r"\bMRN[:\s]*\d{6,10}\b", re.I), "[REDACTED-MRN]"),
    (re.compile(r"\bDOB[:\s]*\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b", re.I), "[REDACTED-DOB]"),
    (re.compile(r"\b\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}\b"), "[REDACTED-PHONE]"),
    (re.compile(r"\b(?:patient|pt\.?)\s+[A-Z][a-z]+\s+[A-Z][a-z]+\b"), "[REDACTED-PATIENT]"),
    (re.compile(r"\broom\s+\d{1,4}[A-Z]?\b", re.I), "[REDACTED-ROOM]"),
]

def scrub_patient_identifiers(text):
    try:
        if not text: return ""
        r = text
        for p, rep in _PATTERNS: r = p.sub(rep, r)
        return r
    except Exception: return text if text else ""

_VENTING = ["i'm so frustrated","i can't believe","this is ridiculous","i'm sick of",
            "it drives me crazy","i hate when","why do they always","nobody listens",
            "i'm fed up","ugh","i need to vent"]

def _is_venting(s):
    lo = s.lower().strip()
    return any(v in lo for v in _VENTING)

def _extract_who(t):
    for p in [re.compile(r"(?:[Dd]r\.?|[Dd]octor|[Nn]urse|[Rr][Nn])\s+([A-Z][a-z]+)")]:
        m = p.search(t)
        if m: return m.group(1).strip()
    return ""

def _extract_when(t):
    for p in [re.compile(r"(today|yesterday|this morning|last night|last week)", re.I)]:
        m = p.search(t)
        if m: return m.group(1).strip()
    return ""

def _extract_witnesses(t):
    m = re.search(r"(?:witness|saw|seen by)\s*(?:was|were|:)?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?(?:\s*,\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)*)", t, re.I)
    return [w.strip() for w in m.group(1).split(",") if w.strip()] if m else []

def _severity(t):
    lo = t.lower()
    if any(w in lo for w in ["harm","injury","death","fatal","critical","overdose"]): return 5
    if any(w in lo for w in ["error","mistake","negligent","unsafe","wrong","missed"]): return 3
    return 1

class _CaptureEngine:
    def __init__(self):
        self._lock = threading.Lock()
        self._reports: Dict[str, StructuredReport] = {}
        self._journal: Dict[str, List[JournalEntry]] = {}

    def structure_transcript(self, transcript, reporter_id=""):
        try:
            if not transcript: return None
            sents = re.split(r"[.!?]+", transcript)
            fact, vent = [], []
            for s in sents:
                s = s.strip()
                if not s: continue
                (vent if _is_venting(s) else fact).append(s)
            scrubbed = scrub_patient_identifiers(". ".join(fact))
            rid = uuid.uuid4().hex[:12]
            wit = _extract_witnesses(transcript)
            r = StructuredReport(id=rid, who=_extract_who(transcript), what=scrubbed,
                                 when=_extract_when(transcript), witnesses=wit,
                                 severity=_severity(transcript),
                                 evidence_grade="Corroborated-pattern" if wit else "Single-observation",
                                 raw_transcript=transcript)
            with self._lock:
                self._reports[rid] = r
                if vent:
                    self._journal.setdefault(reporter_id, []).append(
                        JournalEntry(id=uuid.uuid4().hex[:12], content=". ".join(vent), source_transcript_id=rid))
            return r
        except Exception: return None

    def get_journal(self, rid):
        try:
            with self._lock: return list(self._journal.get(rid, []))
        except Exception: return []

    def stats(self):
        with self._lock: return {"reports": len(self._reports), "journals": len(self._journal)}

    def invalidate(self):
        with self._lock: self._reports.clear(); self._journal.clear()

_engine = _CaptureEngine()
structure_transcript=_engine.structure_transcript; get_journal=_engine.get_journal
stats=_engine.stats; invalidate=_engine.invalidate
