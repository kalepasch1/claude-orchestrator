"""Canonical, value-safe credential discovery for every model provider.

Provider integrations historically checked one spelling while credential setup
accepted another (notably XAI_API_KEY versus GROK_API_KEY/XAPI_KEY).  This module
keeps aliases in one place and mirrors a discovered alias into the canonical env
name in-process, without logging or persisting secret values.
"""
import os


ALIASES = {
    "openai": ("OPENAI_API_KEY",),
    "google": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "gemini": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "groq": ("GROQ_API_KEY",),
    "xai": ("XAI_API_KEY", "GROK_API_KEY", "XAPI_KEY"),
    "grok": ("XAI_API_KEY", "GROK_API_KEY", "XAPI_KEY"),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "claude": ("ANTHROPIC_API_KEY",),
}

CANONICAL_ENV = {
    "google": "GOOGLE_API_KEY", "gemini": "GOOGLE_API_KEY",
    "xai": "XAI_API_KEY", "grok": "XAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY", "claude": "ANTHROPIC_API_KEY",
}


def env_names(provider):
    return ALIASES.get(str(provider or "").lower(), ())


def get(provider, default=""):
    for name in env_names(provider):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def has(provider):
    return bool(get(provider))


def activate_aliases():
    """Expose aliases under the canonical name expected by legacy integrations."""
    activated = []
    for provider, canonical in CANONICAL_ENV.items():
        if os.environ.get(canonical, "").strip():
            continue
        value = get(provider)
        if value:
            os.environ[canonical] = value
            activated.append(provider)
    return sorted(set(activated))
