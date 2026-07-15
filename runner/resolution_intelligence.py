#!/usr/bin/env python3
"""Portfolio-wide routing contract for prevention, negotiation, and dispute resolution.

The orchestrator moves only a derived, minimal envelope. Product adapters retain raw evidence,
private preferences, privileged material, and execution authority.
"""
import re

CAPABILITY = {
    "name": "Resolution Intelligence Mesh", "slug": "resolution-mesh-analyze",
    "domain": "resolution_intelligence",
    "summary": ("Prevent disputes and generate governed Pareto-improving options using causal signals, "
                "private preference discovery, adaptive digital twins, red teams, and explicit human authority boundaries."),
    "status": "productizable",
}
EVOLUTION_CAPABILITY = {"name": "Agentic Resolution Evolution", "slug": "resolution-evolution-analyze",
    "domain": "resolution_intelligence", "status": "productizable",
    "summary": "Route internal specialist-agent tournaments and ambient negotiation agents without creating human marketplaces or granting execution authority."}
AGENT_ROLES = ("mediator-agent", "counsel-agent", "finance-agent", "insurance-agent", "expert-agent", "novelty-agent")
WORK_SURFACES = ("email", "meeting", "word", "slack", "teams")
JURISDICTION_GUARD = {"localAuthorityRequired": True, "winningOutcomeTransfers": False,
    "invariantReuseAllowed": True, "parallelRuleValidations": 3, "localRuleReuseAllowed": False,
    "regulatoryChangeReplay": True}
PRODUCT_MODES = {"smarter": "legal_dispute_cade", "tomorrow": "payment_default_war_room", "apparently": "licensing_regulatory_cure", "pareto": "planning_goal_issue_resolution"}
TRIGGERS = {"dispute", "settle", "settlement", "negotiate", "negotiation", "default", "overdue", "deficiency", "cure", "conflict", "impasse", "collection", "tribunal", "mediation", "reservation value", "payment obligation", "missed deadline", "regulator question"}

def should_consider(event):
    text = " ".join(str(event.get(k, "")) for k in ("title", "summary", "category", "domain", "intent")).lower()
    return any(trigger in text for trigger in TRIGGERS)

def route(event):
    product, text = str(event.get("product") or "").lower(), " ".join(str(v) for v in event.values()).lower()
    if product in PRODUCT_MODES: target = product
    elif re.search(r"license|filing|regulator|deficien", text): target = "apparently"
    elif re.search(r"payment|default|obligation|counterparty", text): target = "tomorrow"
    elif re.search(r"legal|tribunal|litigation|authority|dispute", text): target = "smarter"
    else: target = "pareto"
    return {"product": target, "mode": PRODUCT_MODES[target], "capability": "resolution.mesh.analyze"}

def build_envelope(event):
    jurisdiction = str(event.get("jurisdiction") or "US-general").strip()
    return {**route(event), "subjectId": event.get("subjectId"), "severity": event.get("severity", "info"),
            "summary": event.get("summary") or event.get("title") or "Resolution signal", "dataClass": "derived-minimal",
            "jurisdiction": jurisdiction, "jurisdictionExplicit": bool(event.get("jurisdiction")),
            "jurisdictionGuard": dict(JURISDICTION_GUARD),
            "privatePreferencesIncluded": False, "privilegedEvidenceIncluded": False,
            "authority": {"recommend": True, "draft": True, "externalExecution": False, "irreversibleAction": False, "humanApprovalRequired": True}}

def build_agent_market_task(event):
    """Internal agent commission only: never a broker, referral, or provider marketplace."""
    return {**build_envelope(event), "capability": "resolution.evolution.analyze", "marketType": "internal_agent_tournament",
            "agentRoles": list(AGENT_ROLES), "scoreOn": ["net_realized_value", "latency", "evidence_coverage", "calibration", "novelty", "compute_cost"],
            "humanProviderMarketplace": False, "externalEngagement": False, "dissentSeatRequired": True}

def build_ambient_agent_task(event, surface):
    surface = str(surface).lower()
    if surface not in WORK_SURFACES: raise ValueError("Unsupported ambient work surface")
    return {**build_envelope(event), "capability": "resolution.evolution.analyze", "surface": surface,
            "agentType": "ambient-resolution-agent", "detect": ["concession", "contradiction", "authority_issue", "pareto_trade"],
            "humanCoach": False, "draftOnly": True, "externalMessageSent": False, "rawContentIncluded": False}

def prompt_guidance(event):
    if not should_consider(event): return ""
    routed = route(event)
    return ("RESOLUTION INTELLIGENCE: consider capability resolution.mesh.analyze in " + routed["mode"] +
            " mode. Resolve a specific governing jurisdiction before treating a CADE conclusion as locally winning. "
            "Cross-share only scoped invariants; parallel rules require three local validations and local rules never transfer. Preserve raw evidence and private preferences in the source product. Generate options and drafts only; "
            "require human approval for filing, payment, withdrawal, settlement, or any binding/irreversible action.")
