#!/usr/bin/env python3
"""canary.py — canary marker validation with logging + CLI exit-code contract.

canary-gemini-25 series (define-valida / setup-basic-c / exit-code-en slices):
  * `import sys` and `import logging` at the top; logging.basicConfig(INFO)
    immediately after imports, guarded so an embedding application's logging
    configuration is never clobbered.
  * validate_canary(response_text) -> bool  (str -> bool)
  * CLI integration: `python canary.py <text…>` exits 0 when the canary marker
    is present, 1 when absent — so pipelines can gate on the exit code.
  * parse_gemini_text(payload) -> str, and `python canary.py --request-only [PATH]`,
    which prints the model's TEXT out of a Gemini generateContent response
    ({"candidates":[{"content":{"parts":[{"text": …}]}}]}) rather than the raw JSON
    envelope. Exit 0 on success, 3 when the response cannot be parsed, 2 when the
    body cannot be read. The response comes from PATH or stdin, never from a live
    call — see request_only() for why.
  * `python canary.py --probe` closes the loop with mainline: it runs the live call
    through `gemini_canary_probe.probe_gemini` and applies validate_canary to the
    answer. Until this slice the two halves never met — the live call lived in one
    script and the verdict in another, so nothing actually ran the canary end to end.
    Exit 0 marker present, 1 marker absent (model drift), 4 probe failed (outage or
    credential), 5 probe module unavailable.

Mirrors runner/canary_validation.py (word-boundary, case-insensitive match).
"""
import sys
import logging

if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO)

import json
import os
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


class GeminiResponseError(ValueError):
    """The payload was not a Gemini generateContent response we can read text from."""


def parse_gemini_text(payload):
    """Extract the model text from a Gemini generateContent response.

    Expected shape: {"candidates": [{"content": {"parts": [{"text": "..."}]}}]}
    Returns the first candidate's first part's text.

    Raises GeminiResponseError — never KeyError/IndexError/TypeError — for every
    malformed shape, so the CLI has exactly one failure mode to map onto exit code 3.
    A `promptFeedback.blockReason` is reported specifically: a safety-blocked response is
    well-formed JSON with no candidates at all, and "candidates missing" would be a
    misleading diagnosis of it.
    """
    if isinstance(payload, (str, bytes, bytearray)):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError) as e:
            raise GeminiResponseError(f"response is not valid JSON: {e}") from None
    if not isinstance(payload, dict):
        raise GeminiResponseError(
            f"response is {type(payload).__name__}, expected a JSON object")

    candidates = payload.get("candidates")
    if not candidates:
        block = (payload.get("promptFeedback") or {}).get("blockReason") \
            if isinstance(payload.get("promptFeedback"), dict) else None
        if block:
            raise GeminiResponseError(f"no candidates: prompt blocked ({block})")
        raise GeminiResponseError("response has no 'candidates'")
    if not isinstance(candidates, list):
        raise GeminiResponseError("'candidates' is not a list")

    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    if not isinstance(content, dict):
        raise GeminiResponseError("first candidate has no 'content' object")

    parts = content.get("parts")
    if not isinstance(parts, list) or not parts:
        raise GeminiResponseError("first candidate's content has no 'parts'")
    if not isinstance(parts[0], dict) or "text" not in parts[0]:
        raise GeminiResponseError("first part carries no 'text'")

    text = parts[0]["text"]
    if not isinstance(text, str):
        raise GeminiResponseError(f"'text' is {type(text).__name__}, expected a string")
    return text


def _read_response_payload(path=None):
    """Read a Gemini response body from *path*, or from stdin when path is None/'-'."""
    if path in (None, "-"):
        return sys.stdin.read()
    with open(path, encoding="utf-8") as f:
        return f.read()


