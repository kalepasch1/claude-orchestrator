#!/usr/bin/env python3
"""
test_ploeh_s2s_pricing_main.py - Tests for ploeh_s2s_pricing.py main module.

Covers deferred PLOEH_S2S pricing integration:
1. Secret configuration detection
2. PLOEH_S2S HTTP request handling
3. Pricing fetch with fallback
4. Caching behavior and invalidation
5. Synthesizer integration with pricing
6. Thread-safe concurrent access
7. Error handling and graceful fallback
"""

import os
import pytest
import sys
import json
import time
import threading
from unittest.mock import patch, MagicMock, Mock
import logging

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ploeh_s2s_pricing import (
    is_secret_configured,
    fetch_ploeh_s2s_price,
    get_ploeh_price,
    synthesize_with_pricing,
    invalidate_cache,
    _make_s2s_request,
    LOCAL_PRICE_FALLBACK,
)


class TestSecretConfiguration:
    """Tests for secret configuration detection."""

    def test_is_secret_configured_when_set(self):
        """is_secret_configured returns True when PLOEH_S2S_SECRET is set."""
        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": "test-secret-key"}):
            assert is_secret_configured() is True

    def test_is_secret_configured_when_unset(self):
        """is_secret_configured returns False when PLOEH_S2S_SECRET not set."""
        with patch.dict(os.environ, {}, clear=True):
            assert is_secret_configured() is False

    def test_is_secret_configured_with_empty_string(self):
        """is_secret_configured returns False for empty string."""
        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": ""}):
            assert is_secret_configured() is False

    def test_is_secret_configured_with_whitespace(self):
        """is_secret_configured returns False for whitespace-only string."""
        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": "   "}):
            assert is_secret_configured() is False

    def test_is_secret_configured_with_long_secret(self):
        """is_secret_configured returns True for long secret."""
        long_secret = "x" * 256
        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": long_secret}):
            assert is_secret_configured() is True


class TestMakeS2SRequest:
    """Tests for HTTP request to PLOEH_S2S service."""

    def test_make_s2s_request_success(self):
        """_make_s2s_request succeeds with valid response."""
        mock_response = {"input_price": 2.5, "output_price": 12.5, "effective_date": "2026-01-01"}

        with patch("ploeh_s2s_pricing.requests.get") as mock_get:
            mock_response_obj = Mock()
            mock_response_obj.json.return_value = mock_response
            mock_response_obj.status_code = 200
            mock_get.return_value = mock_response_obj

            with patch.dict(os.environ, {"PLOEH_S2S_SECRET": "test-secret"}):
                result = _make_s2s_request("test-secret")
                assert result == mock_response

    def test_make_s2s_request_connection_error(self):
        """_make_s2s_request raises ConnectionError on connection failure."""
        with patch("ploeh_s2s_pricing.requests.get") as mock_get:
            import requests
            mock_get.side_effect = requests.exceptions.ConnectionError("Connection failed")

            with pytest.raises(ConnectionError):
                _make_s2s_request("test-secret")

    def test_make_s2s_request_timeout(self):
        """_make_s2s_request raises TimeoutError on timeout."""
        with patch("ploeh_s2s_pricing.requests.get") as mock_get:
            import requests
            mock_get.side_effect = requests.exceptions.Timeout("Request timed out")

            with pytest.raises(TimeoutError):
                _make_s2s_request("test-secret")

    def test_make_s2s_request_authentication_error(self):
        """_make_s2s_request raises ValueError on 401 auth failure."""
        with patch("ploeh_s2s_pricing.requests.get") as mock_get:
            import requests
            mock_response_obj = Mock()
            mock_response_obj.status_code = 401
            mock_response_obj.raise_for_status.side_effect = requests.exceptions.HTTPError("401 Unauthorized")
            mock_get.return_value = mock_response_obj

            with pytest.raises(ValueError):
                _make_s2s_request("invalid-secret")

    def test_make_s2s_request_server_error(self):
        """_make_s2s_request raises ValueError on 5xx server error."""
        with patch("ploeh_s2s_pricing.requests.get") as mock_get:
            import requests
            mock_response_obj = Mock()
            mock_response_obj.status_code = 500
            mock_response_obj.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Server Error")
            mock_get.return_value = mock_response_obj

            with pytest.raises(ValueError):
                _make_s2s_request("test-secret")

    def test_make_s2s_request_includes_auth_header(self):
        """_make_s2s_request sends Authorization header with secret."""
        with patch("ploeh_s2s_pricing.requests.get") as mock_get:
            mock_response_obj = Mock()
            mock_response_obj.json.return_value = {"input_price": 1.0, "output_price": 5.0}
            mock_get.return_value = mock_response_obj

            secret = "my-test-secret"
            _make_s2s_request(secret)

            call_args = mock_get.call_args
            headers = call_args.kwargs.get("headers", {})
            assert "Authorization" in headers
            assert headers["Authorization"] == f"Bearer {secret}"

    def test_make_s2s_request_uses_environment_endpoint(self):
        """_make_s2s_request uses PLOEH_S2S_ENDPOINT from environment."""
        custom_endpoint = "https://custom.ploeh.service/pricing"
        with patch("ploeh_s2s_pricing.requests.get") as mock_get:
            mock_response_obj = Mock()
            mock_response_obj.json.return_value = {"input_price": 1.0, "output_price": 5.0}
            mock_get.return_value = mock_response_obj

            with patch.dict(os.environ, {"PLOEH_S2S_ENDPOINT": custom_endpoint}):
                _make_s2s_request("secret")

                call_args = mock_get.call_args
                endpoint = call_args.args[0] if call_args.args else call_args.kwargs.get("url")
                assert endpoint == custom_endpoint


