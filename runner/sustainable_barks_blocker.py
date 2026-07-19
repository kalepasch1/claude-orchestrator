"""Sustainable Barks batch-blocking policy engine.

Evaluates whether an incoming batch payload should be blocked
based on author allowlists and behaviour deny-lists.
"""


def should_block_batch(payload, policies=None):
    """Return (blocked: bool, reason: str) for the given payload/policies.

    If *policies* is None or has an empty/missing allowlist the batch is
    allowed by default (open policy).
    """
    if policies is None:
        return False, ""

    allowlist = policies.get("allowlist") or []
    if not allowlist:
        return False, ""

    author = payload.get("author", "")
    if author not in allowlist:
        return True, f"author '{author}' not in allowlist"

    blocked_behaviors = policies.get("blocked_behaviors") or []
    behavior = payload.get("behavior", "")
    if behavior in blocked_behaviors:
        return True, f"behavior '{behavior}' is blocked"

    return False, ""
