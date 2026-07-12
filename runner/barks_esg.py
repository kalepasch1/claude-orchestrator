"""SB4 ESG targeting engine.

Extracts commitment claims from ESG/sustainability text and produces
outreach drafts with truth-gated source spans.
"""

from __future__ import annotations

import re

from barks_contracts import Claim, OutreachDraft, Result

# Patterns that signal a corporate commitment / pledge.
_COMMIT_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"we commit to\b",
        r"we pledge\b",
        r"our goal is\b",
        r"we aim to\b",
        r"we will\b",
        r"committed to\b",
        r"dedicated to\b",
    ]
]

# Sentence-ending punctuation (or end-of-string).
_SENTENCE_END = re.compile(r"[.!?\n]")


def _sentence_containing(text: str, match_start: int) -> tuple[int, int]:
    """Return (start, end) offsets of the sentence that contains *match_start*."""
    # Walk backward to find sentence start.
    start = 0
    for i in range(match_start - 1, -1, -1):
        if text[i] in ".!?\n":
            start = i + 1
            break
    # Strip leading whitespace from start.
    while start < len(text) and text[start] in " \t\r":
        start += 1

    # Walk forward to find sentence end.
    m = _SENTENCE_END.search(text, match_start)
    if m:
        end = m.end()
    else:
        end = len(text)
    # Strip trailing whitespace.
    while end > start and text[end - 1] in " \t\r":
        end -= 1
    return (start, end)


class EsgTargetingEngine:
    """Extract commitment claims from ESG text and build outreach drafts."""

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    def extract_claims(self, text: str) -> list[Claim]:
        """Return a list of *Claim* objects found in *text*.

        Each claim's ``source_span`` gives ``(start, end)`` byte offsets
        such that ``text[start:end]`` reproduces the claim text exactly.
        """
        if not text:
            return []

        seen_spans: set[tuple[int, int]] = set()
        claims: list[Claim] = []

        for pat in _COMMIT_PATTERNS:
            for m in pat.finditer(text):
                span = _sentence_containing(text, m.start())
                if span in seen_spans:
                    continue
                seen_spans.add(span)
                claim_text = text[span[0] : span[1]]
                claims.append(Claim(text=claim_text, source_span=span))

        # Sort by appearance order.
        claims.sort(key=lambda c: c.source_span[0])
        return claims

    # ------------------------------------------------------------------
    def generate_draft(self, text: str) -> Result:
        """Generate an *OutreachDraft* from raw ESG text.

        **Truth gate**: only claims whose ``source_span`` text matches are
        kept.  Fail-soft on empty / None input.
        """
        if not text:
            return Result(ok=True, data=OutreachDraft(claims=[], body=""))

        try:
            raw_claims = self.extract_claims(text)
        except Exception as exc:  # noqa: BLE001
            return Result(ok=False, error=str(exc))

        # Truth gate – keep only claims whose span text matches.
        verified: list[Claim] = []
        for c in raw_claims:
            start, end = c.source_span
            if 0 <= start < end <= len(text) and text[start:end] == c.text:
                verified.append(c)

        body_lines = [f"- {c.text}" for c in verified]
        body = "\n".join(body_lines) if body_lines else ""
        draft = OutreachDraft(claims=verified, body=body)
        return Result(ok=True, data=draft)