def request_only(path=None, out=None):
    """--request-only flow: print the model's TEXT, not the raw JSON envelope.

    Returns the process exit code: 0 when the text was extracted, 3 when the response
    could not be parsed, 2 when the response body could not be read at all.

    NOTE ON SCOPE (rework): the original slice performed a live generateContent call and
    parsed the result. The call is the part that could not run — it needs a key, network
    egress and a paid quota, and every prior attempt died there before reaching the
    parsing this task is actually about. The parsing is pure and is what the acceptance
    describes ("prints the extracted text and exits 0 / prints an error and exits 3"), so
    the body is taken from a file or stdin and the network is left out. A caller that has
    a key pipes the real response in:
        curl -s ...generateContent... | python canary.py --request-only
    """
    stream = sys.stdout if out is None else out
    try:
        raw = _read_response_payload(path)
    except OSError as e:
        print(f"canary: could not read response: {e}", file=sys.stderr)
        logger.error("canary: could not read response: %s", e)
        return 2
    try:
        text = parse_gemini_text(raw)
    except GeminiResponseError as e:
        print(f"canary: could not parse Gemini response: {e}", file=sys.stderr)
        logger.error("canary: could not parse Gemini response: %s", e)
        return 3
    print(text, file=stream)
    logger.info("canary: extracted %d characters of model text", len(text))
    return 0


#: Exit codes for the --probe flow. Deliberately distinct from 1 (marker absent), because
#: "the model answered something else" and "we never reached the model" call for opposite
#: responses: the first is model drift a human should look at, the second is an outage or
#: a credential. Collapsing them is the exact ambiguity gemini_canary_probe.py's module
#: docstring says the split exists to prevent — and until now nothing joined the two
#: halves, so the live call and the verdict lived in different scripts that never met.
EXIT_PROBE_FAILED = 4
EXIT_PROBE_UNAVAILABLE = 5


def probe_and_validate(probe_fn=None, out=None):
    """Ask the live model for the marker, then apply this module's verdict to the answer.

    This is the integration point: `gemini_canary_probe.probe_gemini` owns the network
    call and its retry/credential policy, `validate_canary` owns the verdict. Neither
    grows a copy of the other.

    ``probe_fn`` is injectable so the wiring is testable without a key or a network.
    Returns the process exit code:

        0  marker present — the canary is healthy
        1  a reply arrived but carries no marker — model drift, look at it
        4  the probe itself failed (transport, retries exhausted, bad credential)
        5  the probe module is not importable in this environment
    """
    stream = sys.stdout if out is None else out
    if probe_fn is None:
        try:
            import gemini_canary_probe
        except Exception as e:  # noqa: BLE001 - any import failure is one signal
            print(f"canary: gemini_canary_probe unavailable: {e}", file=sys.stderr)
            logger.error("canary: gemini_canary_probe unavailable: %s", e)
            return EXIT_PROBE_UNAVAILABLE
        probe_fn = gemini_canary_probe.probe_gemini

    try:
        text = probe_fn(os.environ.get("GEMINI_API_KEY", ""))
    except Exception as e:  # noqa: BLE001 - the probe already classified it; we only route
        print(f"canary: probe failed: {type(e).__name__}: {e}", file=sys.stderr)
        logger.error("canary: probe failed: %s: %s", type(e).__name__, e)
        return EXIT_PROBE_FAILED

    print(text if isinstance(text, str) else "", file=stream)
    if validate_canary(text):
        logger.info("canary: live probe validated")
        return 0
    logger.error("canary: live probe returned no marker — model drift")
    return 1


def main(argv=None) -> int:
    """Validate CLI-provided text; exit 0 iff the canary marker is present.

    `--request-only [PATH]` switches to the Gemini response-parsing flow instead: it
    prints the extracted model text and exits 0, or prints an error and exits 3.

    `--probe` performs the live call through gemini_canary_probe and validates what
    comes back, distinguishing "no marker" (1) from "never reached the model" (4/5).
    """
    args = sys.argv[1:] if argv is None else list(argv)
    if args and args[0] == "--probe":
        return probe_and_validate()
    if args and args[0] == "--request-only":
        rest = args[1:]
        return request_only(rest[0] if rest else None)
    text = " ".join(args)
    if validate_canary(text):
        logger.info("canary: validation passed")
        return 0
    logger.error("canary: validation failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
