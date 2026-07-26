"""Real-time legal/compliance/regulatory monitoring for all code changes.

Scans every diff produced by swarm_executor for patterns that indicate
legal or compliance risk. Integrates with the discovery bus to broadcast
compliance findings to all concurrent tasks, and with the hivemind to
propagate compliance patterns across projects.

Risk categories cover: PII exposure, auth changes, payment logic,
data retention, third-party SDKs, license violations, accessibility,
GDPR, HIPAA, SOX, encryption, API security, data residency, consent
flows, and audit trail requirements.
"""

import re
import logging
import os
import time
from typing import List, Dict, Tuple, Any, Optional

log = logging.getLogger(__name__)

try:
    import db
except ImportError:
    db = None


# --- Risk detection patterns ---

RISK_SIGNALS = {
    "pii_exposure": {
        "patterns": [
            r'(?:email|phone|ssn|social.?security|date.?of.?birth|address|passport)',
            r'(?:console\.log|print|logger\.\w+)\s*\(.*(?:user|customer|patient|email|phone)',
            r'(?:localStorage|sessionStorage)\.setItem\(.*(?:user|token|session)',
        ],
        "severity_default": "high",
        "description": "Potential PII exposure in logs, storage, or public surfaces",
    },
    "auth_change": {
        "patterns": [
            r'(?:supabase\.auth|createClient|signIn|signUp|signOut|resetPassword)',
            r'(?:jwt|bearer|oauth|session|cookie|token).*(?:=|:)',
            r'(?:middleware|guard|protect|requireAuth|withAuth)',
            r'(?:row.?level.?security|RLS|policy\s)',
        ],
        "severity_default": "medium",
        "description": "Authentication or authorization logic changed",
    },
    "payment_change": {
        "patterns": [
            r'(?:stripe|payment|billing|invoice|subscription|checkout|price|plan)',
            r'(?:charge|refund|credit|debit|transaction|ledger|settlement)',
            r'(?:webhook.*(?:payment|invoice|subscription))',
        ],
        "severity_default": "high",
        "description": "Payment, billing, or financial logic changed",
    },
    "data_retention": {
        "patterns": [
            r'(?:delete|drop|truncate|purge|archive|retain|expire|ttl)',
            r'(?:cron|scheduled|periodic).*(?:delete|clean|purge)',
            r'(?:soft.?delete|hard.?delete|cascade)',
        ],
        "severity_default": "medium",
        "description": "Data retention or deletion logic changed",
    },
    "third_party_sdk": {
        "patterns": [
            r'(?:npm install|pip install|import|require).*(?:analytics|tracking|pixel)',
            r'(?:google.?analytics|segment|mixpanel|amplitude|hotjar|intercom|crisp)',
            r'(?:facebook|meta|tiktok|twitter|x\.com).*(?:pixel|sdk|api)',
        ],
        "severity_default": "medium",
        "description": "Third-party SDK or tracking code added",
    },
    "license_violation": {
        "patterns": [
            r'(?:GPL|AGPL|SSPL|EUPL|copyleft)',
            r'(?:license|licence|copyright).*(?:all rights reserved)',
        ],
        "severity_default": "high",
        "description": "Potential license or copyright issue",
    },
    "accessibility": {
        "patterns": [
            r'(?:aria-|role=|tabindex|alt=|sr-only|screen.?reader)',
            r'(?:focus.?trap|keyboard.?nav|skip.?link)',
        ],
        "severity_default": "info",
        "description": "Accessibility attribute changed",
    },
    "gdpr": {
        "patterns": [
            r'(?:consent|cookie.?banner|data.?processing|right.?to.?delete)',
            r'(?:data.?export|portability|erasure|rectification)',
            r'(?:lawful.?basis|legitimate.?interest|explicit.?consent)',
        ],
        "severity_default": "high",
        "description": "GDPR-relevant data processing logic changed",
    },
    "encryption": {
        "patterns": [
            r'(?:encrypt|decrypt|hash|bcrypt|argon|scrypt|pbkdf|aes|rsa)',
            r'(?:crypto|cipher|hmac|digest|salt)',
            r'(?:https?://|ws://|ftp://)',
        ],
        "severity_default": "medium",
        "description": "Encryption or security primitive changed",
    },
    "api_security": {
        "patterns": [
            r'(?:cors|origin|allow-origin|access-control)',
            r'(?:rate.?limit|throttle|quota)',
            r'(?:api.?key|x-api-key|authorization)',
            r'(?:public|unprotected|unauthenticated).*(?:endpoint|route|api)',
        ],
        "severity_default": "medium",
        "description": "API security configuration changed",
    },
    "data_residency": {
        "patterns": [
            r'(?:region|zone|eu-west|us-east|ap-south|data.?center)',
            r'(?:cross.?border|transfer|residency|sovereignty)',
        ],
        "severity_default": "high",
        "description": "Data residency or cross-border transfer implications",
    },
    "consent_flow": {
        "patterns": [
            r'(?:opt.?in|opt.?out|consent|agree|terms|privacy.?policy)',
            r'(?:unsubscribe|preferences|marketing|notification.?settings)',
        ],
        "severity_default": "medium",
        "description": "User consent or preference flow changed",
    },
    "audit_trail": {
        "patterns": [
            r'(?:audit|log|trail|history|changelog|event.?sourcing)',
            r'(?:created_by|updated_by|deleted_by|modified_by)',
        ],
        "severity_default": "info",
        "description": "Audit trail or logging logic changed",
    },
}