class TestFetchPloehS2SPrice:
    """Tests for PLOEH_S2S pricing fetch."""

    def test_fetch_ploeh_s2s_price_when_secret_not_configured(self):
        """fetch_ploeh_s2s_price returns None when secret not configured."""
        with patch.dict(os.environ, {}, clear=True):
            result = fetch_ploeh_s2s_price()
            assert result is None

    def test_fetch_ploeh_s2s_price_success(self):
        """fetch_ploeh_s2s_price returns pricing data when successful."""
        mock_response = {"input_price": 2.5, "output_price": 12.5}

        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": "test-secret"}):
            with patch.object(__import__('ploeh_s2s_pricing'), '_make_s2s_request') as mock_request:
                mock_request.return_value = mock_response

                result = fetch_ploeh_s2s_price()
                assert result is not None
                assert result["input_price"] == 2.5
                assert result["output_price"] == 12.5
                assert result["source"] == "ploeh_s2s"

    def test_fetch_ploeh_s2s_price_graceful_fallback_on_connection_error(self):
        """fetch_ploeh_s2s_price returns None on connection error."""
        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": "test-secret"}):
            with patch.object(__import__('ploeh_s2s_pricing'), '_make_s2s_request') as mock_request:
                mock_request.side_effect = ConnectionError("Service unavailable")

                result = fetch_ploeh_s2s_price()
                assert result is None

    def test_fetch_ploeh_s2s_price_graceful_fallback_on_timeout(self):
        """fetch_ploeh_s2s_price returns None on timeout."""
        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": "test-secret"}):
            with patch.object(__import__('ploeh_s2s_pricing'), '_make_s2s_request') as mock_request:
                mock_request.side_effect = TimeoutError("Request timed out")

                result = fetch_ploeh_s2s_price()
                assert result is None

    def test_fetch_ploeh_s2s_price_graceful_fallback_on_auth_error(self):
        """fetch_ploeh_s2s_price returns None on authentication error."""
        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": "bad-secret"}):
            with patch.object(__import__('ploeh_s2s_pricing'), '_make_s2s_request') as mock_request:
                mock_request.side_effect = ValueError("Authentication failed")

                result = fetch_ploeh_s2s_price()
                assert result is None

    def test_fetch_ploeh_s2s_price_returns_none_on_missing_fields(self):
        """fetch_ploeh_s2s_price returns None when response missing required fields."""
        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": "test-secret"}):
            with patch.object(__import__('ploeh_s2s_pricing'), '_make_s2s_request') as mock_request:
                mock_request.return_value = {"input_price": 1.0}  # Missing output_price

                result = fetch_ploeh_s2s_price()
                assert result is None

    def test_fetch_ploeh_s2s_price_returns_none_on_non_dict_response(self):
        """fetch_ploeh_s2s_price returns None when response is not a dict."""
        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": "test-secret"}):
            with patch.object(__import__('ploeh_s2s_pricing'), '_make_s2s_request') as mock_request:
                mock_request.return_value = ["input_price", "output_price"]  # List instead of dict

                result = fetch_ploeh_s2s_price()
                assert result is None

    def test_fetch_ploeh_s2s_price_returns_none_on_unexpected_error(self):
        """fetch_ploeh_s2s_price returns None on unexpected error."""
        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": "test-secret"}):
            with patch.object(__import__('ploeh_s2s_pricing'), '_make_s2s_request') as mock_request:
                mock_request.side_effect = RuntimeError("Unexpected error")

                result = fetch_ploeh_s2s_price()
                assert result is None


