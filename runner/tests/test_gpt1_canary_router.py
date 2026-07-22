#!/usr/bin/env python3
"""Tests for gpt1_canary_router module."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gpt1_canary_router import route_gpt1_request_canary

_N = 10_000
_CTX = {}


class Gpt1CanaryRouterTest(unittest.TestCase):

    def test_zero_pct_always_control(self):
        for _ in range(200):
            self.assertEqual(route_gpt1_request_canary(_CTX, 0), "control")

    def test_hundred_pct_always_canary(self):
        for _ in range(200):
            self.assertEqual(route_gpt1_request_canary(_CTX, 100), "canary")

    def test_fifty_pct_distribution(self):
        canary = sum(1 for _ in range(_N) if route_gpt1_request_canary(_CTX, 50) == "canary")
        self.assertGreaterEqual(canary, int(_N * 0.45))
        self.assertLessEqual(canary, int(_N * 0.55))

    def test_returns_valid_endpoint_identifier(self):
        for pct in range(0, 101, 10):
            self.assertIn(route_gpt1_request_canary(_CTX, pct), ("canary", "control"))

    def test_negative_pct_treated_as_zero(self):
        for _ in range(50):
            self.assertEqual(route_gpt1_request_canary(_CTX, -10), "control")

    def test_above_hundred_pct_treated_as_full_canary(self):
        for _ in range(50):
            self.assertEqual(route_gpt1_request_canary(_CTX, 110), "canary")


if __name__ == "__main__":
    unittest.main()
