#!/usr/bin/env python3
"""Canary validation helper (canary-gemini-25).

`validate_canary(text)` — True iff the text contains the token "canary"
(case-insensitive, word-boundary match). Used by canary-routing checks to
confirm a canary marker survived a pipeline hop.

SAME VERDICT as `canary.validate_canary` and `runner.canary.validate_canary`, different
logging. All three now match on a word boundary: a marker check whose job is to prove a
canary survived a pipeline hop must not depend on which import the caller reached for,
and `"precanary"` used to validate at one entry point and fail at the others.
`tests/test_canary_validation_agreement.py` pins the agreement across all three.

What still differs is severity on a miss — WARNING in canary.py, INFO here — because an
operator greps for the warning. That one difference is deliberate and is pinned by
`tests/test_validate_canary_divergence.py`, so a consolidation cannot change warning
volume by accident. Do not alias one function to the other: agreement is a property of
behaviour here, not of identity.
"""
import logging
import re

logger = logging.getLogger(__name__)

_CANARY = re.compile(r"\bcanary\b", re.IGNORECASE)


def validate_canary(text) -> bool:
    """Return True when `text` carries a canary marker; False otherwise."""
    if not isinstance(text, str):
        logger.warning("validate_canary: non-string input %r -> False", type(text))
        return False
    ok = bool(_CANARY.search(text))
    if ok:
        logger.info("validate_canary: marker found in %r", text[:60])
    else:
        logger.info("validate_canary: no marker in %r", text[:60])
    return ok