class TestGetPloehPrice:
    """Tests for get_ploeh_price with caching."""

    def setup_method(self):
        """Clear cache before each test."""
        invalidate_cache()

    def teardown_method(self):
        """Clear cache after each test."""
        invalidate_cache()

    def test_get_ploeh_price_returns_local_when_secret_unset(self):
        """get_ploeh_price returns local pricing when secret not set."""
        with patch.dict(os.environ, {}, clear=True):
            result = get_ploeh_price()
            assert result["source"] == "local"
            assert result["input_price"] == LOCAL_PRICE_FALLBACK["input_price"]
            assert result["output_price"] == LOCAL_PRICE_FALLBACK["output_price"]

    def test_get_ploeh_price_returns_ploeh_when_available(self):
        """get_ploeh_price returns PLOEH_S2S pricing when secret set and service available."""
        mock_price = {"input_price": 2.5, "output_price": 12.5, "source": "ploeh_s2s"}

        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": "test-secret"}):
            with patch("ploeh_s2s_pricing.fetch_ploeh_s2s_price") as mock_fetch:
                mock_fetch.return_value = mock_price

                result = get_ploeh_price()
                assert result["source"] == "ploeh_s2s"
                assert result["input_price"] == 2.5

    def test_get_ploeh_price_falls_back_to_local_when_fetch_fails(self):
        """get_ploeh_price returns local pricing when fetch fails."""
        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": "test-secret"}):
            with patch("ploeh_s2s_pricing.fetch_ploeh_s2s_price") as mock_fetch:
                mock_fetch.return_value = None

                result = get_ploeh_price()
                assert result["source"] == "local"
                assert result["input_price"] == LOCAL_PRICE_FALLBACK["input_price"]

    def test_get_ploeh_price_caches_result(self):
        """get_ploeh_price caches result and returns cached value on second call."""
        mock_price = {"input_price": 2.5, "output_price": 12.5, "source": "ploeh_s2s"}

        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": "test-secret"}):
            with patch("ploeh_s2s_pricing.fetch_ploeh_s2s_price") as mock_fetch:
                mock_fetch.return_value = mock_price

                # First call
                result1 = get_ploeh_price()
                # Second call should use cache without calling fetch again
                result2 = get_ploeh_price()

                assert mock_fetch.call_count == 1  # Only called once
                assert result1 == result2

    def test_get_ploeh_price_never_raises_exceptions(self):
        """get_ploeh_price never raises exceptions."""
        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": "test-secret"}):
            with patch("ploeh_s2s_pricing.fetch_ploeh_s2s_price") as mock_fetch:
                mock_fetch.side_effect = RuntimeError("Unexpected error")

                # Should not raise, should return sensible default
                result = get_ploeh_price()
                assert result is not None
                assert "input_price" in result
                assert "output_price" in result

    def test_get_ploeh_price_returns_copy_not_reference(self):
        """get_ploeh_price returns copy, not reference to cached data."""
        with patch.dict(os.environ, {}, clear=True):
            price1 = get_ploeh_price()
            price2 = get_ploeh_price()

            # Modify first result
            price1["input_price"] = 999

            # Second result should not be affected
            assert price2["input_price"] != 999
            assert price2["input_price"] == LOCAL_PRICE_FALLBACK["input_price"]


