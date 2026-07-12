"""
state_gaming_licensing.py — State gaming licensing discipline bot spec.

Discipline bot for gaming regulatory compliance across NV/NJ/PA/MI.
Corpus covers state gaming statutes, regulations, AG opinions,
and licensing deficiency letters.
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bot_factory import BotSpec

SPEC = BotSpec(
    id="state-gaming-licensing-analyst",
    role="discipline",
    target_app="apparently",
    corpus_filter={
        "source": ["NV-GCB", "NJ-DGE", "PA-PGCB", "MI-MGCB"],
        "doc_types": ["statute", "regulation", "ag_opinion", "deficiency_letter", "advisory"],
    },
    priors_tag="nv_gcb_agent",
    competence={
        "skill_vs_chance": 0.90,
        "key_suitability": 0.90,
        "source_of_funds": 0.85,
        "responsible_gaming": 0.85,
        "mics_compliance": 0.80,
    },
    authority=0.75,
    reliability=0.85,
    eval_set=[
        {"issue": {"q": "Does a daily fantasy sports contest where lineup selection drives outcomes qualify as skill-predominant under NV predominant-purpose test?", "context": "State gaming licensing — skill vs chance analysis"}, "expected": "skill_predominant"},
        {"issue": {"q": "Must a principal applicant for a NJ casino license disclose all sources of funding for the acquisition?", "context": "Key suitability assessment — source of funds"}, "expected": "disclosure_required"},
        {"issue": {"q": "Can a gaming licensee in PA operate without a responsible gaming plan filed with the PGCB?", "context": "Responsible gaming compliance"}, "expected": "plan_required"},
        {"issue": {"q": "Is an interactive gaming operator in MI required to implement MICS for electronic table games?", "context": "Minimum internal control standards"}, "expected": "mics_required"},
        {"issue": {"q": "Does a slot machine route operator in NV need a separate key employee license for each location manager?", "context": "Key suitability — licensing scope"}, "expected": "key_license_required"},
        {"issue": {"q": "Can an applicant with a prior felony conviction obtain a NJ gaming license without a waiver?", "context": "Suitability disqualification"}, "expected": "waiver_required"},
    ],
)
