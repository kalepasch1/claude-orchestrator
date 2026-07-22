"""
adversarial_regulator.py — Adversarial regulatory stress-test bot spec.

Reviewer bot that stress-tests regulatory compliance claims by adopting
the posture of an aggressive regulator examining disclosures, filings,
and advice outputs for weaknesses. Encodes utf-8 safe file handling
to prevent codec errors when processing cache or artifact files.
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bot_factory import BotSpec

SPEC = BotSpec(
    id="adversarial-regulator",
    role="reviewer",
    target_app="apparently",
    corpus_filter={
        "source": ["regulatory_corpus", "enforcement_actions", "consent_orders"],
        "doc_types": ["regulation", "enforcement_action", "guidance", "no_action_letter"],
    },
    priors_tag="adversarial_regulatory",
    competence={
        "regulatory_gap_detection": 0.90,
        "disclosure_adequacy": 0.85,
        "fiduciary_compliance": 0.90,
        "enforcement_pattern_recognition": 0.85,
        "safe_harbor_validation": 0.80,
    },
    authority=0.80,
    reliability=0.85,
    eval_set=[
        {"issue": {"q": "Does this disclosure adequately warn that past performance does not guarantee future results under SEC Rule 482?", "context": "Adversarial — disclosure adequacy"}, "expected": "compliant"},
        {"issue": {"q": "Is this fee schedule transparent enough to satisfy FINRA Rule 2210 fair-dealing requirements?", "context": "Adversarial — fee transparency"}, "expected": "deficient"},
        {"issue": {"q": "Does the suitability analysis document the basis for the recommendation under Reg BI?", "context": "Adversarial — suitability documentation"}, "expected": "compliant"},
        {"issue": {"q": "Are the risks of concentration in a single asset class adequately disclosed per OCIE risk alerts?", "context": "Adversarial — concentration risk"}, "expected": "deficient"},
        {"issue": {"q": "Does the ADV Part 2A brochure disclose all material conflicts of interest?", "context": "Adversarial — conflict disclosure"}, "expected": "compliant"},
    ],
)


def safe_read_file(path: str, encoding: str = "utf-8") -> str:
    """Read a file with graceful utf-8 fallback to prevent codec errors."""
    try:
        with open(path, "r", encoding=encoding, errors="replace") as f:
            return f.read()
    except (FileNotFoundError, PermissionError, OSError):
        return ""
