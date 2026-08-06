"""Consume jurisdiction rule-change events from a RegimeOracle, fail-soft.

The oracle is an EXTERNAL dependency: a jurisdiction feed that will be
unavailable, slow, or malformed at some point. Every consumer here treats that
as normal rather than exceptional — an oracle outage must degrade to "no events
this pass", never to a raised exception that takes the household-legal pipeline
down with it.

The one thing this module will not do is invent an event. A fabricated
rule-change would trigger a document rewrite and a user notification off nothing
at all, which is far worse than silence.
"""
import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# Fields a usable regime event must carry.
REQUIRED_FIELDS = ("jurisdiction",)


def _as_dict(event: Any) -> Optional[Dict[str, Any]]:
    """Normalise an oracle event (dataclass, dict, or object) into a dict."""
    if event is None:
        return None
    if isinstance(event, dict):
        return dict(event)
    # RegimeEvent from pareto.2080.contracts.autonomy is a dataclass.
    data = getattr(event, "__dict__", None)
    if isinstance(data, dict) and data:
        return dict(data)
    return None


def normalize_regime_event(event: Any) -> Optional[Dict[str, Any]]:
    """Return a usable event dict, or None when it cannot be trusted.

    Accepts the two spellings in circulation: `jurisdiction` (the RegimeEvent
    contract) and `regime` (the shorthand used by fixtures and callers). They
    are the same field; normalising here stops every downstream consumer from
    having to guess which one it received.
    """
    data = _as_dict(event)
    if not data:
        return None
    jurisdiction = f"{data.get('jurisdiction') or data.get('regime') or ''}".strip()
    if not jurisdiction:
        return None
    return {
        "jurisdiction": jurisdiction,
        "regime": jurisdiction,
        "rule_id": f"{data.get('rule_id') or ''}".strip(),
        "description": f"{data.get('description') or ''}".strip(),
        "effective_date": f"{data.get('effective_date') or ''}".strip(),
    }


def safe_consume_regime_event(oracle: Any, jurisdiction: str) -> List[Dict[str, Any]]:
    """Fetch and normalise events for `jurisdiction`. NEVER raises.

    Returns [] on: no oracle, an oracle that raises, an oracle that returns a
    non-iterable, or events that fail normalisation. Each of those is logged so
    an outage is visible rather than silent — a feed that has been dead for a
    week and a feed with genuinely no changes look identical from the outside,
    and only the log tells them apart.
    """
    if oracle is None:
        log.warning("regime_consumer: no oracle supplied; treating as no events")
        return []

    getter = getattr(oracle, "get_events", None)
    if not callable(getter):
        log.warning("regime_consumer: oracle has no callable get_events; no events")
        return []

    try:
        raw = getter(jurisdiction)
    except Exception as exc:                                   # fail-soft
        log.warning("regime_consumer: oracle unavailable for %s: %s", jurisdiction, exc)
        return []

    try:
        candidates = list(raw or [])
    except TypeError:
        log.warning("regime_consumer: oracle returned a non-iterable for %s", jurisdiction)
        return []

    events = []
    for candidate in candidates:
        normalised = normalize_regime_event(candidate)
        if normalised is None:
            log.warning("regime_consumer: dropping unusable event for %s", jurisdiction)
            continue
        events.append(normalised)
    return events


def safe_subscribe(oracle: Any, jurisdiction: str, callback: str) -> bool:
    """Subscribe to a jurisdiction. Returns success; never raises."""
    subscribe = getattr(oracle, "subscribe", None)
    if not callable(subscribe):
        log.warning("regime_consumer: oracle has no callable subscribe")
        return False
    try:
        subscribe(jurisdiction, callback)
        return True
    except Exception as exc:                                   # fail-soft
        log.warning("regime_consumer: subscribe failed for %s: %s", jurisdiction, exc)
        return False