# Compile all patterns
_COMPILED_SIGNALS = {}
for category, config in RISK_SIGNALS.items():
    _COMPILED_SIGNALS[category] = {
        "regexes": [re.compile(p, re.I | re.M) for p in config["patterns"]],
        "severity_default": config["severity_default"],
        "description": config["description"],
    }

# Severity escalation rules
ESCALATION_RULES = {
    "critical": {"auto_escalate": True, "block_merge": True, "notify": ["operator"]},
    "high": {"auto_escalate": False, "block_merge": False, "notify": ["operator"]},
    "medium": {"auto_escalate": False, "block_merge": False, "notify": []},
    "low": {"auto_escalate": False, "block_merge": False, "notify": []},
    "info": {"auto_escalate": False, "block_merge": False, "notify": []},
}

# Context patterns that escalate severity
_SEVERITY_ESCALATORS = [
    (re.compile(r'(?:production|prod|live|customer)', re.I), 1),  # +1 severity level
    (re.compile(r'(?:health|medical|patient|hipaa)', re.I), 2),   # +2 severity levels
    (re.compile(r'(?:financial|banking|sox|pci)', re.I), 2),
    (re.compile(r'(?:children|minor|coppa|age)', re.I), 2),
]

_SEVERITY_ORDER = ["info", "low", "medium", "high", "critical"]


def _escalate_severity(base_severity: str, diff_text: str) -> str:
    """Escalate severity based on contextual signals in the diff."""
    idx = _SEVERITY_ORDER.index(base_severity)
    for pattern, escalation in _SEVERITY_ESCALATORS:
        if pattern.search(diff_text):
            idx = min(idx + escalation, len(_SEVERITY_ORDER) - 1)
    return _SEVERITY_ORDER[idx]


