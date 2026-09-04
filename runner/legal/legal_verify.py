#!/usr/bin/env python3
"""legal_verify.py — LEGAL-VERIFY gate: a draft must pass before a human reads it.

WHAT THIS IS. The analog of a screenshot-verify gate, for legal text. A drafting
agent produces a policy/terms/notice; this decides whether that draft is fit to go
forward, and when it is not, hands back MACHINE-READABLE reasons the drafting agent
can act on rather than a bare "rejected".

WHY IT IS SHAPED THIS WAY. A previous attempt was blocked because the spec named
four things that do not exist in this repo: a screenshot-verify reference impl, a
competitor-snapshot corpus, a jurisdiction/app-market registry, and a `runner/legal/`
package. Three of those are DATA, not contracts. So the corpora are INJECTED —
`verify(draft, required_jurisdictions=..., competitor_snapshots=...)` — and this
module defines the contract those corpora must satisfy instead of waiting on them.
The module is therefore testable and mergeable today, and a corpus can be wired in
later without changing this file.

WHAT IT DOES NOT DO. No network, no DB, no filesystem, no model calls, and no legal
advice: every check is a property of the text itself. It does not decide whether a
license or registration is required — that routing is a separate, owner-gated
concern and deliberately not implemented here.

THE SIMILARITY CEILING IS STRICT. A draft that is too close to a stored competitor
document is REJECTED, not warned about. A warning is something a tired reviewer
clicks through, and the entire cost of this check is paid at that moment.

CONVENTIONS. Fail-soft: every public function returns a result, never raises —
a malformed draft must produce "rejected, here is why", not a traceback that
takes down the drafting loop. Tunables are ORCH_-prefixed so they are
fleet-pushable via fleet_control.py.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------


def _env_float(name: str, default: float) -> float:
    """Read an ORCH_ knob. Never raises; a bad value falls back to the default.

    This module is imported by the drafting loop, so a malformed knob must not be
    able to raise at import time.
    """
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        print(f"[legal_verify] {name} unusable; using default {default}", flush=True)
        return default


#: Maximum tolerated similarity to any stored competitor document, 0..1.
#: Deliberately strict: above this the draft is REJECTED, not flagged.
SIMILARITY_CEILING = _env_float("ORCH_LEGAL_SIMILARITY_CEILING", 0.35)

#: Highest acceptable US-grade reading level. Consumer-facing legal text above
#: this is unreadable in practice, which is itself a compliance problem.
READABILITY_CEILING = _env_float("ORCH_LEGAL_READABILITY_CEILING", 14.0)

#: Shingle width for similarity. 5-word shingles catch lifted sentences while
#: tolerating ordinary shared legal boilerplate ("to the extent permitted by law").
SHINGLE_N = 5

#: Check ids, pinned. Adding one is additive; renaming one breaks callers that
#: route on the id, so treat these as a contract.
CHECKS: Tuple[str, ...] = (
    "internal_consistency",
    "defined_terms",
    "jurisdiction_coverage",
    "readability",
    "competitor_similarity",
)

#: Checks whose failure is fatal regardless of anything else on the page.
BLOCKING_CHECKS: Tuple[str, ...] = ("competitor_similarity", "internal_consistency")


# ---------------------------------------------------------------------------
# Result contract
# ---------------------------------------------------------------------------


class Finding(tuple):
    """(check, severity, message, evidence). One machine-actionable problem."""

    __slots__ = ()
    SEVERITIES = ("error", "warning")

    def __new__(cls, check: str, severity: str, message: str, evidence: Any = None):
        severity = severity if severity in cls.SEVERITIES else "error"
        return super().__new__(cls, (str(check), severity, str(message), evidence))

    @property
    def check(self) -> str:
        return self[0]

    @property
    def severity(self) -> str:
        return self[1]

    @property
    def message(self) -> str:
        return self[2]

    @property
    def evidence(self) -> Any:
        return self[3]

    def as_dict(self) -> Dict[str, Any]:
        return {"check": self.check, "severity": self.severity,
                "message": self.message, "evidence": self.evidence}


class VerifyResult:
    """The contracts result type for LEGAL-VERIFY.

    `ok` is the gate. `findings` is what goes back to the drafting agent. `metrics`
    carries the measured numbers so a reviewer can see how close a pass was, which
    is the difference between a gate and a coin flip.
    """

    __slots__ = ("ok", "findings", "metrics")

    def __init__(self, ok: bool, findings: Sequence[Finding] = (),
                 metrics: Optional[Dict[str, Any]] = None):
        self.ok = bool(ok)
        self.findings = tuple(findings)
        self.metrics = dict(metrics or {})

    def __bool__(self) -> bool:
        return self.ok

    @property
    def errors(self) -> Tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity == "error")

    @property
    def warnings(self) -> Tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity == "warning")

    def reasons(self) -> Tuple[str, ...]:
        """Human-readable reasons, errors first. Empty when the draft passed."""
        return tuple(f.message for f in self.errors) + tuple(f.message for f in self.warnings)

    def bounce(self) -> Optional[Dict[str, Any]]:
        """The payload handed back to the drafting agent, or None when ok.

        Grouped by check so the drafting agent can fix one class of problem at a
        time instead of being handed an undifferentiated wall of complaints.
        """
        if self.ok:
            return None
        by_check: Dict[str, List[Dict[str, Any]]] = {}
        for finding in self.errors:
            by_check.setdefault(finding.check, []).append(finding.as_dict())
        return {"action": "revise", "blocking": sorted(by_check),
                "findings": by_check, "metrics": self.metrics}

    def as_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "metrics": self.metrics,
                "findings": [f.as_dict() for f in self.findings]}


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")
_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]?")
_VOWEL_GROUP_RE = re.compile(r"[aeiouy]+")


def _words(text: str) -> List[str]:
    return _WORD_RE.findall(text or "")


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENTENCE_RE.findall(text or "") if s.strip()]


def _syllables(word: str) -> int:
    """Approximate syllable count. Good enough for a grade-level ceiling; exactness
    would need a pronunciation dictionary and would not change any decision here."""
    word = (word or "").lower().strip("'-")
    if not word:
        return 0
    groups = _VOWEL_GROUP_RE.findall(word)
    count = len(groups)
    if word.endswith("e") and count > 1 and not word.endswith(("le", "ee", "ye")):
        count -= 1
    return max(count, 1)


def readability_grade(text: str) -> float:
    """Flesch-Kincaid grade level. Returns 0.0 for empty/unusable input."""
    words = _words(text)
    sentences = _sentences(text)
    if not words or not sentences:
        return 0.0
    wps = len(words) / len(sentences)
    spw = sum(_syllables(w) for w in words) / len(words)
    return round(0.39 * wps + 11.8 * spw - 15.59, 2)


def _shingles(text: str, n: int = SHINGLE_N) -> set:
    words = [w.lower() for w in _words(text)]
    if len(words) < n:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def similarity(a: str, b: str, n: int = SHINGLE_N) -> float:
    """Jaccard similarity over word shingles, 0..1. Fail-soft: 0.0 on junk input."""
    try:
        sa, sb = _shingles(a, n), _shingles(b, n)
    except Exception:
        return 0.0
    if not sa or not sb:
        return 0.0
    return round(len(sa & sb) / len(sa | sb), 4)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

#: Obligation verbs whose negation flips the meaning of a clause.
_MODALS = ("shall", "must", "will", "may")

#: "We will not sell your data" / "We will sell your data" — same subject+verb,
#: opposite polarity. This is the contradiction shape that survives review, because
#: the two sentences are usually paragraphs apart.
_CLAUSE_RE = re.compile(
    r"\b(?P<subject>[A-Za-z][\w \-]{0,40}?)\s+"
    r"(?P<modal>" + "|".join(_MODALS) + r")\s+"
    r"(?P<neg>not\s+|never\s+)?"
    r"(?P<verb>[a-z]+)",
    re.IGNORECASE)

#: "retained for 30 days" stated twice with different numbers. The context is taken
#: from the words BEFORE the number rather than from the regex itself: a non-greedy
#: leading group happily matches the empty string, so every duration got the same
#: empty context and no conflict could ever be detected.
_DURATION_RE = re.compile(r"(?P<num>\d+)\s+(?P<unit>day|month|year)s?\b", re.IGNORECASE)

#: Filler that says nothing about WHICH obligation a period belongs to.
_DURATION_STOPWORDS = frozenset({
    "for", "of", "to", "the", "a", "an", "up", "at", "least", "most", "than",
    "is", "are", "be", "been", "we", "you", "your", "our", "will", "shall",
    "may", "must", "within", "after", "before", "and", "or", "in", "on", "it",
    "that", "this", "says", "say", "policy", "document", "elsewhere", "later",
})


def _duration_context(text: str, start: int, window: int = 60) -> str:
    """The obligation a period attaches to: the last meaningful words before it."""
    prefix = text[max(0, start - window):start]
    words = [w.lower() for w in _WORD_RE.findall(prefix)]
    meaningful = [w for w in words if w not in _DURATION_STOPWORDS]
    return " ".join(meaningful[-2:])


def check_internal_consistency(draft: str) -> List[Finding]:
    """Find clauses that contradict each other inside one document."""
    findings: List[Finding] = []
    seen: Dict[Tuple[str, str, str], bool] = {}
    for m in _CLAUSE_RE.finditer(draft or ""):
        key = (m.group("subject").strip().lower(),
               m.group("modal").lower(),
               m.group("verb").lower())
        negated = bool(m.group("neg"))
        if key in seen and seen[key] != negated:
            findings.append(Finding(
                "internal_consistency", "error",
                f"contradicting clauses: '{key[0]} {key[1]} {key[2]}' is stated both "
                f"affirmatively and negatively",
                {"subject": key[0], "modal": key[1], "verb": key[2]}))
        else:
            seen.setdefault(key, negated)

    text = draft or ""
    durations: Dict[str, set] = {}
    for m in _DURATION_RE.finditer(text):
        head = _duration_context(text, m.start())
        if not head:
            continue
        unit = m.group("unit").lower()
        durations.setdefault(f"{head}|{unit}", set()).add(int(m.group("num")))
    for key, values in durations.items():
        if len(values) > 1:
            head, unit = key.split("|", 1)
            findings.append(Finding(
                "internal_consistency", "error",
                f"conflicting periods for '{head}': {sorted(values)} {unit}(s)",
                {"context": head, "unit": unit, "values": sorted(values)}))
    return findings


_DEFINITION_RE = re.compile(r'["“](?P<term>[A-Z][\w \-]{1,40})["”]\s+(?:means|shall mean|refers to)',
                            re.IGNORECASE)
#: A capitalised multi-word noun phrase mid-sentence is how legal drafting signals
#: "this is a defined term". Sentence-initial words are excluded — they are
#: capitalised for grammar, not for definition.
_TERM_USE_RE = re.compile(r"(?<![.!?]\s)(?<!^)\b(?P<term>[A-Z][a-z]+(?: [A-Z][a-z]+)*)\b",
                          re.MULTILINE)

#: Capitalised words that are never defined terms, so flagging them is pure noise.
_TERM_STOPWORDS = frozenset({
    "We", "You", "Your", "Our", "The", "This", "These", "If", "It", "In", "As",
    "By", "For", "To", "And", "Or", "But", "No", "Any", "All", "Please", "Note",
    "United States", "European Union", "California", "Canada", "Brazil", "Japan",
})


def check_defined_terms(draft: str) -> List[Finding]:
    """Defined terms must be used; capitalised term-shaped phrases must be defined."""
    findings: List[Finding] = []
    text = draft or ""
    defined = {m.group("term").strip() for m in _DEFINITION_RE.finditer(text)}
    body = _DEFINITION_RE.sub(" ", text)

    for term in sorted(defined):
        if not re.search(r"\b" + re.escape(term) + r"\b", body):
            findings.append(Finding(
                "defined_terms", "warning",
                f"defined term '{term}' is never used", {"term": term}))

    used = {m.group("term").strip() for m in _TERM_USE_RE.finditer(body)}
    for term in sorted(used):
        if term in _TERM_STOPWORDS or term in defined:
            continue
        if " " not in term:
            continue  # single capitalised words are too noisy to flag
        findings.append(Finding(
            "defined_terms", "warning",
            f"'{term}' is used like a defined term but is never defined",
            {"term": term}))
    return findings


def check_jurisdiction_coverage(draft: str,
                                required_jurisdictions: Iterable[str] = ()) -> List[Finding]:
    """Every market the app ships in must be addressed by the document."""
    findings: List[Finding] = []
    text = (draft or "").lower()
    for jurisdiction in required_jurisdictions or ():
        if not isinstance(jurisdiction, str) or not jurisdiction.strip():
            continue
        name = jurisdiction.strip()
        if name.lower() not in text:
            findings.append(Finding(
                "jurisdiction_coverage", "error",
                f"required jurisdiction '{name}' is not addressed",
                {"jurisdiction": name}))
    return findings


def check_readability(draft: str, ceiling: Optional[float] = None) -> List[Finding]:
    ceiling = READABILITY_CEILING if ceiling is None else ceiling
    grade = readability_grade(draft)
    if grade > ceiling:
        return [Finding("readability", "warning",
                        f"reading grade {grade} exceeds ceiling {ceiling}",
                        {"grade": grade, "ceiling": ceiling})]
    return []


def check_competitor_similarity(draft: str,
                                competitor_snapshots: Iterable[Any] = (),
                                ceiling: Optional[float] = None) -> List[Finding]:
    """STRICT ceiling. Above it the draft is rejected, not warned about.

    `competitor_snapshots` may be plain strings or mappings with a `text` key and an
    optional `source` — that shape IS the corpus contract, so a store can be wired in
    later without touching this module.
    """
    ceiling = SIMILARITY_CEILING if ceiling is None else ceiling
    findings: List[Finding] = []
    for snapshot in competitor_snapshots or ():
        if isinstance(snapshot, dict):
            text, source = snapshot.get("text", ""), snapshot.get("source", "unknown")
        else:
            text, source = snapshot, "unknown"
        if not isinstance(text, str) or not text.strip():
            continue
        score = similarity(draft or "", text)
        if score > ceiling:
            findings.append(Finding(
                "competitor_similarity", "error",
                f"draft is {score:.0%} similar to competitor document '{source}', "
                f"above the {ceiling:.0%} ceiling",
                {"source": source, "similarity": score, "ceiling": ceiling}))
    return findings


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def verify(draft: Any,
           required_jurisdictions: Iterable[str] = (),
           competitor_snapshots: Iterable[Any] = (),
           similarity_ceiling: Optional[float] = None,
           readability_ceiling: Optional[float] = None) -> VerifyResult:
    """Run every check and decide whether the draft may go forward.

    Fail-soft: never raises. An unusable draft is a REJECTION with a reason, because
    a gate that throws is a gate that gets wrapped in a bare except and disabled.
    """
    if not isinstance(draft, str) or not draft.strip():
        return VerifyResult(False, [Finding(
            "internal_consistency", "error", "draft is empty or not text")],
            {"words": 0})

    findings: List[Finding] = []
    try:
        findings.extend(check_internal_consistency(draft))
        findings.extend(check_defined_terms(draft))
        findings.extend(check_jurisdiction_coverage(draft, required_jurisdictions))
        findings.extend(check_readability(draft, readability_ceiling))
        findings.extend(check_competitor_similarity(
            draft, competitor_snapshots, similarity_ceiling))
    except Exception as e:  # pragma: no cover - defensive
        return VerifyResult(False, [Finding(
            "internal_consistency", "error", f"verification failed: {e}")], {})

    ceiling = SIMILARITY_CEILING if similarity_ceiling is None else similarity_ceiling
    scores = []
    for snapshot in competitor_snapshots or ():
        text = snapshot.get("text", "") if isinstance(snapshot, dict) else snapshot
        if isinstance(text, str) and text.strip():
            scores.append(similarity(draft, text))
    metrics = {
        "words": len(_words(draft)),
        "readability_grade": readability_grade(draft),
        "max_competitor_similarity": max(scores) if scores else 0.0,
        "similarity_ceiling": ceiling,
    }
    ok = not any(f.severity == "error" for f in findings)
    return VerifyResult(ok, findings, metrics)
