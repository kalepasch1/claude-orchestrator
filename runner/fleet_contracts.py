"""fleet_contracts — the single declaration of what fleet_config may hold.

The rule "only secret-free tuning knobs go fleet-wide" was, until now, written
down twice: once as `_SAFE_PREFIXES`/`_DENY_MARKERS` in fleet_control.py, and
again as an inline regex fallback inside db._guard_fleet_config. Two copies of a
security predicate drift, and the 2026-08-02 incident is what that costs —
VERCEL_TOKEN, GITHUB_PAT, OPENAI_API_KEY and GEMINI_API_KEY were stored in
fleet_config in plaintext because a dozen writers never consulted either copy.

This module is the one place the contract is stated. It is data plus two pure
predicates: no I/O, no imports from the control plane, so anything may depend on
it without a cycle and a writer has no excuse to reimplement the check.

Fails CLOSED. An unrecognised key is refused, not allowed — the asymmetry is not
close: refusing a legitimate knob costs one config change, admitting a
credential costs a key rotation across every provider.
"""
import functools

# Substrings that make a key credential-shaped. Presence of ANY of these refuses
# the key outright, whatever its prefix — a knob named ORCH_OPENAI_API_KEY is
# still a secret.
DENY_MARKERS = (
    "KEY", "SECRET", "TOKEN", "PASSWORD", "PWD", "CREDENTIAL", "PAT",
    "PRIVATE", "AUTH_HEADER", "COOKIE", "SESSION_ID", "BEARER",
)

# Prefixes whose families are secret-free tuning knobs. Kept in sync with
# fleet_control._SAFE_PREFIXES; that module now imports from here rather than
# keeping a second list.
SAFE_PREFIXES = (
    "ORCH_", "MAX_PARALLEL", "PER_TASK_GB", "RAM_FLOOR_GB", "RAM_", "RELEASE_",
    "QUEUE_", "CONT_", "JANITOR_", "REMEDIATION_", "DEFAULT_TEST_CMD",
    "TASK_TIMEOUT", "ENABLE_", "SESSION_", "ACCOUNT_COOLDOWN", "MERGE_",
    "DEPLOY_", "INTEGRATE_", "COST_", "OLLAMA_", "COMMITTEE_", "LEGAL_DOCKET",
    "SEMANTIC_DEDUPE", "SWARM_", "CADE_",
)

# The declarative schema. `FLEET_CONFIG_SCHEMA` is the contract other modules and
# tests assert against, so a change to the policy is a change to one literal.
FLEET_CONFIG_SCHEMA = {
    "version": 1,
    "table": "fleet_config",
    "description": (
        "Fleet-wide, secret-free tuning knobs. Every machine converges on these. "
        "Credentials are per-machine environment only and MUST NOT be stored here."
    ),
    "safe_prefixes": SAFE_PREFIXES,
    "deny_markers": DENY_MARKERS,
    "fail_closed": True,
    # Named explicitly so the exclusion is documented rather than folklore: the
    # PAT VALUE lives in local env; only the "auth is required" signal is
    # fleet-wide.
    "explicit_exclusions": ("ORCH_GIT_PAT",),
    "incident": "2026-08-02 plaintext-credential incident",
}


def is_safe_config_key(key) -> bool:
    """True only when `key` is a secret-free fleet-wide knob. Fails closed.

    Deny markers are checked BEFORE the prefix allowlist, so a credential cannot
    smuggle itself in behind a permitted prefix.
    """
    try:
        if not key or not isinstance(key, str):
            return False
        upper = key.strip().upper()
        if not upper:
            return False
        if upper in {e.upper() for e in FLEET_CONFIG_SCHEMA["explicit_exclusions"]}:
            return False
        if any(marker in upper for marker in DENY_MARKERS):
            return False
        return any(upper.startswith(prefix) for prefix in SAFE_PREFIXES)
    except Exception:
        # An exception while deciding is not permission.
        return False


def fail_soft(default=None, on_error=None):
    """Decorate a function so an unexpected error returns `default` instead of raising.

    The repo convention is that a public helper degrades rather than wedging the
    runner. This makes that convention importable instead of hand-rolled per
    module.

    NOTE: deliberately NOT used on `is_safe_config_key`. A security predicate
    that swallows its own failure and returns a truthy default is how a guard
    silently stops guarding; that function fails closed by returning False.
    """
    def decorate(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                if on_error is not None:
                    try:
                        on_error(exc)
                    except Exception:
                        pass
                return default
        return wrapper
    return decorate


def assert_safe_config_key(key) -> None:
    """Raise ValueError when `key` may not be stored fleet-wide."""
    if not is_safe_config_key(key):
        raise ValueError(
            f"[fleet-contracts] refusing key {key!r} for fleet_config: not a "
            f"secret-free tuning knob (see FLEET_CONFIG_SCHEMA). Credentials "
            f"belong in per-machine environment only."
        )


def describe() -> dict:
    """A copy of the contract, safe to log or serialise."""
    return dict(FLEET_CONFIG_SCHEMA)
