#!/usr/bin/env python3
"""
pricing_config.py - the pricing configuration the economic scheduler loads.

economic_scheduler.py already reads its own knobs straight off os.environ at
import time (ENABLED, ROI_THRESHOLD, REVENUE_CRITICAL_LANE_SIZE). That is fine
for three scalars and wrong for a pricing table: import-time reads cannot be
re-read after a fleet_config push, and a malformed value would raise during
import and take the whole scheduler down rather than degrade.

So this module is a FUNCTION, not a constant block. Every call re-reads the
environment, which is what makes an ORCH_-prefixed fleet push take effect
without a restart.

Conventions this follows, from CLAUDE.md:
  * fail-soft - never raises. A malformed override logs a diagnostic and falls
    back to the default for THAT key only; one bad value cannot blank the table.
  * env-var configuration - every knob is an ORCH_-prefixed variable, so it is
    fleet-pushable through fleet_control.py.
  * no hardcoded secrets - these are prices and limits; nothing here is a
    credential, and no key is read from anywhere but the environment.
  * module-level singleton with module-level functions delegating to it.
"""
import copy
import json
import os
import threading

#: Defaults. Deliberately conservative: if the environment says nothing, the
#: scheduler still gets a complete, usable table rather than an empty dict.
DEFAULT_TIERS = {"free": 0.0, "pro": 199.0, "scale": 999.0}
DEFAULT_RATE_LIMITS = {"free": 100, "pro": 10000, "scale": 100000}
DEFAULT_TTL_SECONDS = 3600

#: Every knob is ORCH_-prefixed so fleet_control.py can push it fleet-wide.
ENV_TIERS = "ORCH_PRICING_TIERS"
ENV_RATE_LIMITS = "ORCH_PRICING_RATE_LIMITS"
ENV_TTL = "ORCH_PRICING_TTL_SECONDS"

REQUIRED_KEYS = ("tiers", "rate_limits", "ttl_seconds")

# --- Pricing MODEL -----------------------------------------------------------
# The table above answers "what does each plan cost". The model answers "how is a
# customer charged at all": a flat rate, a tiered ladder, or metered usage. The
# economic scheduler's revenue prediction needs the second question answered
# separately, because the same tier table means very different revenue under a
# flat subscription than under per-unit metering.
#
# Defaults are deliberately ZERO-VALUED, not invented: an unconfigured fleet must
# predict no revenue rather than a plausible-looking number nobody chose.

MODEL_FLAT = "flat"
MODEL_TIERED = "tiered"
MODEL_USAGE_BASED = "usage_based"
PRICING_MODELS = (MODEL_FLAT, MODEL_TIERED, MODEL_USAGE_BASED)

DEFAULT_PRICING_MODEL = MODEL_FLAT
DEFAULT_FLAT = {"rate": 0.0}
DEFAULT_TIERED = {"tiers": []}
DEFAULT_USAGE_BASED = {"rates": {}}

ENV_MODEL = "ORCH_PRICING_MODEL"
ENV_MODEL_FLAT = "ORCH_PRICING_MODEL_FLAT"
ENV_MODEL_TIERED = "ORCH_PRICING_MODEL_TIERED"
ENV_MODEL_USAGE_BASED = "ORCH_PRICING_MODEL_USAGE_BASED"

MODEL_REQUIRED_KEYS = ("model", MODEL_FLAT, MODEL_TIERED, MODEL_USAGE_BASED)


def _json_map(env_name, default, value_cast):
    """Read a JSON object override for one key. Never raises.

    Returns a COPY of `default` on anything unusable — absent, blank, malformed
    JSON, a JSON scalar/array where an object was required, or a value that will
    not cast. Falling back per-key (rather than per-table) means one bad
    override cannot blank the rest of the configuration.
    """
    raw = os.environ.get(env_name)
    if not raw or not raw.strip():
        return dict(default)
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict) or not parsed:
            raise ValueError(f"expected a non-empty JSON object, got {type(parsed).__name__}")
        return {str(k): value_cast(v) for k, v in parsed.items()}
    except Exception as exc:
        # Diagnostic before the swallow: a silent fallback here would show up
        # later as mispriced work with no trace of why.
        print(f"[pricing_config] {env_name} unusable ({exc}); using defaults", flush=True)
        return dict(default)


