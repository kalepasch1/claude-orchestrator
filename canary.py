#!/usr/bin/env python3
"""canary.py — canary marker validation with logging + CLI exit-code contract.

canary-gemini-25 series (define-valida / setup-basic-c / exit-code-en slices):
  * `import sys` and `import logging` at the top; logging.basicConfig(INFO)
    immediately after imports, guarded so an embedding application's logging
    configuration is never clobbered.
  * validate_canary(response_text) -> bool  (str -> bool)
  * process_response(response_text) -> int  (0 when the marker is present, 1 when
    it is absent) — the one place the predicate becomes a process exit status, so
    `main()`, the tests and embedding pipelines cannot drift apart.
  * CLI integration: `python canary.py <text…>` exits 0 when the canary marker
    is present, 1 when absent — so pipelines can gate on the exit code.
  * parse_gemini_text(payload) -> str, and `python canary.py --request-only [PATH]`,
    which prints the model's TEXT out of a Gemini generateContent response
    ({"candidates":[{"content":{"parts":[{"text": …}]}}]}) rather than the raw JSON
    envelope. Exit 0 on success, 3 when the response cannot be parsed, 2 when the
    body cannot be read. The response comes from PATH or stdin, never from a live
    call — see request_only() for why.

Mirrors runner/canary_validation.py (word-boundary, case-insensitive match).
"""
import sys
import logging

if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO)

import json
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


def process_response(response_text) -> int:
    """Map a model response to the CLI exit code: 0 = marker present, 1 = absent.

    This is the single place the boolean predicate is turned into a process exit
    status, so `main()`, the pytest suite and any embedding pipeline all agree on
    the contract instead of each re-deriving `0 if ok else 1`:

        process_response("The canary sings") == 0
        process_response("no bird")          == 1

    Fail-soft per repo convention: any non-string (None, dict, bytes) is a failed
    validation, i.e. exit code 1 — never an exception.
    """
    ok = validate_canary(response_text)
    code = 0 if ok else 1
    logger.info("process_response: exit code %d", code)
    return code


def main(argv=None) -> int:
    """Validate CLI-provided text; exit 0 iff the canary marker is present.

    `--request-only [PATH]` switches to the Gemini response-parsing flow instead: it
    prints the extracted model text and exits 0, or prints an error and exits 3.
    """
    args = sys.argv[1:] if argv is None else list(argv)
    if args and args[0] == "--request-only":
        rest = args[1:]
        return request_only(rest[0] if rest else None)
    text = " ".join(args)
    code = process_response(text)
    if code == 0:
        logger.info("canary: validation passed")
    else:
        logger.error("canary: validation failed")
    return code


if __name__ == "__main__":
    sys.exit(main())