def scan_diff(diff_text: str, project_id: str, dag_id: Optional[str] = None,
              task_slug: Optional[str] = None) -> List[Dict[str, Any]]:
    """Scan a diff for compliance risks. Returns list of ComplianceEvent dicts.

    Args:
        diff_text: Unified diff text
        project_id: Project identifier
        dag_id: DAG identifier (optional)
        task_slug: Task slug (optional)

    Returns:
        List of compliance event dicts
    """
    if not diff_text:
        return []

    events = []
    # Only scan added lines (lines starting with +, not +++)
    added_lines = "\n".join(
        line[1:] for line in diff_text.split("\n")
        if line.startswith("+") and not line.startswith("+++")
    )
    if not added_lines:
        return []

    for category, config in _COMPILED_SIGNALS.items():
        matches = []
        for regex in config["regexes"]:
            for match in regex.finditer(added_lines):
                matches.append(match.group(0))

        if matches:
            severity = _escalate_severity(config["severity_default"], diff_text)
            # Extract file path from diff header
            file_match = re.search(r'^\+\+\+ b/(.+)$', diff_text, re.M)
            file_path = file_match.group(1) if file_match else None

            event = {
                "project_id": project_id,
                "dag_id": dag_id,
                "task_slug": task_slug,
                "risk_category": category,
                "severity": severity,
                "summary": f"{config['description']}. Signals: {', '.join(matches[:5])}",
                "file_path": file_path,
                "diff_excerpt": added_lines[:500],
                "auto_resolved": False,
                "escalated": ESCALATION_RULES[severity]["auto_escalate"],
                "escalated_to": "operator" if ESCALATION_RULES[severity]["auto_escalate"] else None,
            }
            events.append(event)

    return events


def record_events(events: List[Dict[str, Any]]) -> int:
    """Store compliance events in the database.

    Args:
        events: List of compliance event dicts

    Returns:
        Number of events recorded
    """
    if not db or not events:
        return 0
    recorded = 0
    for event in events:
        try:
            db.insert("compliance_events", event)
            recorded += 1
        except Exception as e:
            log.error("compliance_events insert failed: %s", e)
    return recorded


def broadcast_to_bus(events: List[Dict[str, Any]], bus: Any) -> None:
    """Publish compliance events to the discovery bus so concurrent tasks see them.

    Args:
        events: List of compliance events
        bus: SharedDiscoveryBus instance (or None to skip)
    """
    if not bus:
        return
    for event in events:
        if event["severity"] in ("high", "critical"):
            bus.publish({
                "slug": event.get("task_slug", "compliance-monitor"),
                "kind": "compliance_risk",
                "summary": f"⚠️ {event['severity'].upper()} compliance risk: {event['summary']}",
                "tags": ["compliance", event["risk_category"], event["severity"]],
                "content": event.get("diff_excerpt", ""),
                "file_path": event.get("file_path"),
                "confidence": 1.0,
                "ts": time.time(),
            })


def check_merge_block(events: List[Dict[str, Any]]) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Check if any events should block merging.

    Args:
        events: List of compliance events

    Returns:
        Tuple of (should_block: bool, blocking_event_or_none: dict)
    """
    for event in events:
        if ESCALATION_RULES.get(event["severity"], {}).get("block_merge"):
            return True, event
    return False, None


def unacknowledged_risks(project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get unacknowledged high/critical risks.

    Args:
        project_id: Filter by project (optional)

    Returns:
        List of unacknowledged high/critical risk events
    """
    if not db:
        return []
    filters = {"acknowledged": False, "severity": {"in": ["high", "critical"]}}
    if project_id:
        filters["project_id"] = project_id
    try:
        return db.select("compliance_events", filters, order="created_at.desc", limit=50) or []
    except Exception as e:
        log.error("unacknowledged_risks query failed: %s", e)
        return []


def acknowledge(event_id: str, by: str = "operator") -> bool:
    """Acknowledge a compliance event.

    Args:
        event_id: UUID of event to acknowledge
        by: Who acknowledged it

    Returns:
        True if successful
    """
    if not db:
        return False
    try:
        db.update("compliance_events", event_id, {
            "acknowledged": True,
            "acknowledged_by": by,
        })
        return True
    except Exception as e:
        log.error("acknowledge failed: %s", e)
        return False


def stats(project_id: Optional[str] = None) -> Dict[str, Any]:
    """Compliance summary for dashboards.

    Args:
        project_id: Filter by project (optional)

    Returns:
        Dict with compliance statistics
    """
    if not db:
        return {}
    try:
        filters = {}
        if project_id:
            filters["project_id"] = project_id
        total = db.count("compliance_events", filters) or 0
        unacked = len(unacknowledged_risks(project_id))
        return {
            "total_events": total,
            "unacknowledged_high_critical": unacked,
        }
    except Exception as e:
        log.error("stats failed: %s", e)
        return {}
