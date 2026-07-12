"""
cftc_event_contract.py — CFTC event-contract authority bot spec.

Authority bot for prediction markets / derivatives regulatory analysis.
Corpus covers CEA, 17 CFR Part 40, CFTC event-contract orders,
no-action letters, and enforcement actions.
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bot_factory import BotSpec

SPEC = BotSpec(
    id="cftc-event-contract-authority",
    role="authority",
    target_app="apparently",
    corpus_filter={
        "source": ["CFTC", "CEA", "CFR-17"],
        "doc_types": ["order", "no_action", "rule", "enforcement"],
    },
    priors_tag="cftc_dmo_reviewer",
    competence={
        "event_contracts": 0.95,
        "derivatives_regulation": 0.90,
        "prediction_markets": 0.90,
        "cea_compliance": 0.85,
    },
    authority=0.9,
    reliability=0.85,
    eval_set=[
        {"issue": {"q": "Does a binary contract on the outcome of an NFL game qualify as gaming under CEA §40.11(a)?", "context": "CFTC special rule for event contracts involving gaming activity"}, "expected": "prohibited"},
        {"issue": {"q": "Can a DCM list an event contract on whether a specific hurricane will make landfall?", "context": "CFTC event contract policy on natural disaster contracts"}, "expected": "permitted_with_conditions"},
        {"issue": {"q": "Is a binary contract on a congressional election outcome listable under §40.11?", "context": "CFTC prohibition on contracts involving unlawful activity under state law"}, "expected": "prohibited"},
        {"issue": {"q": "Does a commodity price binary option require Part 40 certification or approval?", "context": "Standard commodity derivative listing requirements"}, "expected": "certification_required"},
        {"issue": {"q": "Can an event contract be designed to avoid manipulation susceptibility per §40.11(c)?", "context": "CFTC manipulation-susceptibility analysis for event contracts"}, "expected": "design_review_required"},
        {"issue": {"q": "Must a DCM demonstrate economic purpose for a weather event contract?", "context": "CFTC economic purpose test under CEA §5c(c)(5)(C)"}, "expected": "economic_purpose_required"},
    ],
)