class TestInvalidateCache:
    """Tests for cache invalidation."""

    def setup_method(self):
        """Clear cache before each test."""
        invalidate_cache()

    def teardown_method(self):
        """Clear cache after each test."""
        invalidate_cache()

    def test_invalidate_cache_clears_cached_pricing(self):
        """invalidate_cache clears the pricing cache."""
        with patch.dict(os.environ, {}, clear=True):
            # Prime cache
            get_ploeh_price()

            # Invalidate
            invalidate_cache()

            # Next call should work normally (not affected by cache timing)
            result = get_ploeh_price()
            assert result["source"] == "local"

    def test_invalidate_cache_allows_fresh_fetch(self):
        """invalidate_cache forces fresh fetch on next call."""
        mock_price1 = {"input_price": 1.0, "output_price": 5.0, "source": "ploeh_s2s"}
        mock_price2 = {"input_price": 2.0, "output_price": 10.0, "source": "ploeh_s2s"}

        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": "test-secret"}):
            with patch("ploeh_s2s_pricing.fetch_ploeh_s2s_price") as mock_fetch:
                # First fetch
                mock_fetch.return_value = mock_price1
                result1 = get_ploeh_price()
                assert result1["input_price"] == 1.0

                # Change mock response
                mock_fetch.return_value = mock_price2

                # Second call uses cache (mock not called)
                result2 = get_ploeh_price()
                assert result2["input_price"] == 1.0  # Still cached

                # Invalidate cache
                invalidate_cache()

                # Third call fetches fresh data
                result3 = get_ploeh_price()
                assert result3["input_price"] == 2.0  # Fresh data


