"""
citation_auditor.py — Citation fidelity reviewer bot spec.

Reviewer bot that checks whether authorities are cited for propositions
they actually support. Mirrors apparently's citation-source-resolver.ts
and rlo_citation_corrections memory. Corpus covers the verified citation
library plus the self-growing citation-correction memory.
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bot_factory import BotSpec

SPEC = BotSpec(
    id="citation-fidelity-auditor",
    role="reviewer",
    target_app="apparently",
    corpus_filter={
        "source": ["verified_citation_library", "rlo_citation_corrections"],
        "doc_types": ["citation_record", "correction", "authority_opinion", "statute"],
    },
    priors_tag="citation_fidelity",
    competence={
        "citation_accuracy": 0.95,
        "authority_matching": 0.90,
        "proposition_support": 0.90,
        "mis_citation_detection": 0.85,
        "source_verification": 0.85,
    },
    authority=0.85,
    reliability=0.90,
    eval_set=[
        {"issue": {"q": "Is Chevron v. NRDC cited correctly for the proposition that courts must defer to agency interpretations of ambiguous statutes?", "context": "Citation fidelity — faithful citation check"}, "expected": "faithful"},
        {"issue": {"q": "Is Marbury v. Madison cited for the proposition that administrative agencies have inherent rulemaking power?", "context": "Citation fidelity — mis-citation detection"}, "expected": "mis_cited"},
        {"issue": {"q": "Is SEC v. Howey cited for the four-prong investment contract test?", "context": "Citation fidelity — faithful securities law citation"}, "expected": "faithful"},
        {"issue": {"q": "Is Roe v. Wade cited for the proposition that the Commerce Clause grants Congress unlimited regulatory power?", "context": "Citation fidelity — cross-domain mis-citation"}, "expected": "mis_cited"},
        {"issue": {"q": "Is Erie Railroad v. Tompkins cited for the proposition that federal courts sitting in diversity apply state substantive law?", "context": "Citation fidelity — faithful civil procedure citation"}, "expected": "faithful"},
        {"issue": {"q": "Is Brown v. Board of Education cited for the principle that separate educational facilities are inherently unequal?", "context": "Citation fidelity — faithful constitutional law citation"}, "expected": "faithful"},
        {"issue": {"q": "Is Citizens United v. FEC cited for the proposition that individual campaign contributions cannot be limited?", "context": "Citation fidelity — overbroad citation"}, "expected": "mis_cited"},
    ],
)