def _positive_int(env_name, default):
    """Read an int override. Never raises. Rejects non-positive values."""
    raw = os.environ.get(env_name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = int(str(raw).strip())
        if value <= 0:
            raise ValueError(f"must be positive, got {value}")
        return value
    except Exception as exc:
        print(f"[pricing_config] {env_name} unusable ({exc}); using default {default}", flush=True)
        return default


def _json_shape(env_name, default):
    """Read a JSON object override whose inner shape is caller-defined. Never raises.

    Unlike _json_map this does not cast values, because a model sub-config holds
    mixed types (a float rate, a list of tier dicts, a map of unit rates). It still
    falls back per-key, so one malformed model cannot blank the other two.
    """
    raw = os.environ.get(env_name)
    if not raw or not str(raw).strip():
        return copy.deepcopy(default)
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError(f"expected a JSON object, got {type(parsed).__name__}")
        return parsed
    except Exception as exc:
        print(f"[pricing_config] {env_name} unusable ({exc}); using defaults", flush=True)
        return copy.deepcopy(default)


def _model_name(env_name, default):
    """Read the active model name. Never raises. An unknown name falls back."""
    raw = (os.environ.get(env_name) or "").strip().lower()
    if not raw:
        return default
    if raw not in PRICING_MODELS:
        print(f"[pricing_config] {env_name}={raw!r} is not one of {PRICING_MODELS}; "
              f"using default {default!r}", flush=True)
        return default
    return raw


def _load_pricing_model_config():
    """Build the pricing-model configuration from the environment. Never raises.

    Always returns every key in MODEL_REQUIRED_KEYS, so a consumer can index the
    result without guarding — the same contract load_pricing_config() offers for
    the price table.
    """
    return {
        "model": _model_name(ENV_MODEL, DEFAULT_PRICING_MODEL),
        MODEL_FLAT: _json_shape(ENV_MODEL_FLAT, DEFAULT_FLAT),
        MODEL_TIERED: _json_shape(ENV_MODEL_TIERED, DEFAULT_TIERED),
        MODEL_USAGE_BASED: _json_shape(ENV_MODEL_USAGE_BASED, DEFAULT_USAGE_BASED),
    }


def load_pricing_model_config(refresh=True):
    """Return the pricing-model configuration. Never raises.

    `refresh` mirrors load_pricing_config(): True re-reads the environment so a
    fleet-pushed ORCH_PRICING_MODEL* change takes effect without a restart.
    """
    try:
        return _store.load_model(refresh=refresh)
    except Exception as exc:
        print(f"[pricing_config] model load failed ({exc}); using defaults", flush=True)
        return {
            "model": DEFAULT_PRICING_MODEL,
            MODEL_FLAT: copy.deepcopy(DEFAULT_FLAT),
            MODEL_TIERED: copy.deepcopy(DEFAULT_TIERED),
            MODEL_USAGE_BASED: copy.deepcopy(DEFAULT_USAGE_BASED),
        }


def active_pricing_model(config=None):
    """(name, sub_config) for whichever model is active. Never raises."""
    config = config or load_pricing_model_config()
    name = config.get("model") or DEFAULT_PRICING_MODEL
    if name not in PRICING_MODELS:
        name = DEFAULT_PRICING_MODEL
    return name, copy.deepcopy(config.get(name) or {})


def _isolate(config):
    """Return a copy the caller cannot use to mutate the cache.

    dict(config) is NOT enough: it is shallow, so `tiers` and `rate_limits`
    would still be the cached objects and a caller doing
    `cfg["tiers"]["x"] = 1` would silently rewrite the shared table for every
    later reader. Only visible on the refresh=False path, which is exactly the
    hot-loop path where it would do the most damage.
    """
    return {
        "tiers": dict(config["tiers"]),
        "rate_limits": dict(config["rate_limits"]),
        "ttl_seconds": config["ttl_seconds"],
    }


class PricingConfigStore:
    """Thread-safe holder. Callers use the module-level functions, not this."""

    def __init__(self):
        self._lock = threading.Lock()
        self._cached = None
        self._cached_model = None

    def load_model(self, refresh=False):
        """Cached pricing-model config. Deep-copied out so callers cannot mutate it."""
        with self._lock:
            if self._cached_model is None or refresh:
                self._cached_model = _load_pricing_model_config()
            return copy.deepcopy(self._cached_model)

    def load(self, refresh=False):
        with self._lock:
            if self._cached is not None and not refresh:
                return _isolate(self._cached)
            config = {
                "tiers": _json_map(ENV_TIERS, DEFAULT_TIERS, float),
                "rate_limits": _json_map(ENV_RATE_LIMITS, DEFAULT_RATE_LIMITS, int),
                "ttl_seconds": _positive_int(ENV_TTL, DEFAULT_TTL_SECONDS),
            }
            self._cached = config
            return _isolate(config)

    def invalidate(self):
        with self._lock:
            self._cached = None
            self._cached_model = None


_store = PricingConfigStore()


def load_pricing_config(refresh=True):
    """Return the pricing configuration. Never raises.

    Always contains every key in REQUIRED_KEYS, so a consumer can index the
    result without guarding — an empty or partial dict here would push the
    failure into the scheduler, which is the opposite of fail-soft.

    `refresh` defaults to True so a fleet-pushed ORCH_PRICING_* change is picked
    up on the next call rather than at the next process restart. Pass
    refresh=False in a hot loop to use the cached copy.
    """
    try:
        return _store.load(refresh=refresh)
    except Exception as exc:
        print(f"[pricing_config] load failed ({exc}); using defaults", flush=True)
        return {
            "tiers": dict(DEFAULT_TIERS),
            "rate_limits": dict(DEFAULT_RATE_LIMITS),
            "ttl_seconds": DEFAULT_TTL_SECONDS,
        }


def invalidate():
    """Drop the cached copy so the next load re-reads the environment."""
    _store.invalidate()


if __name__ == "__main__":
    print(json.dumps({"table": load_pricing_config(),
                      "pricing_model": load_pricing_model_config()},
                     indent=2, sort_keys=True))
