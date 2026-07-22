"""Loop cadence coordinator — wires hourly / nightly / weekly schedules.

Ensures generator_feedback + queue_velocity run hourly in coordination,
self_review proposals auto-apply when blast-radius is low (nightly),
and meta_loop cross-deploys + template A/B rotation runs weekly.
"""

import time
import logging
from typing import Dict, List, Any, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cadence definitions
# ---------------------------------------------------------------------------

HOURLY_JOBS = ["generator_feedback", "queue_velocity"]
NIGHTLY_JOBS = ["self_review_auto_apply"]
WEEKLY_JOBS = ["meta_loop_cross_deploy", "prompt_distillation_refresh", "template_ab_rotation"]

CADENCE_TABLE: Dict[str, Dict[str, Any]] = {
    "generator_feedback": {
        "interval_seconds": 3600,
        "group": "hourly",
        "coordinated_with": "queue_velocity",
        "description": "Run generator feedback loop",
    },
    "queue_velocity": {
        "interval_seconds": 3600,
        "group": "hourly",
        "coordinated_with": "generator_feedback",
        "description": "Run queue velocity measurement",
    },
    "self_review_auto_apply": {
        "interval_seconds": 86400,
        "group": "nightly",
        "description": "Auto-apply low blast-radius self-review proposals",
    },
    "meta_loop_cross_deploy": {
        "interval_seconds": 604800,
        "group": "weekly",
        "description": "Cross-deploy best loop configs",
    },
    "prompt_distillation_refresh": {
        "interval_seconds": 604800,
        "group": "weekly",
        "description": "Recompute template-library stats via prompt_distillation.run()",
    },
    "template_ab_rotation": {
        "interval_seconds": 604800,
        "group": "weekly",
        "description": "Rotate 1 challenger template per task class at 10% traffic",
    },
}


# ---------------------------------------------------------------------------
# Blast-radius gate for auto-apply
# ---------------------------------------------------------------------------

# Categories that NEVER auto-merge (security surface)
NEVER_AUTO_APPLY = frozenset([
    "billing_guard",
    "kill_switch",
    "schema",
    "deploy",
    "security",
    "secret",
    "licensing",
    "registration",
    "custody",
    "transmission",
])


def score_blast_radius(proposal: Dict[str, Any]) -> float:
    """Score a proposal's blast radius from 0.0 (safe) to 1.0 (dangerous).

    Low blast-radius (< 0.3): config/prompt-template/cadence changes.
    High blast-radius (>= 0.3): schema/security/billing/deploy surface.
    """
    category = proposal.get("category", "").lower()
    affected_files = proposal.get("affected_files", [])
    change_type = proposal.get("change_type", "unknown")

    # Hard block on security-surface categories
    for blocked in NEVER_AUTO_APPLY:
        if blocked in category:
            return 1.0
        for f in affected_files:
            if blocked in f.lower():
                return 1.0

    # Score by change type
    scores = {
        "config": 0.1,
        "prompt_template": 0.15,
        "cadence": 0.1,
        "test": 0.05,
        "documentation": 0.05,
        "code": 0.5,
        "migration": 0.9,
    }
    base = scores.get(change_type, 0.5)

    # Scale by number of affected files
    file_count = len(affected_files)
    if file_count > 10:
        base = min(base + 0.3, 1.0)
    elif file_count > 5:
        base = min(base + 0.15, 1.0)

    return base


def is_auto_appliable(proposal: Dict[str, Any], threshold: float = 0.3) -> bool:
    """Return True if a proposal is safe to auto-apply."""
    return score_blast_radius(proposal) < threshold


# ---------------------------------------------------------------------------
# Auto-apply tier (nightly)
# ---------------------------------------------------------------------------

def partition_proposals(proposals: List[Dict[str, Any]]) -> tuple:
    """Split proposals into (auto_apply, needs_approval) buckets."""
    auto_apply = []
    needs_approval = []
    for p in proposals:
        if is_auto_appliable(p):
            auto_apply.append(p)
        else:
            needs_approval.append(p)
    return auto_apply, needs_approval


def build_approval_digest(proposals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build ONE clustered approval digest (not one card per proposal)."""
    return {
        "type": "clustered_approval_digest",
        "count": len(proposals),
        "proposals": [
            {
                "id": p.get("id"),
                "category": p.get("category"),
                "summary": p.get("summary", ""),
                "blast_radius": score_blast_radius(p),
            }
            for p in proposals
        ],
        "generated_at": time.time(),
    }


# ---------------------------------------------------------------------------
# Template A/B rotation (weekly)
# ---------------------------------------------------------------------------

CHALLENGER_TRAFFIC_FRACTION = 0.10  # 10% traffic to challenger


class TemplateVariantManager:
    """Manage 1 challenger template per task class at 10% traffic."""

    def __init__(self):
        self._variants: Dict[str, Dict[str, Any]] = {}

    def register_challenger(self, task_class: str, template_id: str,
                            template_content: str) -> None:
        """Register a challenger template for a task class."""
        self._variants[task_class] = {
            "challenger_id": template_id,
            "content": template_content,
            "traffic_fraction": CHALLENGER_TRAFFIC_FRACTION,
            "registered_at": time.time(),
        }

    def get_active_variant(self, task_class: str,
                           random_val: float = 0.0) -> Optional[str]:
        """Return challenger template_id if random_val < traffic fraction."""
        variant = self._variants.get(task_class)
        if variant and random_val < variant["traffic_fraction"]:
            return variant["challenger_id"]
        return None

    def list_variants(self) -> Dict[str, Dict[str, Any]]:
        """Return all registered variants."""
        return dict(self._variants)

    def remove_variant(self, task_class: str) -> bool:
        """Remove a challenger variant."""
        return self._variants.pop(task_class, None) is not None


# ---------------------------------------------------------------------------
# Coordination check
# ---------------------------------------------------------------------------

def verify_hourly_coordination(schedule_entries: List[Dict[str, Any]]) -> bool:
    """Verify generator_feedback and queue_velocity are coordinated hourly."""
    gf = None
    qv = None
    for entry in schedule_entries:
        name = entry.get("name", "")
        if "generator_feedback" in name:
            gf = entry
        elif "queue_velocity" in name:
            qv = entry
    if not gf or not qv:
        return False
    # Both must be hourly
    gf_interval = gf.get("interval_seconds", 0)
    qv_interval = qv.get("interval_seconds", 0)
    if gf_interval != 3600 or qv_interval != 3600:
        return False
    # They should be within 5 minutes of each other
    gf_offset = gf.get("offset_seconds", 0)
    qv_offset = qv.get("offset_seconds", 0)
    return abs(gf_offset - qv_offset) <= 300


def get_cadence_summary() -> Dict[str, List[str]]:
    """Return a summary of all cadence groups."""
    return {
        "hourly": HOURLY_JOBS,
        "nightly": NIGHTLY_JOBS,
        "weekly": WEEKLY_JOBS,
    }
