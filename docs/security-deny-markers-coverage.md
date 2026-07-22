# Security: fleet_config deny marker coverage

**Date:** 2026-07-18
**Risk:** Low

## Analysis
The `_DENY_MARKERS` tuple in `fleet_control.py` blocks config keys containing
credential-like substrings. Current markers:

    KEY, SECRET, TOKEN, PASSWORD, PWD, CREDENTIAL, PAT

## Recommendation
Consider adding `AUTH` and `PRIVATE` to the deny list for defense-in-depth.
While no current config keys use these substrings, they are common patterns
in credential variable naming across the industry.

This is a low-risk hardening measure — false positives would only block a
new config key from being pushed fleet-wide, never crash the runner.
