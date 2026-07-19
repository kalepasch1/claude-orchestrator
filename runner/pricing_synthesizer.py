#!/usr/bin/env python3
"""
pricing_synthesizer.py - Pricing synthesizer with deferred cross-app calls.

Calls ploeh_s2s_bridge to build pricing inputs when PLOEH_S2S_SECRET is set.
Falls back to local mock pricing (1000 basis points markup) when:
- Secret is not configured
- Bridge call fails
- Envelope verification fails

The synthesizer never blocks on cross-app calls; it logs warnings and continues.
"""

import os
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

try:
    from ploeh_s2s_bridge import build_pricing_inputs
except ImportError:
    build_pricing_inputs = None

MOCK_PRICING_MARKUP_BP = 1000
MOCK_PRICING_BASE_INPUT = 1.0
MOCK_PRICING_BASE_OUTPUT = 5.0


def _calculate_mock_pricing() -> Dict[str, Any]:
    """
    Calculate mock pricing with 1000 basis points (10%) markup.

    Returns:
        dict with {input_price, output_price, source: "mock"}
    """
    markup_multiplier = 1.0 + (MOCK_PRICING_MARKUP_BP / 10000.0)
    return {
        "input_price": MOCK_PRICING_BASE_INPUT * markup_multiplier,
        "output_price": MOCK_PRICING_BASE_OUTPUT * markup_multiplier,
        "source": "mock",
    }


def get_pricing_with_fallback() -> Dict[str, Any]:
    """
    Get pricing, attempting S2S bridge first, falling back to mock.

    If PLOEH_S2S_SECRET is configured, attempts to fetch pricing from
    the apparently service via S2S bridge. On any failure, logs warning
    and returns mock pricing. Never raises exceptions.

    Returns:
        dict with {input_price, output_price, source}
        - source is "apparently" if bridge succeeded
        - source is "mock" if fallback used
    """
    secret = os.environ.get("PLOEH_S2S_SECRET", "").strip()

    if not secret:
        logger.debug("PLOEH_S2S_SECRET not configured, using mock pricing")
        return _calculate_mock_pricing()

    try:
        if build_pricing_inputs is None:
            logger.warning("ploeh_s2s_bridge not available, using mock pricing")
            return _calculate_mock_pricing()

        apparently_envelope = _get_apparently_envelope()
        if apparently_envelope is None:
            logger.warning("Could not fetch envelope from apparently, using mock pricing")
            return _calculate_mock_pricing()

        pricing_inputs = build_pricing_inputs(apparently_envelope)
        if pricing_inputs is None:
            logger.warning("S2S bridge failed to process envelope, using mock pricing")
            return _calculate_mock_pricing()

        apparently_price = _build_price_from_inputs(pricing_inputs)
        logger.info(f"Successfully fetched pricing from apparently: {apparently_price}")
        return apparently_price

    except Exception as e:
        logger.warning(f"Unexpected error fetching pricing: {e}, using mock pricing")
        return _calculate_mock_pricing()


def _get_apparently_envelope() -> Optional[Dict[str, Any]]:
    """
    Get envelope from apparently service (placeholder).

    In production, this would fetch an actual envelope from the apparently
    service. For now, returns None (will fall back to mock pricing).

    Returns:
        Envelope dict or None if unavailable
    """
    return None


def _build_price_from_inputs(pricing_inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build pricing dict from apparently inputs.

    Uses risk vectors and trigger specs to calculate final pricing.

    Args:
        pricing_inputs: dict with {risk_vectors, trigger_specs, source}

    Returns:
        dict with {input_price, output_price, source: "apparently"}
    """
    base_input = MOCK_PRICING_BASE_INPUT
    base_output = MOCK_PRICING_BASE_OUTPUT

    risk_vectors = pricing_inputs.get("risk_vectors", {})
    fraud_score = risk_vectors.get("fraud_score", 0)

    multiplier = 1.0 + (fraud_score / 100.0)

    return {
        "input_price": base_input * multiplier,
        "output_price": base_output * multiplier,
        "source": "apparently",
    }


def synthesize_pricing_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Synthesize application config with pricing information.

    Defers cross-app pricing calls behind PLOEH_S2S_SECRET environment variable.
    If the secret is not set or the call fails, uses mock pricing and continues.
    The synthesizer is never blocked by pricing availability.

    Args:
        config: Application configuration dict

    Returns:
        dict with {
            status: "success",
            config: original config,
            pricing: {input_price, output_price, source},
            pricing_source: "apparently" or "mock"
        }

    This function never raises exceptions.
    """
    try:
        pricing = get_pricing_with_fallback()
        pricing_source = pricing.get("source", "mock")

        result = {
            "status": "success",
            "config": config.copy() if config else {},
            "pricing": {
                "input_price": pricing.get("input_price", 1.1),
                "output_price": pricing.get("output_price", 5.5),
                "source": pricing_source,
            },
            "pricing_source": pricing_source,
        }

        return result

    except Exception as e:
        logger.error(f"Unexpected error in synthesize_pricing_config: {e}")
        mock_price = _calculate_mock_pricing()
        return {
            "status": "success",
            "config": config.copy() if config else {},
            "pricing": mock_price,
            "pricing_source": "mock",
            "error": str(e),
        }
