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


def probe_gemini(api_key: str, model: str = DEFAULT_MODEL, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Call generateContent and return the model's text. Raises on transport/HTTP failure."""
    if not api_key:
        raise ValueError("GEMINI_API_KEY is empty or unset")
    request = urllib.request.Request(
        _ENDPOINT.format(model=model),
        data=json.dumps({"contents": [{"parts": [{"text": PROMPT}]}]}).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return extract_text(json.loads(response.read().decode("utf-8")))


def main(argv=None) -> int:
    """Print the model's reply on stdout; non-zero exit means the call itself failed."""
    model = os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
    try:
        timeout = int(os.environ.get("GEMINI_TIMEOUT") or DEFAULT_TIMEOUT)
    except ValueError:
        timeout = DEFAULT_TIMEOUT
    try:
        text = probe_gemini(os.environ.get("GEMINI_API_KEY", ""), model, timeout)
    except urllib.error.HTTPError as exc:
        # 400/403 here is the invalid-key case the acceptance criteria calls out.
        logger.error("gemini probe: HTTP %s from %s", exc.code, model)
        return 1
    except Exception as exc:  # noqa: BLE001 - any transport failure is one signal: probe down
        logger.error("gemini probe: %s: %s", type(exc).__name__, exc)
        return 1
    # stdout is the payload; logging goes to stderr, so command substitution stays clean.
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
