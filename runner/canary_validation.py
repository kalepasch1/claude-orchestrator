#!/usr/bin/env python3
"""Canary validation helper (canary-gemini-25).

`validate_canary(text)` — True iff the text contains the token "canary"
(case-insensitive, word-boundary match). Used by canary-routing checks to
confirm a canary marker survived a pipeline hop.

NOT THE SAME FUNCTION as `canary.validate_canary`, despite the identical name. That one
is a plain SUBSTRING match and logs WARNING on a miss; this one requires a word boundary
and logs INFO. They disagree on affixed forms — `"precanary build"` is False here and
True there — so the two imports are not interchangeable. Both behaviours are deliberate
and separately tested, so neither may be quietly folded into the other;
`tests/test_validate_canary_divergence.py` pins the difference.
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
