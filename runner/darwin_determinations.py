#!/usr/bin/env python3
"""
darwin_determinations.py - Determinations module with mock/live-model hybrid execution.

Provides a `determine()` function that executes with one of two paths:
  1. Mock (default): Returns a deterministic, hardcoded result
  2. Live (conditional): Calls the Claude API via the Anthropic SDK when DARWIN_LIVE=1

Environment variables:
  - DARWIN_LIVE: Set to "1" to enable live model path (default: unset/0)
  - DARWIN_API_KEY: Optional API key (if unset, uses ambient credentials)
  - DARWIN_MODEL: Optional model ID (default: claude-haiku-4-5-20251001)
"""
import os
import logging

log = logging.getLogger(__name__)

# Default model if not specified
DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def _mock_determine():
    """Mock/default implementation. Always returns a deterministic result."""
    return "MOCK_DETERMINATION_RESULT"


def _live_determine(model=None):
    """Live model path. Calls the Anthropic API and returns result.

    Args:
        model: Model ID to use (if None, reads from DARWIN_MODEL env var)

    Returns:
        str: Result from live model, or mock result on error
    """
    if model is None:
        model = os.environ.get("DARWIN_MODEL", DEFAULT_MODEL)

    api_key = os.environ.get("DARWIN_API_KEY")

    try:
        from anthropic import Anthropic

        # Create client (uses ANTHROPIC_API_KEY env var if DARWIN_API_KEY not set)
        client_kwargs = {}
        if api_key:
            client_kwargs["api_key"] = api_key

        client = Anthropic(**client_kwargs)

        # Make a simple determination call
        message = client.messages.create(
            model=model,
            max_tokens=100,
            messages=[
                {"role": "user", "content": "Provide a brief determination or judgment."}
            ]
        )

        # Extract text from response
        if message.content and len(message.content) > 0:
            return message.content[0].text
        return "LIVE_DETERMINATION_EMPTY"

    except Exception as exc:
        log.error("[DARWIN] Live model call failed; falling back to mock. Error: %s: %s",
                  type(exc).__name__, str(exc))
        return _mock_determine()


def determine():
    """
    Main determination function. Executes with mock or live model path based on env vars.

    Public signature takes no required parameters for backwards compatibility.

    Environment variables:
      - DARWIN_LIVE: "1" to enable live path (default: unset or "0")
      - DARWIN_API_KEY: Optional API key (uses ambient ANTHROPIC_API_KEY if unset)
      - DARWIN_MODEL: Optional model ID (default: claude-haiku-4-5-20251001)

    Returns:
        str: Determination result
    """
    # Check if live path is enabled
    live_enabled = os.environ.get("DARWIN_LIVE", "0").strip() == "1"

    if not live_enabled:
        return _mock_determine()

    # Live path is enabled
    model = os.environ.get("DARWIN_MODEL", DEFAULT_MODEL)
    return _live_determine(model=model)
