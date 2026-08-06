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

# Sentinel so the two-arity dispatch can tell "not passed" from an explicit None.
_UNSET = object()


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


class NoOpRegimeOracle:
    """The oracle used when the real one cannot be reached.

    Explicit rather than None so callers never branch on it, and so the failure
    mode is "no events" rather than an AttributeError somewhere downstream. It
    reports `available = False` so a caller that DOES care can tell the
    difference between a quiet jurisdiction and a dead feed.
    """

    available = False

    def get_events(self, jurisdiction: str) -> List[Any]:
        return []

    def subscribe(self, jurisdiction: str, callback: str) -> None:
        return None


def get_regime_oracle(factory: Any = None) -> Any:
    """Return a RegimeOracle. Silently degrades to a no-op oracle. NEVER raises.

    Unavailability covers all three shapes the contract can fail in: the import
    fails, the factory returns None, or the factory raises.
    """
    if factory is not None:
        try:
            oracle = factory() if callable(factory) else factory
            return oracle if oracle is not None else NoOpRegimeOracle()
        except Exception as exc:                               # fail-soft
            log.warning("regime_consumer: oracle factory failed: %s", exc)
            return NoOpRegimeOracle()

    try:
        import os
        import sys
        contracts = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contracts")
        if contracts not in sys.path:
            sys.path.insert(0, contracts)
        import autonomy  # noqa: F401  — presence proves the contract is importable
        # The Protocol has no default implementation; a real oracle is injected
        # by the caller. Absent one, degrade rather than fabricate a feed.
        return NoOpRegimeOracle()
    except Exception as exc:                                   # fail-soft
        log.warning("regime_consumer: contracts unavailable (%s); using no-op oracle", exc)
        return NoOpRegimeOracle()


def safe_consume_regime_event(oracle: Any, jurisdiction: Any = _UNSET) -> Any:
    """Consume regime data safely. NEVER raises.

    Two call shapes, because two sibling slices specify this name differently
    and both are live:

      safe_consume_regime_event(event)               -> dict  (empty on failure)
      safe_consume_regime_event(oracle, jurisdiction) -> list  (empty on failure)

    Dispatching on arity keeps one function honest for both callers rather than
    having two near-identical functions drift apart, which is the failure this
    codebase has already paid for elsewhere.
    """
    if jurisdiction is _UNSET:
        # Single-argument form: normalise ONE event into a dict.
        try:
            normalised = normalize_regime_event(oracle)
            if normalised is None:
                log.warning("regime_consumer: unusable event; returning {}")
                return {}
            return normalised
        except Exception as exc:                               # fail-soft
            log.warning("regime_consumer: event normalisation failed: %s", exc)
            return {}
    return consume_oracle_events(oracle, jurisdiction)


def consume_oracle_events(oracle: Any, jurisdiction: str) -> List[Dict[str, Any]]:
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
