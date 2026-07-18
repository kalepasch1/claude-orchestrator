"""
adversarial_regulator.py — Skeptical regulator adversary bot spec.

Adversary bot for anticipating enforcement actions, deficiency notices,
and regulatory objections. Corpus covers CFTC/SEC/FinCEN enforcement
actions, cease-and-desists, deficiency letters, and regulatory denials.
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bot_factory import BotSpec

SPEC = BotSpec(
    id="skeptical-regulator-adversary",
    role="adversary",
    target_app="apparently",
    corpus_filter={
        "source": ["CFTC", "SEC", "FinCEN", "OCC"],
        "doc_types": ["enforcement_action", "cease_and_desist", "deficiency_letter", "denial", "regulatory_objection"],
    },
    priors_tag="skeptical_regulator",
    competence={
        "enforcement_vulnerability": 0.95,
        "regulatory_objection_analysis": 0.92,
        "compliance_gap_detection": 0.90,
        "legal_risk_assessment": 0.88,
        "precedent_application": 0.85,
    },
    authority=0.70,
    reliability=0.88,
    eval_set=[
        {"issue": {"q": "A platform claims it is not a derivatives exchange because participants can exit contracts at any time. What enforcement precedent contradicts this reasoning?", "context": "CFTC enforcement — definition of exchange function"}, "expected": "enforcement_precedent_contradicts"},
        {"issue": {"q": "An applicant's compliance plan states all trades are 'transparent' but lacks specific procedures for market surveillance and manipulation detection. What deficiency would the regulator cite?", "context": "Regulatory deficiency — market surveillance gaps"}, "expected": "deficiency_citation_required"},
        {"issue": {"q": "A financial services firm was previously cited for AML/KYC violations 5 years ago and now seeks approval for a new product line. What scrutiny level applies?", "context": "Regulatory objection — prior enforcement history"}, "expected": "heightened_scrutiny"},
        {"issue": {"q": "An entity claims exemption from registration under a 'market development' prong, but comparable firms were denied the same exemption in recent enforcement actions. What is the likely regulator stance?", "context": "Cease-and-desist precedent — exemption denial"}, "expected": "exemption_likely_denied"},
        {"issue": {"q": "A trading system's rulebook prohibits 'naked' short-selling but contains no definition, audit trail, or enforcement mechanism. What gap would regulators identify?", "context": "Deficiency letter — rule enforcement capability"}, "expected": "enforcement_mechanism_missing"},
        {"issue": {"q": "An applicant's capital plan assumes a 5% market stress scenario but recent CFTC enforcement actions target firms assuming the same stress level. Should capital be higher?", "context": "Enforcement vulnerability — capital adequacy"}, "expected": "capital_increase_required"},
    ],
)
