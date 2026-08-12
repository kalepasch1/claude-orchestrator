#!/usr/bin/env python3
"""canary.py — canary marker validation with logging + CLI exit-code contract.

canary-gemini-25 series (define-valida / setup-basic-c / exit-code-en slices):
  * `import sys` and `import logging` at the top; logging.basicConfig(INFO)
    immediately after imports, guarded so an embedding application's logging
    configuration is never clobbered.
  * validate_canary(response_text) -> bool  (str -> bool)
  * CLI integration: `python canary.py <text…>` exits 0 when the canary marker
    is present, 1 when absent — so pipelines can gate on the exit code.
  * `--request-only` probe: POSTs to a canary endpoint and reports transport
    health via the exit code. 5xx responses are retried (they are transient);
    4xx responses are NOT — an invalid API key or malformed request will never
    succeed on retry, so the probe fails immediately with exit code 5 and an
    error naming the status, instead of burning the retry budget.

Exit-code contract:
    0  canary marker present / request succeeded
    1  canary marker absent
    4  transport failure or 5xx exhausted after retries
    5  client error (4xx) — do not retry, credentials/request are wrong

Mirrors runner/canary_validation.py (word-boundary, case-insensitive match).
"""
import argparse
import os
import sys
import time
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


# --- exit codes -------------------------------------------------------------

EXIT_OK = 0
EXIT_NO_MARKER = 1
EXIT_TRANSPORT = 4
EXIT_CLIENT_ERROR = 5

#: Retries are for transient server-side failures only.
ORCH_CANARY_MAX_RETRIES = int(os.environ.get("ORCH_CANARY_MAX_RETRIES", "3"))
ORCH_CANARY_BACKOFF_SECONDS = float(os.environ.get("ORCH_CANARY_BACKOFF_SECONDS", "1.0"))
ORCH_CANARY_TIMEOUT_SECONDS = float(os.environ.get("ORCH_CANARY_TIMEOUT_SECONDS", "30"))


def is_retryable(status_code) -> bool:
    """True only for 5xx. A 4xx is a client error and will never self-heal.

    This is the whole point of the slice: an invalid API key (403) or a
    malformed request (400) returns the same failure on every attempt, so
    retrying just burns the budget and hides the real cause.
    """
    try:
        code = int(status_code)
    except (TypeError, ValueError):
        return False
    return 500 <= code < 600


def _reason_for(response) -> str:
    reason = getattr(response, "reason", None)
    if reason:
        return str(reason)
    try:
        code = int(getattr(response, "status_code", 0))
    except (TypeError, ValueError):
        return ""
    return {400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
            404: "Not Found", 429: "Too Many Requests"}.get(code, "")


def perform_request(url, payload=None, headers=None, session=None):
    """POST to `url`, honouring the retry policy. Returns an exit code.

    * 2xx/3xx           -> EXIT_OK
    * 4xx               -> EXIT_CLIENT_ERROR immediately, NO retries
    * 5xx               -> retried up to ORCH_CANARY_MAX_RETRIES, then EXIT_TRANSPORT
    * transport failure -> retried, then EXIT_TRANSPORT

    `session` is an injection seam for tests; by default `requests` is imported
    lazily so the validation path has no hard dependency on it.
    """
    if session is None:
        try:
            import requests as session  # type: ignore
        except ImportError:
            logger.error("canary: `requests` is not installed; cannot probe %s", url)
            return EXIT_TRANSPORT

    attempts = max(1, ORCH_CANARY_MAX_RETRIES)
    for attempt in range(1, attempts + 1):
        try:
            response = session.post(
                url, json=payload or {}, headers=headers or {},
                timeout=ORCH_CANARY_TIMEOUT_SECONDS,
            )
        except Exception as exc:  # transport-level failure: retryable
            logger.error("canary: request error on attempt %d/%d: %s", attempt, attempts, exc)
            if attempt < attempts:
                time.sleep(ORCH_CANARY_BACKOFF_SECONDS * attempt)
                continue
            return EXIT_TRANSPORT

        try:
            status = int(getattr(response, "status_code", 0))
        except (TypeError, ValueError):
            status = 0

        if 200 <= status < 400:
            logger.info("canary: request succeeded (%d)", status)
            return EXIT_OK

        if 400 <= status < 500:
            # Do NOT retry. Print the status and reason so the operator sees
            # "invalid key" rather than a wall of identical retry noise.
            reason = _reason_for(response)
            message = "API error: %d%s" % (status, (" " + reason) if reason else "")
            print(message, file=sys.stderr)
            logger.error("canary: %s — client error, not retrying", message)
            return EXIT_CLIENT_ERROR

        if is_retryable(status):
            logger.warning("canary: server error %d on attempt %d/%d", status, attempt, attempts)
            if attempt < attempts:
                time.sleep(ORCH_CANARY_BACKOFF_SECONDS * attempt)
                continue
            print("API error: %d" % status, file=sys.stderr)
            return EXIT_TRANSPORT

        logger.error("canary: unexpected status %r", status)
        print("API error: %s" % status, file=sys.stderr)
        return EXIT_TRANSPORT

    return EXIT_TRANSPORT


def main(argv=None) -> int:
    """Validate CLI-provided text, or run the `--request-only` probe."""
    args = sys.argv[1:] if argv is None else list(argv)

    parser = argparse.ArgumentParser(
        prog="canary.py", description="Canary marker validation / endpoint probe.",
        add_help=False,
    )
    parser.add_argument("--request-only", action="store_true")
    parser.add_argument("--url", default=os.environ.get("ORCH_CANARY_URL", ""))
    parser.add_argument("text", nargs="*")
    try:
        parsed, _unknown = parser.parse_known_args(args)
    except SystemExit:  # fail-soft: never let argparse decide the exit code
        parsed = None

    if parsed is not None and parsed.request_only:
        if not parsed.url:
            print("API error: no --url (or ORCH_CANARY_URL) given", file=sys.stderr)
            logger.error("canary: --request-only requires --url")
            return EXIT_CLIENT_ERROR
        return perform_request(parsed.url, payload={"probe": "canary"})

    text = " ".join(parsed.text if parsed is not None else args)
    if validate_canary(text):
        logger.info("canary: validation passed")
        return EXIT_OK
    logger.error("canary: validation failed")
    return EXIT_NO_MARKER


if __name__ == "__main__":
    sys.exit(main())
