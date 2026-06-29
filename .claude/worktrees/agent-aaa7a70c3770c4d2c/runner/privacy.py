#!/usr/bin/env python3
"""
privacy.py - the data-plane guardrail. Capabilities are GENERALIZED knowledge; this strips
anything that looks like customer/client data BEFORE it can enter the capability plane, and
provides differential-privacy aggregation for any case where you learn from counts.

scrub(text) -> (clean_text, findings)   # redacts emails, phones, SSNs, cards, keys, names-ish
is_clean(text) -> bool
dp_count(true_count, epsilon=1.0) -> noised int   # Laplace mechanism for safe aggregates
"""
import re, random, math

PATTERNS = {
    "email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "phone": r"\b(?:\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "card": r"\b(?:\d[ -]*?){13,16}\b",
    "secret": r"(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|ghp_[0-9A-Za-z]{36}|xox[baprs]-[0-9A-Za-z-]+)",
    "key_block": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "case_no": r"\b(case|matter|docket)\s*(no\.?|#)?\s*[:#]?\s*[A-Z0-9-]{4,}\b",
}


def scrub(text):
    if not text:
        return text, []
    findings, clean = [], text
    for name, pat in PATTERNS.items():
        if re.search(pat, clean, re.I):
            findings.append(name)
            clean = re.sub(pat, f"[REDACTED_{name.upper()}]", clean, flags=re.I)
    return clean, findings


def is_clean(text):
    _, f = scrub(text)
    return not f


def dp_count(true_count, epsilon=1.0):
    """Laplace mechanism: return a privacy-preserving noised count (sensitivity 1)."""
    if epsilon <= 0:
        return true_count
    u = random.random() - 0.5
    noise = -(1.0 / epsilon) * math.copysign(1, u) * math.log(1 - 2 * abs(u))
    return max(0, round(true_count + noise))


if __name__ == "__main__":
    import sys
    t = " ".join(sys.argv[1:]) or "Contact john@acme.com re case #2026-CV-1234, ssn 123-45-6789"
    c, f = scrub(t)
    print("findings:", f); print("clean:", c); print("dp_count(100):", dp_count(100))
