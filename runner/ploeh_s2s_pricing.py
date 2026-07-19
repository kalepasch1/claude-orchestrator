#!/usr/bin/env python3
"""
ploeh_s2s_pricing.py - Deferred PLOEH_S2S cross-app pricing integration.

When PLOEH_S2S_SECRET is set, attempts to fetch current pricing from the
cross-app PLOEH_S2S service. If the secret is missing, unavailable, or the
call fails, falls back to local pricing without blocking the synthesizer.

This allows the synthesizer to ship with a working default while enabling
real-time pricing when the integration is configured.
"""

import os
import json
import threading
import time
from typing import Optional, Dict, Any
import logging
import requests

logger = logging.getLogger(__name__)

# Local fallback pricing (USD per 1M tokens) when PLOEH_S2S_SECRET is not set
# or when the cross-app call fails. Conservative, safe defaults.
LOCAL_PRICE_FALLBACK = {
    "input_price": 3.0,      # USD per 1M input tokens
    "output_price": 15.0,    # USD per 1M output tokens
    "source": "local",
}

# Mutex for thread-safe access to cached pricing
_price_cache_lock = threading.Lock()
_price_cache: Optional[Dict[str, Any]] = None
_cache_timestamp: float = 0.0
_CACHE_TTL = 3600  # Cache for 1 hour


def is_secret_configured() -> bool:
    """Check whether PLOEH_S2S_SECRET environment variable is set."""
    secret = os.environ.get("PLOEH_S2S_SECRET", "").strip()
    return bool(secret)


