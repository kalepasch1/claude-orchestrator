#!/usr/bin/env python3
"""
ploeh_s2s_bridge.py - Server-to-server bridge for PLOEH cross-app pricing.

Implements HMAC-SHA256 verification with 300s time window for envelopes
from the apparently service. Ingests risk vectors and trigger specs to
build pricing inputs.

Uses PLOEH_S2S_SECRET for envelope verification and fails gracefully
when secret is missing or verification fails.
"""

import os
import json
import hmac
import hashlib
import time
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

ENVELOPE_TIMEOUT_SECONDS = 300


class HMACVerificationError(Exception):
    """Raised when HMAC signature verification fails."""
    pass


class EnvelopeExpiredError(Exception):
    """Raised when envelope timestamp is outside acceptable window."""
    pass


def _verify_hmac_sha256(
    secret: str, payload: str, signature: str
) -> bool:
    """
    Verify HMAC-SHA256 signature of payload using secret.

    Args:
        secret: The PLOEH_S2S_SECRET used to sign the payload
        payload: The JSON payload string that was signed
        signature: The hex-encoded signature to verify

    Returns:
        True if signature is valid, False otherwise
    """
    expected_sig = hmac.new(
        secret.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected_sig, signature)


def verify_envelope(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """
    Verify and parse an envelope from apparently service.

    Validates:
    - HMAC-SHA256 signature using PLOEH_S2S_SECRET
    - Timestamp is within 300 seconds of current time
    - Required fields present (payload, signature, timestamp)

    Args:
        envelope: dict with {payload, signature, timestamp}

    Returns:
        Parsed payload dict if verification succeeds

    Raises:
        HMACVerificationError: If secret missing or signature invalid
        EnvelopeExpiredError: If timestamp outside 300s window
        ValueError: If envelope format invalid
    """
    secret = os.environ.get("PLOEH_S2S_SECRET", "").strip()
    if not secret:
        raise HMACVerificationError("PLOEH_S2S_SECRET not configured")

    required_fields = ["payload", "signature", "timestamp"]
    missing = [f for f in required_fields if f not in envelope]
    if missing:
        raise ValueError(f"Envelope missing required fields: {missing}")

    timestamp = envelope.get("timestamp", 0)
    now = time.time()
    time_diff = abs(now - timestamp)

    if time_diff > ENVELOPE_TIMEOUT_SECONDS:
        raise EnvelopeExpiredError(
            f"Envelope timestamp {time_diff}s outside {ENVELOPE_TIMEOUT_SECONDS}s window"
        )

    payload_str = json.dumps(envelope["payload"], separators=(",", ":"), sort_keys=True)
    signature = envelope["signature"]

    if not _verify_hmac_sha256(secret, payload_str, signature):
        raise HMACVerificationError("HMAC-SHA256 signature verification failed")

    return envelope["payload"]


def ingest_risk_vectors(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ingest risk vectors from payload.

    Extracts risk vector data like fraud score, latency patterns, error rates.

    Args:
        payload: Parsed envelope payload

    Returns:
        dict with {vectors: {...}, source: "apparently"}
    """
    if payload is None:
        return {"vectors": {}, "source": "apparently"}
    vectors = payload.get("risk_vectors", {})
    return {
        "vectors": vectors,
        "source": "apparently",
    }


def ingest_trigger_specs(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ingest trigger specifications from payload.

    Extracts trigger specs like price adjustment thresholds, alert rules.

    Args:
        payload: Parsed envelope payload

    Returns:
        dict with {specs: {...}, source: "apparently"}
    """
    if payload is None:
        return {"specs": {}, "source": "apparently"}
    specs = payload.get("trigger_specs", {})
    return {
        "specs": specs,
        "source": "apparently",
    }


def build_pricing_inputs(
    envelope: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Verify envelope and build pricing inputs from apparently data.

    Validates HMAC-SHA256 signature and extracts risk vectors + trigger specs.

    Args:
        envelope: Envelope dict with {payload, signature, timestamp}

    Returns:
        dict with {risk_vectors, trigger_specs, source} if successful
        None if verification fails or secret not configured

    This function never raises exceptions; failures are logged and None returned.
    """
    try:
        payload = verify_envelope(envelope)

        if payload is None:
            logger.debug("S2S bridge received None payload after verification, using defaults")
            return {
                "risk_vectors": {},
                "trigger_specs": {},
                "source": "apparently",
                "payload_id": "unknown",
            }

        risk_data = ingest_risk_vectors(payload)
        trigger_data = ingest_trigger_specs(payload)

        return {
            "risk_vectors": risk_data["vectors"],
            "trigger_specs": trigger_data["specs"],
            "source": "apparently",
            "payload_id": payload.get("id", "unknown"),
        }

    except HMACVerificationError as e:
        logger.warning(f"S2S bridge HMAC verification failed: {e}")
        return None
    except EnvelopeExpiredError as e:
        logger.warning(f"S2S bridge envelope expired: {e}")
        return None
    except ValueError as e:
        logger.warning(f"S2S bridge envelope format invalid: {e}")
        return None
    except Exception as e:
        logger.warning(f"S2S bridge unexpected error: {e}")
        return None