class TestSynthesizeWithPricing:
    """Tests for synthesize_with_pricing function."""

    def setup_method(self):
        """Clear cache before each test."""
        invalidate_cache()

    def teardown_method(self):
        """Clear cache after each test."""
        invalidate_cache()

    def test_synthesize_with_pricing_success_local(self):
        """synthesize_with_pricing succeeds with local pricing."""
        config = {"app_id": "test-app", "version": "1.0"}

        with patch.dict(os.environ, {}, clear=True):
            result = synthesize_with_pricing(config)

            assert result["status"] == "success"
            assert result["config"] == config
            assert result["pricing_source"] == "local"
            assert result["pricing"]["source"] == "local"

    def test_synthesize_with_pricing_includes_ploeh_when_available(self):
        """synthesize_with_pricing uses PLOEH_S2S pricing when available."""
        config = {"app_id": "test-app"}
        mock_price = {"input_price": 3.0, "output_price": 15.0, "source": "ploeh_s2s"}

        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": "test-secret"}):
            with patch("ploeh_s2s_pricing.fetch_ploeh_s2s_price") as mock_fetch:
                mock_fetch.return_value = mock_price

                result = synthesize_with_pricing(config)

                assert result["status"] == "success"
                assert result["pricing_source"] == "ploeh_s2s"
                assert result["pricing"]["input_price"] == 3.0

    def test_synthesize_with_pricing_preserves_config(self):
        """synthesize_with_pricing preserves original config intact."""
        config = {
            "app_id": "my-app",
            "version": "2.5",
            "custom_field": "custom_value",
            "nested": {"key": "value"}
        }

        with patch.dict(os.environ, {}, clear=True):
            result = synthesize_with_pricing(config)

            assert result["config"]["app_id"] == config["app_id"]
            assert result["config"]["version"] == config["version"]
            assert result["config"]["custom_field"] == config["custom_field"]
            assert result["config"]["nested"] == config["nested"]

    def test_synthesize_with_pricing_handles_empty_config(self):
        """synthesize_with_pricing handles empty config."""
        with patch.dict(os.environ, {}, clear=True):
            result = synthesize_with_pricing({})

            assert result["status"] == "success"
            assert result["config"] == {}

    def test_synthesize_with_pricing_handles_none_config(self):
        """synthesize_with_pricing handles None config."""
        with patch.dict(os.environ, {}, clear=True):
            result = synthesize_with_pricing(None)

            assert result["status"] == "success"
            assert result["config"] == {}

    def test_synthesize_with_pricing_never_raises_exceptions(self):
        """synthesize_with_pricing never raises exceptions."""
        config = {"app_id": "test"}

        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": "test-secret"}):
            with patch("ploeh_s2s_pricing.get_ploeh_price") as mock_get:
                mock_get.side_effect = RuntimeError("Unexpected error")

                # Should not raise
                result = synthesize_with_pricing(config)
                assert result["status"] == "failed" or result["status"] == "success"
                assert result is not None

    def test_synthesize_with_pricing_includes_pricing_info(self):
        """synthesize_with_pricing includes pricing information."""
        config = {"app_id": "test"}

        with patch.dict(os.environ, {}, clear=True):
            result = synthesize_with_pricing(config)

            assert "pricing" in result
            assert "input_price" in result["pricing"]
            assert "output_price" in result["pricing"]
            assert "source" in result["pricing"]
            assert result["pricing"]["input_price"] > 0
            assert result["pricing"]["output_price"] > 0


class TestThreadSafety:
    """Tests for thread-safe concurrent access."""

    def setup_method(self):
        """Clear cache before each test."""
        invalidate_cache()

    def teardown_method(self):
        """Clear cache after each test."""
        invalidate_cache()

    def test_concurrent_get_ploeh_price_calls(self):
        """Multiple concurrent get_ploeh_price calls work correctly."""
        results = []
        errors = []

        def fetch_price():
            try:
                with patch.dict(os.environ, {}, clear=True):
                    result = get_ploeh_price()
                    results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=fetch_price) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 10
        # All results should be consistent (local pricing)
        for result in results:
            assert result["source"] == "local"

    def test_concurrent_synthesize_calls(self):
        """Multiple concurrent synthesize_with_pricing calls work correctly."""
        results = []
        errors = []

        def synthesize():
            try:
                with patch.dict(os.environ, {}, clear=True):
                    result = synthesize_with_pricing({"app_id": "test"})
                    results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=synthesize) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 10
        # All results should be valid
        for result in results:
            assert result["status"] == "success"

    def test_concurrent_cache_invalidation(self):
        """Cache invalidation is safe under concurrent access."""
        results = []
        errors = []

        def fetch_and_invalidate():
            try:
                with patch.dict(os.environ, {}, clear=True):
                    get_ploeh_price()
                    invalidate_cache()
                    get_ploeh_price()
                    results.append(True)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=fetch_and_invalidate) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 5