def _make_s2s_request(secret: str) -> Dict[str, Any]:
    """
    Make HTTP request to PLOEH_S2S service.

    This is a separate function to allow mocking in tests.
    In production, this would make an actual HTTP call to the PLOEH service.

    Args:
        secret: The PLOEH_S2S_SECRET value

    Returns:
        dict with pricing data {input_price, output_price, effective_date, ...}

    Raises:
        ConnectionError: If service is unreachable
        ValueError: If authentication fails
        TimeoutError: If request times out
    """
    # In a real implementation, this would call the actual PLOEH_S2S endpoint
    # For now, we'll implement a basic structure that can be mocked
    endpoint = os.environ.get("PLOEH_S2S_ENDPOINT", "https://ploeh.service.local/pricing")
    headers = {
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(endpoint, headers=headers, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError as e:
        raise ConnectionError(f"PLOEH_S2S service unreachable: {e}") from e
    except requests.exceptions.Timeout as e:
        raise TimeoutError(f"PLOEH_S2S request timeout: {e}") from e
    except requests.exceptions.HTTPError as e:
        if response.status_code == 401:
            raise ValueError(f"PLOEH_S2S authentication failed: invalid secret") from e
        raise ValueError(f"PLOEH_S2S request failed: {e}") from e


def fetch_ploeh_s2s_price() -> Optional[Dict[str, Any]]:
    """
    Fetch current pricing from PLOEH_S2S service if secret is configured.

    Returns:
        dict with pricing data (input_price, output_price, source="ploeh_s2s")
        or None if secret is not configured or call fails

    This function never raises exceptions; failures are logged and None is returned.
    """
    if not is_secret_configured():
        return None

    secret = os.environ.get("PLOEH_S2S_SECRET", "")

    try:
        data = _make_s2s_request(secret)

        # Ensure response has required fields
        if not isinstance(data, dict):
            logger.warning(f"PLOEH_S2S returned non-dict response: {type(data)}")
            return None

        if "input_price" not in data or "output_price" not in data:
            logger.warning(f"PLOEH_S2S response missing required fields: {data.keys()}")
            return None

        # Mark as coming from PLOEH_S2S
        data["source"] = "ploeh_s2s"
        return data

    except (ConnectionError, TimeoutError, ValueError) as e:
        logger.debug(f"PLOEH_S2S pricing fetch failed (will use local fallback): {e}")
        return None
    except Exception as e:
        logger.warning(f"Unexpected error fetching PLOEH_S2S pricing: {e}")
        return None


def get_ploeh_price() -> Dict[str, Any]:
    """
    Get current pricing, trying PLOEH_S2S first, falling back to local.

    Returns:
        dict with {input_price, output_price, source}
        - source is "ploeh_s2s" if cross-app call succeeded
        - source is "local" if using fallback

    This function never raises exceptions and never returns None.
    """
    global _price_cache, _cache_timestamp

    # Check cache (thread-safe)
    with _price_cache_lock:
        now = time.time()
        if _price_cache is not None and (now - _cache_timestamp) < _CACHE_TTL:
            return _price_cache.copy()

    # Try PLOEH_S2S if secret is configured
    price = None
    if is_secret_configured():
        try:
            price = fetch_ploeh_s2s_price()
        except Exception as e:
            logger.debug(f"Exception calling fetch_ploeh_s2s_price: {e}, falling back to local")
            price = None

    # Fall back to local pricing if PLOEH_S2S failed or secret wasn't configured
    if price is None:
        price = LOCAL_PRICE_FALLBACK.copy()

    # Cache the result
    with _price_cache_lock:
        _price_cache = price.copy()
        _cache_timestamp = time.time()

    return price.copy()


def synthesize_with_pricing(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Synthesize application configuration with pricing information.

    Defers cross-app pricing call behind PLOEH_S2S_SECRET environment variable.
    If the secret is not set or the call fails, uses local pricing and continues.
    The synthesizer is never blocked by pricing availability.

    Args:
        config: Application configuration dict

    Returns:
        dict with {
            status: "success" or "failed",
            config: original config,
            pricing: {input_price, output_price, source},
            pricing_source: "ploeh_s2s" or "local"
        }

    This function never raises exceptions.
    """
    try:
        # Get pricing (never blocks, always returns valid price)
        pricing = get_ploeh_price()
        pricing_source = pricing.get("source", "local")

        # Synthesize configuration
        result = {
            "status": "success",
            "config": config.copy() if config else {},
            "pricing": {
                "input_price": pricing.get("input_price", LOCAL_PRICE_FALLBACK["input_price"]),
                "output_price": pricing.get("output_price", LOCAL_PRICE_FALLBACK["output_price"]),
                "source": pricing_source,
            },
            "pricing_source": pricing_source,
        }

        return result

    except Exception as e:
        logger.error(f"Unexpected error in synthesize_with_pricing: {e}")
        return {
            "status": "failed",
            "config": config.copy() if config else {},
            "pricing": LOCAL_PRICE_FALLBACK.copy(),
            "pricing_source": "local",
            "error": str(e),
        }


def invalidate_cache():
    """Clear the pricing cache. Useful for testing."""
    global _price_cache, _cache_timestamp
    with _price_cache_lock:
        _price_cache = None
        _cache_timestamp = 0.0


if __name__ == "__main__":
    # Quick test/demo
    import json

    print("=== PLOEH_S2S Pricing Module Demo ===\n")

    # Test 1: Without secret (uses local)
    os.environ.pop("PLOEH_S2S_SECRET", None)
    invalidate_cache()

    print("1. Without PLOEH_S2S_SECRET (local pricing):")
    print(f"   Secret configured: {is_secret_configured()}")
    price = get_ploeh_price()
    print(f"   Pricing: {json.dumps(price, indent=2)}\n")

    # Test 2: With secret but no endpoint (would fail, falls back)
    os.environ["PLOEH_S2S_SECRET"] = "test-key"
    invalidate_cache()

    print("2. With PLOEH_S2S_SECRET but no service available:")
    print(f"   Secret configured: {is_secret_configured()}")
    price = get_ploeh_price()
    print(f"   Pricing (falls back to local): {json.dumps(price, indent=2)}\n")

    # Test 3: Synthesizer
    print("3. Synthesizer result:")
    result = synthesize_with_pricing({"app_id": "demo", "version": "1.0"})
    print(f"   {json.dumps(result, indent=2)}")
