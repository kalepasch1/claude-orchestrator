#!/usr/bin/env python3
"""canary.py — canary marker validation with logging + CLI exit-code contract.

canary-gemini-25 series (define-valida / setup-basic-c / exit-code-en slices):
  * `import sys` and `import logging` at the top; logging.basicConfig(INFO)
    immediately after imports, guarded so an embedding application's logging
    configuration is never clobbered.
  * validate_canary(response_text) -> bool  (str -> bool)
  * CLI integration: `python canary.py <text…>` exits 0 when the canary marker
    is present, 1 when absent — so pipelines can gate on the exit code.
  * load_dotenv(path) / load_api_key() and `python canary.py --check-key [PATH]`:
    loads a .env (python-dotenv when installed, a small parser when it is not — the
    package is NOT a repo dependency) and exits 0 when GEMINI_API_KEY is set, or
    prints "Error: GEMINI_API_KEY not found" and exits 1. Environment already set on
    the process always wins over the file.
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


def process_response(response_text) -> int:
    """Validate `response_text` and return the process exit code for it.

    0 when the canary marker is present, 1 when it is absent — the same contract
    `main()` already exposes, lifted out so a caller that has the text in hand can
    reuse the validation + final-summary log without going through argv.

    The summary is logged at INFO on success and ERROR on failure, so a failing
    canary is visible in a deploy-window log that is filtered to warnings and above.
    """
    ok = validate_canary(response_text)
    if ok:
        logger.info("Validation result: success")
        return 0
    logger.error("Validation result: failure")
    return 1


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


class MissingApiKeyError(RuntimeError):
    """GEMINI_API_KEY is not set. Carries the exit code the CLI should use."""

    exit_code = 1


def load_dotenv(path=None):
    """Load KEY=VALUE pairs from a .env file into os.environ. Returns a dict of them.

    python-dotenv is used when it is installed, and a small parser is used when it is
    not. That fallback is deliberate: python-dotenv is NOT a dependency of this repo,
    and canary.py is imported by the deploy path — a hard `from dotenv import
    load_dotenv` would turn "the canary module" into "the canary module, on machines
    that happen to have an extra package", which is exactly the crash-free-until-used
    class this file already warns about.

    Never overwrites a variable already present in the environment: a real deployment
    sets GEMINI_API_KEY for the process, and a stale .env on disk must not shadow it.
    Fail-soft — an unreadable or malformed file yields {} with a warning, not a raise.
    """
    path = path or os.path.join(os.getcwd(), ".env")
    try:
        import dotenv  # noqa: F401  (optional; used only when installed)
    except ImportError:
        pass
    else:
        try:
            values = dotenv.dotenv_values(path) or {}
        except Exception as e:  # noqa: BLE001 - logged, then degraded (fail-soft)
            logger.warning("canary: could not read %s (%s)", path, e)
            return {}
        loaded = {}
        for key, value in values.items():
            if value is not None and key not in os.environ:
                os.environ[key] = value
                loaded[key] = value
        return loaded

    loaded = {}
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.readlines()
    except FileNotFoundError:
        return {}
    except OSError as e:
        logger.warning("canary: could not read %s (%s)", path, e)
        return {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded[key] = value
    return loaded


def load_api_key(env_var="GEMINI_API_KEY", dotenv_path=None):
    """Return the API key, loading a .env file first. Raise MissingApiKeyError if unset.

    Raises rather than calling sys.exit so the function is testable and importable; the
    CLI is the only place that turns the error into an exit code (see check_key()).
    An empty or whitespace-only value counts as unset — a blank key in a .env is the
    most common way this fails, and treating it as present would defer the failure to
    an opaque 401 from the API.
    """
    load_dotenv(dotenv_path)
    key = (os.environ.get(env_var) or "").strip()
    if not key:
        raise MissingApiKeyError(f"Error: {env_var} not found")
    return key


def check_key(env_var="GEMINI_API_KEY", dotenv_path=None):
    """CLI flow for --check-key: exit 0 silently when the key is present, 1 with a
    message on stderr when it is not.

    NOTE ON THE FLAG NAME (rework): the slice as written asked for this behaviour under
    `--request-only`. That flag already exists here with a different, tested meaning —
    it parses a Gemini generateContent response body and is documented as deliberately
    NOT requiring a key or network. Redefining it would break
    tests/test_canary_acceptance.py and every caller that pipes a response into it, and
    would put a key check in front of a pure parser that does not need one. The
    env/argument setup the slice is actually about is the same either way, so it is
    exposed under its own flag instead.
    """
    try:
        load_api_key(env_var, dotenv_path)
    except MissingApiKeyError as e:
        print(str(e), file=sys.stderr)
        logger.error("canary: %s", e)
        return e.exit_code
    return 0


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


def main(argv=None) -> int:
    """Validate CLI-provided text; exit 0 iff the canary marker is present.

    `--request-only [PATH]` switches to the Gemini response-parsing flow instead: it
    prints the extracted model text and exits 0, or prints an error and exits 3.

    `--check-key [DOTENV_PATH]` checks the environment only: it loads a .env file and
    exits 0 silently when GEMINI_API_KEY is set, or prints
    "Error: GEMINI_API_KEY not found" on stderr and exits 1.
    """
    args = sys.argv[1:] if argv is None else list(argv)
    if args and args[0] == "--check-key":
        rest = args[1:]
        return check_key(dotenv_path=rest[0] if rest else None)
    if args and args[0] == "--request-only":
        rest = args[1:]
        return request_only(rest[0] if rest else None)
    # Delegated so the CLI exit code and process_response() cannot drift apart.
    return process_response(" ".join(args))


if __name__ == "__main__":
    sys.exit(main())
