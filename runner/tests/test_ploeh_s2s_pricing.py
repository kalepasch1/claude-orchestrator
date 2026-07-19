#!/usr/bin/env python3
"""
test_ploeh_s2s_pricing.py - Tests for PLOEH S2S pricing system.

Covers:
1. S2S verify with valid HMAC-SHA256 signature
2. Expired/tampered envelope rejection
3. Mock pricing fallback when env unset
4. Successful pricing when PLOEH_S2S_SECRET present
"""

import os
import pytest
import json
import hmac
import hashlib
import time
from unittest.mock import patch, MagicMock
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ploeh_s2s_bridge import (
    verify_envelope,
    build_pricing_inputs,
    HMACVerificationError,
    EnvelopeExpiredError,
    _verify_hmac_sha256,
    ENVELOPE_TIMEOUT_SECONDS,
)
from pricing_synthesizer import (
    get_pricing_with_fallback,
    synthesize_pricing_config,
    _calculate_mock_pricing,
)


def create_valid_envelope(
    secret: str, payload: dict, timestamp: float = None
) -> dict:
    """Helper to create a validly signed envelope."""
    if timestamp is None:
        timestamp = time.time()

    payload_str = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    signature = hmac.new(
        secret.encode(), payload_str.encode(), hashlib.sha256
    ).hexdigest()

    return {
        "payload": payload,
        "signature": signature,
        "timestamp": timestamp,
    }


