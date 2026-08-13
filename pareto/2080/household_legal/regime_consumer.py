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
import os
import sys
from typing import Any, Dict, List, Optional, Union

log = logging.getLogger(__name__)

# Fields a usable regime event must carry.
REQUIRED_FIELDS = ("jurisdiction",)

# Sentinel distinguishing "second argument omitted" from "second argument was
# None". `safe_consume_regime_event(None)` and `(None, None)` mean different
# things — see that function's docstring.
_OMITTED = object()


class NoOpRegimeOracle:
    """The oracle used when the real one cannot be reached.

    Shaped exactly like the `RegimeOracle` protocol, so every caller and every
    `getattr(oracle, ...)` probe in this module keeps working unchanged. It
    reports no events rather than raising, because an unreachable jurisdiction
    feed must degrade the household-legal pipeline to "no changes this pass",
    never take it down.

    It deliberately does NOT pretend to succeed at `subscribe`: returning None
    is what the protocol says, but `available` is False so a caller that cares
    can tell a real quiet feed from a missing one.
    """

    #: False on this class, True on any real oracle. Lets a caller distinguish
    #: "the feed said nothing" from "there is no feed", which the event list
    #: alone cannot express.
    available = False

    def get_events(self, jurisdiction: str) -> List[Any]:
        log.debug("no-op regime oracle: no events for %s", jurisdiction)
        return []

    def subscribe(self, jurisdiction: str, callback: str) -> None:
        log.debug("no-op regime oracle: ignoring subscribe for %s", jurisdiction)
        return None


def _load_contracts_module():
    """Import `pareto/2080/contracts/autonomy.py`, or return None.

    '2080' is not a valid Python identifier, so this package cannot be reached
    by dotted path. The repo convention (pareto/2080/contracts/test_contracts_smoke.py,
    doc_updater.py, test_household_legal.py) is to put the directory on sys.path
    and import by bare name; this follows it.
    """
    contracts_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contracts"
    )
    if contracts_dir not in sys.path:
        sys.path.insert(0, contracts_dir)
    import autonomy  # noqa: PLC0415  (deliberately late and guarded)

    return autonomy


def get_regime_oracle(provider: Any = None) -> Any:
    """Return a usable regime oracle. NEVER raises.

    Resolution order: an explicitly supplied `provider` (called if callable),
    then the contracts module's oracle if one is exposed there, then the no-op.

    Note what the contracts module actually offers today: `RegimeOracle` is a
    `typing.Protocol`, a shape rather than an implementation, so there is no
    instance to hand back and this correctly degrades to `NoOpRegimeOracle`.
    That is the honest answer, and it is why the fallback is the normal path
    rather than an error path — the function exists so callers stop writing
    their own try/except around an import that has no implementation behind it
    yet. When a concrete feed lands, exposing it as `get_regime_oracle` or
    `REGIME_ORACLE` in the contracts module is all that is needed here.

    Degrades silently (logged at debug/warning, never raised) on: import error,
    a provider that raises, a provider that returns None, or anything else.
    """
    if provider is not None:
        try:
            oracle = provider() if callable(provider) else provider
            if oracle is not None:
                return oracle
            log.warning("regime_consumer: supplied provider returned None; using no-op")
        except Exception as exc:                                # fail-soft
            log.warning("regime_consumer: provider raised (%s); using no-op", exc)
        return NoOpRegimeOracle()

    try:
        autonomy = _load_contracts_module()
    except Exception as exc:                                    # fail-soft
        log.warning("regime_consumer: contracts unavailable (%s); using no-op", exc)
        return NoOpRegimeOracle()

    for attr in ("get_regime_oracle", "REGIME_ORACLE", "regime_oracle"):
        candidate = getattr(autonomy, attr, None)
        if candidate is None:
            continue
        try:
            oracle = candidate() if callable(candidate) else candidate
        except Exception as exc:                                # fail-soft
            log.warning("regime_consumer: %s raised (%s); using no-op", attr, exc)
            continue
        if oracle is not None:
            return oracle

    log.debug("regime_consumer: contracts expose no oracle instance; using no-op")
    return NoOpRegimeOracle()


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


def safe_consume_regime_event(
    oracle: Any,
    jurisdiction: Any = _OMITTED,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """Consume regime events, fail-soft. NEVER raises.

    TWO CALL SHAPES, distinguished by arity, because two live contracts
    converged on this one name and dropping either one breaks a real caller:

      safe_consume_regime_event(oracle, jurisdiction) -> list[dict]
          Pull-from-feed. The shipped shape: fetch this jurisdiction's events
          from the oracle and return the normalised ones. Six assertions in
          test_household_legal.py depend on it, and doc_updater.py imports it.

      safe_consume_regime_event(event) -> dict
          Consume-one-event. Normalise a single already-received `RegimeEvent`
          (or dict, or None) and return it as a dict, or {} when it cannot be
          trusted. Always a dict, never None, so a caller can index the result
          without a guard.

    Overloading a name is not free, and the alternative was considered first:
    a second function under a different name. It was rejected because the
    earlier attempts at this task redefined THIS name with the one-argument
    signature, which is what made the branch conflict four times running — the
    two shapes are genuinely the same operation seen from either side of the
    feed, and callers of both spellings exist. Arity separates them with no
    ambiguity: no legitimate call passes a jurisdiction without an oracle.

    Both shapes fail soft. The one-argument form returns {}; the two-argument
    form returns []. Every degradation is logged, because a feed dead for a
    week and a feed with genuinely no changes look identical from the outside
    and only the log tells them apart.
    """
    if jurisdiction is _OMITTED:
        # Consume-one-event: `oracle` is the event.
        normalised = normalize_regime_event(oracle)
        if normalised is None:
            log.warning("regime_consumer: unusable event; returning empty result")
            return {}
        return normalised

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
