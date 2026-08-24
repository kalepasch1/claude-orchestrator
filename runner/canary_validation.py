#!/usr/bin/env python3
"""Canary validation helper (canary-gemini-25).

`validate_canary(text)` — True iff the text contains the token "canary"
(case-insensitive, word-boundary match). Used by canary-routing checks to
confirm a canary marker survived a pipeline hop.

THIS IS THE SINGLE SOURCE OF THE MATCH. `canary.validate_canary` has the same name and
DELEGATES here, so the two always return the same verdict.

Corrected 2026-08-24: this docstring used to say the two disagreed on affixed forms
("precanary build" False here, True there) and cited a test pinning that difference. That
was true of the pre-unification code and has not been true since 2026-08-13, when three
disagreeing copies were collapsed onto this word-boundary match — a canary hop could
otherwise be reported as both intact and broken depending on which import a caller used.
The stale note was actively dangerous: it told the next reader the split-brain was
intentional, and `tests/test_validate_canary_divergence.py` still asserted it and had
been failing on master ever since. Both are corrected; that file now pins AGREEMENT.

What DOES still differ is the log severity on a miss — WARNING from `canary`, INFO here —
and that remains pinned, so a consolidation cannot change an operator's warning volume by
accident.
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