class TestIntegration:
    """Integration tests for complete workflows."""

    def setup_method(self):
        """Clear cache before each test."""
        invalidate_cache()

    def teardown_method(self):
        """Clear cache after each test."""
        invalidate_cache()

    def test_complete_workflow_without_secret(self):
        """Complete workflow without PLOEH_S2S_SECRET uses local pricing."""
        with patch.dict(os.environ, {}, clear=True):
            # Step 1: Check configuration
            assert is_secret_configured() is False

            # Step 2: Get pricing
            price = get_ploeh_price()
            assert price["source"] == "local"

            # Step 3: Synthesize config
            config = {"app_id": "myapp", "version": "1.0"}
            result = synthesize_with_pricing(config)

            assert result["status"] == "success"
            assert result["pricing_source"] == "local"
            assert result["config"] == config

    def test_complete_workflow_with_secret(self):
        """Complete workflow with PLOEH_S2S_SECRET attempts cross-app call."""
        mock_price = {"input_price": 2.5, "output_price": 12.5, "source": "ploeh_s2s"}

        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": "my-secret"}):
            # Step 1: Check configuration
            assert is_secret_configured() is True

            # Step 2: Mock the fetch and get pricing
            with patch("ploeh_s2s_pricing.fetch_ploeh_s2s_price") as mock_fetch:
                mock_fetch.return_value = mock_price

                price = get_ploeh_price()
                assert price["source"] == "ploeh_s2s"

                # Step 3: Synthesize config
                config = {"app_id": "myapp"}
                result = synthesize_with_pricing(config)

                assert result["status"] == "success"
                assert result["pricing_source"] == "ploeh_s2s"

    def test_graceful_degradation_when_service_unavailable(self):
        """System gracefully degrades when PLOEH_S2S service unavailable."""
        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": "my-secret"}):
            with patch("ploeh_s2s_pricing.fetch_ploeh_s2s_price") as mock_fetch:
                # Simulate service unavailable
                mock_fetch.return_value = None

                # Should still work with fallback
                price = get_ploeh_price()
                assert price["source"] == "local"

                result = synthesize_with_pricing({"app_id": "myapp"})
                assert result["status"] == "success"
                assert result["pricing_source"] == "local"


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def setup_method(self):
        """Clear cache before each test."""
        invalidate_cache()

    def teardown_method(self):
        """Clear cache after each test."""
        invalidate_cache()

    def test_pricing_with_very_large_numbers(self):
        """Pricing system handles very large numbers."""
        mock_price = {
            "input_price": 999999.99,
            "output_price": 888888.88,
            "source": "ploeh_s2s"
        }

        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": "test"}):
            with patch("ploeh_s2s_pricing.fetch_ploeh_s2s_price") as mock_fetch:
                mock_fetch.return_value = mock_price

                result = synthesize_with_pricing({"app_id": "test"})
                assert result["pricing"]["input_price"] == 999999.99

    def test_pricing_with_zero_values(self):
        """Pricing system handles zero values."""
        mock_price = {
            "input_price": 0.0,
            "output_price": 0.0,
            "source": "ploeh_s2s"
        }

        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": "test"}):
            with patch("ploeh_s2s_pricing.fetch_ploeh_s2s_price") as mock_fetch:
                mock_fetch.return_value = mock_price

                result = synthesize_with_pricing({"app_id": "test"})
                assert result["pricing"]["input_price"] == 0.0

    def test_pricing_with_negative_values(self):
        """Pricing system handles negative values (edge case)."""
        mock_price = {
            "input_price": -1.0,
            "output_price": -5.0,
            "source": "ploeh_s2s"
        }

        with patch.dict(os.environ, {"PLOEH_S2S_SECRET": "test"}):
            with patch("ploeh_s2s_pricing.fetch_ploeh_s2s_price") as mock_fetch:
                mock_fetch.return_value = mock_price

                result = synthesize_with_pricing({"app_id": "test"})
                # System accepts these, application logic should validate if needed
                assert result["pricing"]["input_price"] == -1.0

    def test_config_with_special_characters(self):
        """Synthesizer handles config with special characters."""
        config = {
            "app_id": "my-app@v2.0",
            "description": "Test with <special> & \"chars\"",
            "path": "/path/to/file"
        }

        with patch.dict(os.environ, {}, clear=True):
            result = synthesize_with_pricing(config)
            assert result["config"]["app_id"] == config["app_id"]
            assert result["config"]["description"] == config["description"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
