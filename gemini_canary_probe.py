#!/usr/bin/env python3
"""gemini_canary_probe.py — ask Gemini for the canary marker, print what came back.

Pairs with `canary.py`, which owns the verdict. This module owns only the network
call, so the two failure modes the scheduled canary exists to catch stay separable:

  * credential/transport failure (bad or expired GEMINI_API_KEY, 4xx/5xx, timeout)
    -> this script exits non-zero and prints the reason to stderr;
  * live-but-wrong model output (the key works, the answer is not what we asked for)
    -> this script exits 0 having printed the text, and `canary.py` fails on it.

Collapsing both into one script would have made "the key died" and "the model drifted"
report identically at 05:00, which is exactly the ambiguity the canary is meant to remove.

stdlib only — the repo's requirements.txt carries no Google SDK and this must run on a
bare runner.

Env:
  GEMINI_API_KEY   required
  GEMINI_MODEL     default gemini-2.0-flash
  GEMINI_TIMEOUT   seconds, default 30
"""
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request

if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.0-flash"
DEFAULT_TIMEOUT = 30
_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Deliberately explicit: a healthy model returns the word, so a missing marker is a real
# signal rather than an artifact of a vague prompt.
PROMPT = "Reply with exactly one word: canary"


def extract_text(payload) -> str:
    """Pull the response text out of a generateContent payload, fail-soft to ''.

    A shape change upstream must degrade to 'no marker' (canary.py fails loudly) rather
    than to a traceback that reads like an infrastructure outage.
    """
    if not isinstance(payload, dict):
        return ""
    parts = []
    for candidate in payload.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        for part in content.get("parts") or []:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
    return " ".join(parts).strip()


#: HTTP statuses worth trying again. 429 and 5xx are the provider being busy or briefly
#: broken; everything else is a decision the provider has already made.
RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})

#: A wrong/expired/revoked key. Retrying these burns the schedule and, worse, delays the
#: page for the one failure an operator must act on personally.
AUTH_STATUSES = frozenset({400, 401, 403})

MAX_ATTEMPTS = int(os.environ.get("GEMINI_MAX_ATTEMPTS", "3"))
BACKOFF_BASE_S = float(os.environ.get("GEMINI_BACKOFF_BASE_S", "1.0"))


class InvalidKeyError(RuntimeError):
    """The credential was rejected. Never retried."""


def is_retryable(status: int) -> bool:
    return int(status) in RETRYABLE_STATUSES


def probe_gemini(api_key: str, model: str = DEFAULT_MODEL, timeout: int = DEFAULT_TIMEOUT,
                 attempts: int = None, sleep=None) -> str:
    """Call generateContent and return the model's text.

    RETRY POLICY. A canary that runs every 5 minutes must not report an outage because
    one request hit a 503 — that trains people to ignore it. But it must not paper over a
    dead key either, so the two are separated explicitly:

      * 429/5xx/timeout  -> transient. Retried with exponential backoff.
      * 400/401/403      -> the key is wrong, expired or revoked. Raised IMMEDIATELY as
                            InvalidKeyError; retrying cannot fix a credential, and doing
                            so delays the one failure a human has to act on personally.
      * anything else    -> raised as-is; guessing is how a real fault gets absorbed.

    `sleep` is injectable so the backoff is testable without actually waiting.
    """
    if not api_key:
        raise ValueError("GEMINI_API_KEY is empty or unset")
    total = max(1, int(attempts if attempts is not None else MAX_ATTEMPTS))
    pause = sleep or time.sleep
    last_error = None

    for attempt in range(total):
        request = urllib.request.Request(
            _ENDPOINT.format(model=model),
            data=json.dumps({"contents": [{"parts": [{"text": PROMPT}]}]}).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return extract_text(json.loads(response.read().decode("utf-8")))
        except urllib.error.HTTPError as exc:
            if exc.code in AUTH_STATUSES:
                raise InvalidKeyError(
                    f"GEMINI_API_KEY rejected with HTTP {exc.code} — the credential is "
                    f"wrong, expired or revoked. Not retried.") from exc
            if not is_retryable(exc.code) or attempt == total - 1:
                raise
            last_error = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # Transport-level: DNS, connection reset, read timeout. Transient by nature.
            if attempt == total - 1:
                raise
            last_error = exc
        delay = BACKOFF_BASE_S * (2 ** attempt)
        logger.warning("gemini probe: attempt %d/%d failed (%s); retrying in %.1fs",
                       attempt + 1, total, type(last_error).__name__, delay)
        pause(delay)

    raise RuntimeError(f"gemini probe exhausted {total} attempts: {last_error}")


def main(argv=None) -> int:
    """Print the model's reply on stdout; non-zero exit means the call itself failed."""
    model = os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
    try:
        timeout = int(os.environ.get("GEMINI_TIMEOUT") or DEFAULT_TIMEOUT)
    except ValueError:
        timeout = DEFAULT_TIMEOUT
    try:
        text = probe_gemini(os.environ.get("GEMINI_API_KEY", ""), model, timeout)
    except InvalidKeyError as exc:
        # Called out separately from a generic HTTP failure: "the key is dead" and "the
        # provider is having a bad minute" need different human responses, and the whole
        # point of the retry split is that the log says which one happened.
        logger.error("gemini probe: %s", exc)
        return 1
    except urllib.error.HTTPError as exc:
        logger.error("gemini probe: HTTP %s from %s after retries", exc.code, model)
        return 1
    except Exception as exc:  # noqa: BLE001 - any transport failure is one signal: probe down
        logger.error("gemini probe: %s: %s", type(exc).__name__, exc)
        return 1
    # stdout is the payload; logging goes to stderr, so command substitution stays clean.
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
