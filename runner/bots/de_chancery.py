"""
de_chancery.py — Delaware Court of Chancery recipient-alignment bot spec.

Reviewer bot that anticipates the questions the Court of Chancery would
raise — RFI-anticipation recall. This is the LEARNED version of the
seeded de_chancery recipient persona; the persona-learner cron feeds it.
Corpus covers Delaware Court of Chancery opinions.
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bot_factory import BotSpec

SPEC = BotSpec(
    id="de-chancery-recipient",
    role="reviewer",
    target_app="apparently",
    corpus_filter={
        "source": ["DE_Chancery"],
        "doc_types": ["opinion", "memorandum_opinion", "bench_ruling", "letter_opinion"],
    },
    priors_tag="de_chancery",
    competence={
        "fiduciary_duty_analysis": 0.95,
        "entire_fairness_review": 0.90,
        "appraisal_proceedings": 0.85,
        "books_and_records": 0.85,
        "rfi_anticipation": 0.90,
    },
    authority=0.80,
    reliability=0.85,
    eval_set=[
        {"issue": {"q": "In a squeeze-out merger at 85% of DCF value, would the Court apply entire fairness or business judgment review?", "context": "Controlling stockholder merger — standard of review"}, "expected": "entire_fairness"},
        {"issue": {"q": "Does a special committee's approval of a conflicted transaction cleanse the conflict if the committee lacked independent advisors?", "context": "MFW framework — procedural protections"}, "expected": "not_cleansed"},
        {"issue": {"q": "Can a stockholder demand books and records under §220 without stating a proper purpose?", "context": "Books and records inspection — proper purpose requirement"}, "expected": "proper_purpose_required"},
        {"issue": {"q": "Would the Court question whether a board's rushed 48-hour sale process satisfied Revlon duties?", "context": "Sale of control — Revlon enhanced scrutiny"}, "expected": "revlon_scrutiny_applies"},
        {"issue": {"q": "In an appraisal proceeding, would the Court accept a deal-price-minus-synergies valuation without further inquiry?", "context": "Appraisal — fair value determination"}, "expected": "further_inquiry_needed"},
        {"issue": {"q": "Does an exculpatory charter provision under §102(b)(7) protect directors from a duty of loyalty claim?", "context": "Director liability — exculpation scope"}, "expected": "loyalty_not_exculpated"},
    ],
)