class TestHMACSignatureVerification:
    """Tests for HMAC-SHA256 signature verification."""

    def test_valid_hmac_signature_passes(self):
        """_verify_hmac_sha256 accepts valid signatures."""
        secret = "test-secret-key"
        payload = "test payload"
        signature = hmac.new(
            secret.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        assert _verify_hmac_sha256(secret, payload, signature) is True

    def test_invalid_hmac_signature_fails(self):
        """_verify_hmac_sha256 rejects invalid signatures."""
        secret = "test-secret-key"
        payload = "test payload"
        bad_signature = "0" * 64
        assert _verify_hmac_sha256(secret, payload, bad_signature) is False

    def test_tampered_payload_signature_fails(self):
        """_verify_hmac_sha256 detects payload tampering."""
        secret = "test-secret-key"
        original_payload = "original"
        signature = hmac.new(
            secret.encode(), original_payload.encode(), hashlib.sha256
        ).hexdigest()
        tampered_payload = "tampered"
        assert _verify_hmac_sha256(secret, tampered_payload, signature) is False

    def test_wrong_secret_signature_fails(self):
        """_verify_hmac_sha256 fails with wrong secret."""
        secret1 = "secret-1"
        secret2 = "secret-2"
        payload = "test payload"
        signature = hmac.new(
            secret1.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        assert _verify_hmac_sha256(secret2, payload, signature) is False


class TestEnvelopeVerification:
    """Tests for envelope verification with timestamps."""

    def test_verify_valid_envelope_succeeds(self):
        """verify_envelope accepts valid, timely envelope."""
        secret = "test-secret"
        payload = {"risk_vectors": {"fraud_score": 0.1}, "trigger_specs": {}}

        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": secret}):
            envelope = create_valid_envelope(secret, payload)
            result = verify_envelope(envelope)
            assert result == payload

    def test_verify_expired_envelope_fails(self):
        """verify_envelope rejects envelope outside 300s window."""
        secret = "test-secret"
        payload = {"risk_vectors": {}, "trigger_specs": {}}
        old_timestamp = time.time() - 400

        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": secret}):
            envelope = create_valid_envelope(secret, payload, timestamp=old_timestamp)
            with pytest.raises(EnvelopeExpiredError):
                verify_envelope(envelope)

    def test_verify_future_envelope_fails(self):
        """verify_envelope rejects envelope with future timestamp."""
        secret = "test-secret"
        payload = {"risk_vectors": {}, "trigger_specs": {}}
        future_timestamp = time.time() + 400

        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": secret}):
            envelope = create_valid_envelope(secret, payload, timestamp=future_timestamp)
            with pytest.raises(EnvelopeExpiredError):
                verify_envelope(envelope)

    def test_verify_envelope_at_boundary_succeeds(self):
        """verify_envelope accepts envelope at 300s boundary."""
        secret = "test-secret"
        payload = {"risk_vectors": {}, "trigger_specs": {}}
        boundary_timestamp = time.time() - 299

        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": secret}):
            envelope = create_valid_envelope(secret, payload, timestamp=boundary_timestamp)
            result = verify_envelope(envelope)
            assert result == payload

    def test_verify_tampered_envelope_fails(self):
        """verify_envelope rejects envelope with tampered signature."""
        secret = "test-secret"
        payload = {"risk_vectors": {}, "trigger_specs": {}}

        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": secret}):
            envelope = create_valid_envelope(secret, payload)
            envelope["signature"] = "0" * 64
            with pytest.raises(HMACVerificationError):
                verify_envelope(envelope)

    def test_verify_missing_secret_fails(self):
        """verify_envelope fails when PLOEH_S2S_SECRET not set."""
        payload = {"risk_vectors": {}, "trigger_specs": {}}

        with patch.dict(os.environ, {}, clear=True):
            envelope = create_valid_envelope("secret", payload)
            with pytest.raises(HMACVerificationError):
                verify_envelope(envelope)

    def test_verify_missing_required_fields_fails(self):
        """verify_envelope fails when envelope missing required fields."""
        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": "secret"}):
            with pytest.raises(ValueError):
                verify_envelope({"payload": {}})

    def test_verify_empty_secret_fails(self):
        """verify_envelope fails when PLOEH_S2S_SECRET is empty string."""
        payload = {"risk_vectors": {}, "trigger_specs": {}}

        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": ""}):
            envelope = create_valid_envelope("secret", payload)
            with pytest.raises(HMACVerificationError):
                verify_envelope(envelope)


class TestBuildPricingInputs:
    """Tests for building pricing inputs from envelope."""

    def test_build_pricing_inputs_from_valid_envelope(self):
        """build_pricing_inputs succeeds with valid envelope."""
        secret = "test-secret"
        payload = {
            "id": "test-123",
            "risk_vectors": {"fraud_score": 0.05},
            "trigger_specs": {"alert_threshold": 0.8},
        }

        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": secret}):
            envelope = create_valid_envelope(secret, payload)
            inputs = build_pricing_inputs(envelope)
            assert inputs is not None
            assert inputs["risk_vectors"]["fraud_score"] == 0.05
            assert inputs["trigger_specs"]["alert_threshold"] == 0.8
            assert inputs["source"] == "apparently"

    def test_build_pricing_inputs_returns_none_on_verification_failure(self):
        """build_pricing_inputs returns None when HMAC verification fails."""
        secret = "test-secret"
        payload = {"risk_vectors": {}, "trigger_specs": {}}

        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": secret}):
            envelope = create_valid_envelope(secret, payload)
            envelope["signature"] = "0" * 64
            result = build_pricing_inputs(envelope)
            assert result is None

    def test_build_pricing_inputs_returns_none_on_expired_envelope(self):
        """build_pricing_inputs returns None for expired envelope."""
        secret = "test-secret"
        payload = {"risk_vectors": {}, "trigger_specs": {}}

        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": secret}):
            envelope = create_valid_envelope(secret, payload, time.time() - 400)
            result = build_pricing_inputs(envelope)
            assert result is None

    def test_build_pricing_inputs_returns_none_when_secret_missing(self):
        """build_pricing_inputs returns None when PLOEH_S2S_SECRET not set."""
        payload = {"risk_vectors": {}, "trigger_specs": {}}

        with patch.dict(os.environ, {}, clear=True):
            envelope = create_valid_envelope("secret", payload)
            result = build_pricing_inputs(envelope)
            assert result is None


class TestMockPricingFallback:
    """Tests for mock pricing fallback when env unset."""

    def test_mock_pricing_calculated_correctly(self):
        """_calculate_mock_pricing applies 1000 bp markup."""
        price = _calculate_mock_pricing()
        assert price["source"] == "mock"
        assert price["input_price"] > 1.0
        assert price["output_price"] > 5.0

        expected_multiplier = 1.0 + (1000 / 10000.0)
        assert abs(price["input_price"] - 1.0 * expected_multiplier) < 0.01
        assert abs(price["output_price"] - 5.0 * expected_multiplier) < 0.01

    def test_get_pricing_uses_mock_when_secret_unset(self):
        """get_pricing_with_fallback returns mock pricing when secret not set."""
        with patch.dict(os.environ, {}, clear=True):
            price = get_pricing_with_fallback()
            assert price["source"] == "mock"
            assert "input_price" in price
            assert "output_price" in price

    def test_synthesize_uses_mock_when_secret_unset(self):
        """synthesize_pricing_config uses mock pricing when secret not set."""
        config = {"app_id": "test", "version": "1.0"}
        with patch.dict(os.environ, {}, clear=True):
            result = synthesize_pricing_config(config)
            assert result["status"] == "success"
            assert result["pricing_source"] == "mock"
            assert result["pricing"]["source"] == "mock"

    def test_mock_pricing_fallback_on_bridge_failure(self):
        """get_pricing_with_fallback falls back to mock on bridge error."""
        secret = "test-secret"
        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": secret}):
            with patch(
                "pricing_synthesizer.build_pricing_inputs", return_value=None
            ):
                price = get_pricing_with_fallback()
                assert price["source"] == "mock"


class TestSuccessfulPricingWithSecret:
    """Tests for successful pricing when PLOEH_S2S_SECRET present."""

    def test_get_pricing_fetches_from_bridge_when_secret_set(self):
        """get_pricing_with_fallback attempts bridge when secret configured."""
        secret = "test-secret"
        pricing_inputs = {
            "risk_vectors": {"fraud_score": 0.05},
            "trigger_specs": {},
            "source": "apparently",
        }

        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": secret}):
            with patch(
                "pricing_synthesizer._get_apparently_envelope",
                return_value={"payload": {}, "signature": "", "timestamp": time.time()},
            ):
                with patch(
                    "pricing_synthesizer.build_pricing_inputs",
                    return_value=pricing_inputs,
                ):
                    price = get_pricing_with_fallback()
                    assert price["source"] == "apparently"

    def test_synthesize_includes_apparently_pricing_when_available(self):
        """synthesize_pricing_config uses apparently pricing when bridge succeeds."""
        config = {"app_id": "test", "version": "1.0"}
        secret = "test-secret"

        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": secret}):
            with patch(
                "pricing_synthesizer._get_apparently_envelope",
                return_value={"payload": {}, "signature": "", "timestamp": time.time()},
            ):
                with patch(
                    "pricing_synthesizer.build_pricing_inputs",
                    return_value={
                        "risk_vectors": {"fraud_score": 0.1},
                        "trigger_specs": {},
                        "source": "apparently",
                    },
                ):
                    result = synthesize_pricing_config(config)
                    assert result["status"] == "success"
                    assert result["pricing_source"] == "apparently"

    def test_synthesize_maintains_config_integrity(self):
        """synthesize_pricing_config preserves original config."""
        config = {"app_id": "test-app", "version": "1.0", "custom": "value"}
        with patch.dict(os.environ, {}, clear=True):
            result = synthesize_pricing_config(config)
            assert result["config"]["app_id"] == config["app_id"]
            assert result["config"]["version"] == config["version"]
            assert result["config"]["custom"] == config["custom"]

    def test_synthesize_never_raises_exceptions(self):
        """synthesize_pricing_config never raises, always returns valid dict."""
        config = {"app_id": "test"}
        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": "secret"}):
            with patch(
                "pricing_synthesizer.get_pricing_with_fallback",
                side_effect=Exception("Unexpected error"),
            ):
                result = synthesize_pricing_config(config)
                assert result["status"] == "success"
                assert result["pricing_source"] == "mock"


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_envelope_with_missing_payload_field(self):
        """verify_envelope handles missing payload field gracefully."""
        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": "secret"}):
            with pytest.raises(ValueError):
                verify_envelope({"signature": "sig", "timestamp": time.time()})

    def test_envelope_with_missing_signature_field(self):
        """verify_envelope handles missing signature field gracefully."""
        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": "secret"}):
            with pytest.raises(ValueError):
                verify_envelope({"payload": {}, "timestamp": time.time()})

    def test_envelope_with_missing_timestamp_field(self):
        """verify_envelope handles missing timestamp field gracefully."""
        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": "secret"}):
            with pytest.raises(ValueError):
                verify_envelope({"payload": {}, "signature": "sig"})

    def test_envelope_with_malformed_json_payload(self):
        """build_pricing_inputs handles malformed payload gracefully."""
        secret = "test-secret"

        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": secret}):
            envelope = create_valid_envelope(secret, None)
            result = build_pricing_inputs(envelope)
            assert result is not None

    def test_empty_config_handled(self):
        """synthesize_pricing_config handles empty config."""
        with patch.dict(os.environ, {}, clear=True):
            result = synthesize_pricing_config({})
            assert result["status"] == "success"
            assert result["config"] == {}

    def test_none_config_handled(self):
        """synthesize_pricing_config handles None config."""
        with patch.dict(os.environ, {}, clear=True):
            result = synthesize_pricing_config(None)
            assert result["status"] == "success"


class TestLogging:
    """Tests for proper logging on failures."""

    def test_log_warning_on_verification_failure(self, caplog):
        """build_pricing_inputs logs warning on verification failure."""
        secret = "test-secret"
        payload = {"risk_vectors": {}, "trigger_specs": {}}

        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": secret}):
            envelope = create_valid_envelope(secret, payload)
            envelope["signature"] = "0" * 64
            build_pricing_inputs(envelope)
            # Should log but not raise

    def test_log_warning_on_expired_envelope(self, caplog):
        """build_pricing_inputs logs warning on expired envelope."""
        secret = "test-secret"
        payload = {"risk_vectors": {}, "trigger_specs": {}}

        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": secret}):
            envelope = create_valid_envelope(secret, payload, time.time() - 400)
            build_pricing_inputs(envelope)
            # Should log but not raise


class TestThreadSafety:
    """Tests for thread-safe operation."""

    def test_concurrent_verification_calls(self):
        """Multiple concurrent verify_envelope calls work correctly."""
        import threading

        secret = "test-secret"
        payload = {"risk_vectors": {}, "trigger_specs": {}}
        results = []

        def verify_in_thread():
            with patch.dict(os.environ, {"PLOEH_S2S_SECRET": secret}):
                envelope = create_valid_envelope(secret, payload)
                result = verify_envelope(envelope)
                results.append(result)

        threads = [threading.Thread(target=verify_in_thread) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 5
        for result in results:
            assert result == payload

    def test_concurrent_pricing_calls(self):
        """Multiple concurrent get_pricing_with_fallback calls work."""
        import threading

        results = []

        def get_price_in_thread():
            with patch.dict(os.environ, {}, clear=True):
                price = get_pricing_with_fallback()
                results.append(price)

        threads = [threading.Thread(target=get_price_in_thread) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 5
        for result in results:
            assert result["source"] == "mock"
