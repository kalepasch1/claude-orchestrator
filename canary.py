#!/usr/bin/env python3
"""canary.py — canary marker validation with logging + CLI exit-code contract.

canary-gemini-25 series (define-valida / setup-basic-c / exit-code-en slices):
  * `import sys` and `import logging` at the top; logging.basicConfig(INFO)
    immediately after imports, guarded so an embedding application's logging
    configuration is never clobbered.
  * validate_canary(response_text) -> bool  (str -> bool)
  * CLI integration: `python canary.py <text…>` exits 0 when the canary marker
    is present, 1 when absent — so pipelines can gate on the exit code.

Mirrors runner/canary_validation.py (word-boundary, case-insensitive match).
"""
import sys
import logging

if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO)

import re

logger = logging.getLogger(__name__)

_CANARY = re.compile(r"\bcanary\b", re.IGNORECASE)


def validate_canary(response_text) -> bool:
    """Return True when `response_text` carries a canary marker."""
    if not isinstance(response_text, str):
        logger.warning("validate_canary: non-string input %r -> False", type(response_text))
        return False
    ok = bool(_CANARY.search(response_text))
    logger.info("validate_canary: %s in %r", "marker found" if ok else "no marker",
                response_text[:60])
    return ok


def main(argv=None) -> int:
    """Validate CLI-provided text; exit 0 iff the canary marker is present."""
    args = sys.argv[1:] if argv is None else list(argv)
    text = " ".join(args)
    if validate_canary(text):
        logger.info("canary: validation passed")
        return 0
    logger.error("canary: validation failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
