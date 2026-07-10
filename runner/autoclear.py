"""Rule-based auto-clearing for operator approval cards.

Rules are loaded from the operator_autoclear_rules DB table (fall back to
runner/autoclear_rules.yaml when the table is absent or empty).

HARD GUARDS — autoclear_decision() returns (None, None) if ANY of these hold:
  1. AUTOCLEAR_ENABLED env var is not exactly 'true'
  2. card's approvals_required >= 2
  3. card kind is 'legal'
  4. card detail mentions prod / production deploy

No secrets or credentials are stored here; the DB table stores only
project/kind/max_usd/enabled config, not any credentials.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

_YAML_FALLBACK = Path(__file__).parent / "autoclear_rules.yaml"

# Kill-switch: must be exactly 'true' (case-insensitive) or no auto-clears happen.
AUTOCLEAR_ENABLED = os.environ.get("AUTOCLEAR_ENABLED", "").strip().lower() == "true"

_PROD_PATTERN = re.compile(r"\bprod(?:uction)?\b", re.I)


def _load_rules_from_db() -> list[dict]:
    try:
        import db
        rows = db.select("operator_autoclear_rules", {"select": "*", "enabled": "eq.true"})
        return rows or []
    except Exception:
        return []


def _load_rules_from_yaml() -> list[dict]:
    try:
        import yaml  # type: ignore
        with open(_YAML_FALLBACK, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return [r for r in (data.get("rules") or []) if r.get("enabled", True)]
    except Exception:
        return []


def load_rules() -> list[dict]:
    """Return active rules from DB; fall back to YAML if DB returns nothing."""
    rules = _load_rules_from_db()
    if not rules:
        rules = _load_rules_from_yaml()
    return rules


def _parse_usd(detail: str) -> Optional[float]:
    """Extract the first dollar amount from a card's detail string."""
    m = re.search(r"\$([0-9]+(?:\.[0-9]+)?)", detail or "")
    return float(m.group(1)) if m else None


def autoclear_decision(card_row: dict, rules: list[dict]) -> tuple[Optional[str], Optional[str]]:
    """Evaluate card_row against rules and return (decision, rule_id).

    Returns ('approved', rule_id) when a matching rule auto-approves.
    Returns (None, None) in all other cases (pending / hard-blocked).
    """
    # Kill-switch
    if not AUTOCLEAR_ENABLED:
        return None, None

    # Hard guard: multi-sig cards are never auto-approved
    if int(card_row.get("approvals_required") or 1) >= 2:
        return None, None

    kind = (card_row.get("kind") or "").lower()

    # Hard guard: legal cards never auto-approve
    if kind == "legal":
        return None, None

    # Hard guard: production deploy cards never auto-approve
    detail = card_row.get("detail") or ""
    if _PROD_PATTERN.search(detail):
        return None, None

    project = card_row.get("project") or ""
    card_usd = _parse_usd(detail)

    for rule in rules:
        if not rule.get("enabled", True):
            continue
        # project filter (None / absent = match all)
        rp = rule.get("project")
        if rp and rp != project:
            continue
        # kind filter
        rk = (rule.get("kind") or "").lower()
        if rk and rk != kind:
            continue
        # max_usd filter
        max_usd = rule.get("max_usd")
        if max_usd is not None:
            if card_usd is None or card_usd > float(max_usd):
                continue
        return "approved", str(rule.get("id", "unknown"))

    return None, None
