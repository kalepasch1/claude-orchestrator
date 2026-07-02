#!/usr/bin/env python3
"""
committees.py - TAILORED STANDING ADVISORY BOARDS PER APP. Each application type
gets domain-specific reviewers: fintech apps get Regulatory (by jurisdiction) + Compliance;
consumer apps get Brand + UX; APIs get Performance + Security. Ensures reviews consider
the right trade-offs for each domain instead of one-size-fits-all gate.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


APP_COMMITTEES = {
    # Fintech/payments apps: regulatory scrutiny + compliance-first mindset
    "fintech": [
        {"seat": "Regulatory", "expertise": "jurisdiction-aware legal compliance", "veto": True},
        {"seat": "Compliance", "expertise": "AML/KYC/sanctions screening", "veto": False},
        {"seat": "Security", "expertise": "PCI/data residency/encryption", "veto": True},
        {"seat": "Finance", "expertise": "settlement/reconciliation/audit trail", "veto": False},
    ],
    # B2C consumer products: brand risk + user safety + privacy
    "consumer": [
        {"seat": "Brand", "expertise": "brand voice/tone/reputation risk", "veto": False},
        {"seat": "Privacy", "expertise": "GDPR/CCPA/data minimization", "veto": True},
        {"seat": "Trust", "expertise": "abuse/safety/fraud", "veto": True},
        {"seat": "UX", "expertise": "user flow/accessibility/change risk", "veto": False},
    ],
    # B2B SaaS: performance/reliability + integration stability
    "saas": [
        {"seat": "Performance", "expertise": "latency/throughput/scale", "veto": False},
        {"seat": "Reliability", "expertise": "uptime/failover/observability", "veto": True},
        {"seat": "Integration", "expertise": "API contracts/backward-compat", "veto": True},
        {"seat": "Security", "expertise": "auth/secrets/RBAC", "veto": True},
    ],
    # Infrastructure/platform: stability + multi-tenant isolation
    "platform": [
        {"seat": "Stability", "expertise": "blast radius/rollback/canary", "veto": True},
        {"seat": "Isolation", "expertise": "multi-tenancy/resource quotas", "veto": True},
        {"seat": "Observability", "expertise": "tracing/metrics/logs", "veto": False},
        {"seat": "Security", "expertise": "privilege escalation/audit", "veto": True},
    ],
    # Open-source: community/contribution/sustainability
    "opensource": [
        {"seat": "Community", "expertise": "contributor/maintainer impact", "veto": False},
        {"seat": "Sustainability", "expertise": "maintenance burden/debt", "veto": False},
        {"seat": "API", "expertise": "public API stability/docs", "veto": True},
        {"seat": "License", "expertise": "license/patent/compliance", "veto": True},
    ],
    # Default fallback: general purpose
    "default": [
        {"seat": "Code", "expertise": "correctness/test coverage", "veto": False},
        {"seat": "Security", "expertise": "OWASP/secrets/injection", "veto": True},
        {"seat": "Performance", "expertise": "efficiency/scale", "veto": False},
    ],
}


def for_app(app_name_or_id, db_project=None):
    """
    Return the advisory board (list of committee members) for an app.
    Fetches app type from DB if db_project is a project dict, or infers from app_name.
    """
    # Determine the app type: either from db_project["type"] or by pattern matching
    app_type = None
    if db_project and isinstance(db_project, dict):
        app_type = db_project.get("type", "").lower()

    if not app_type:
        # Pattern-match app name to infer type
        name_lower = (app_name_or_id or "").lower()
        if any(w in name_lower for w in ["pay", "bank", "settle", "crypto", "fintech", "wallet", "stripe", "square"]):
            app_type = "fintech"
        elif any(w in name_lower for w in ["consumer", "social", "web", "mobile", "user", "app", "instagram", "twitter", "facebook", "tiktok"]):
            app_type = "consumer"
        elif any(w in name_lower for w in ["saas", "service", "enterprise", "workspace", "notion", "slack"]):
            app_type = "saas"
        elif any(w in name_lower for w in ["platform", "kernel", "infra", "core", "kube", "docker", "runtime", "linux"]):
            app_type = "platform"
        elif any(w in name_lower for w in ["opensource", "open-source", "oss", "tensorflow"]):
            app_type = "opensource"

    if not app_type or app_type not in APP_COMMITTEES:
        app_type = "default"

    return APP_COMMITTEES[app_type]


def members_for_app(app_name_or_id, db_project=None):
    """Return a list of seat names on the committee for this app."""
    return [m["seat"] for m in for_app(app_name_or_id, db_project)]


def has_veto_seat(app_name_or_id, seat_name, db_project=None):
    """Return True if the given seat has veto power on this app's committee."""
    for m in for_app(app_name_or_id, db_project):
        if m["seat"] == seat_name:
            return m.get("veto", False)
    return False


def all_types():
    """Return list of all defined committee types."""
    return [k for k in APP_COMMITTEES.keys() if k != "default"]


if __name__ == "__main__":
    # Demo: show committees for each app type
    for app_type in all_types() + ["default"]:
        board = for_app(app_type)
        print(f"\n{app_type.upper()} app:")
        for m in board:
            veto_mark = " [VETO]" if m.get("veto") else ""
            print(f"  {m['seat']:15} {m['expertise']}{veto_mark}")
