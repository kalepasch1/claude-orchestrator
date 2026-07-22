#!/usr/bin/env python3
"""
darwin_determinations.py - Route queries through mock/deterministic or live-model logic.

Supports environment-gated live-model path via DARWIN_LIVE/DARWIN_API_KEY with fallback
to deterministic mock path on any error. Thread-safe, fail-soft error handling.
"""
import os
import logging
import threading

log = logging.getLogger(__name__)
_lock = threading.Lock()


def _should_use_live_path() -> bool:
    """Check if live-model path should be used based on env vars."""
    darwin_live = os.environ.get("DARWIN_LIVE", "").strip()
    darwin_api_key = os.environ.get("DARWIN_API_KEY", "").strip()
    return bool(darwin_live or darwin_api_key)


def _mock_path(query: str, context: dict = None) -> str:
    """Deterministic/mock path — reproducible output, no model invocation."""
    try:
        return query.upper() if query else ""
    except Exception:
        return ""


def _live_path(query: str, context: dict = None) -> str:
    """Live-model path — invoke Claude via claude_cli.run(), fail-soft to mock on error."""
    try:
        import claude_cli
    except ImportError:
        log.warning("claude_cli not available; falling back to mock path")
        return _mock_path(query, context)

    model = os.environ.get("DARWIN_MODEL", "claude-opus-4-8").strip()

    # Build prompt from query and context
    prompt = query
    if context:
        try:
            context_str = "\n".join(f"{k}: {v}" for k, v in context.items())
            prompt = f"{query}\n\nContext:\n{context_str}"
        except Exception:
            pass

    try:
        result = claude_cli.run(
            prompt=prompt,
            model=model,
            timeout=30
        )

        if result.get("returncode") == 0:
            return result.get("text", "")
        else:
            log.warning(
                "Live-model returned non-zero exit code %s; falling back to mock path",
                result.get("returncode")
            )
            return _mock_path(query, context)

    except Exception as exc:
        log.warning(
            "Live-model invocation failed (%s: %s); falling back to mock path",
            type(exc).__name__, str(exc)
        )
        return _mock_path(query, context)


def determine(query: str, context: dict = None) -> str:
    """
    Determine a routing decision or classification.

    Routes through mock (deterministic) or live-model path based on environment
    variables. Falls back to mock path on any error.

    Args:
        query: Input string to determine
        context: Optional dict with additional context

    Returns:
        str: Deterministic result (mock path) or live-model response (live path)
    """
    try:
        if not query:
            return ""

        with _lock:
            if _should_use_live_path():
                return _live_path(query, context)
            else:
                return _mock_path(query, context)
    except Exception:
        return _mock_path(query, context)
