Here is the SPEC.md file based on the provided signals:

**Specification**
===============

**Purpose**
-----------

The app provides a centralized configuration management system for fleet-wide changes and fail-soft error handling.

**INVARIANTS**
-------------

### Data INVARIANTs

*   The `fleet_config` table remains up-to-date with all machines.
*   Database operations are used for configuration management, not hardcoded secrets or credentials.

### Security INVARIANT

*   Only safe config keys without secrets or credentials can be pushed fleet-wide.

### Correctness INVARIANT

*   Fail-soft error handling prevents crashes during code execution or database queries.

**Current Direction**
--------------------

The current direction is to maintain the existing conventions and rules, including:

*   Centralized configuration management through `fleet_config` and `fleet_control.py`.
*   Safe config keys only.
*   DB + git for synchronization.
*   Fail-soft error handling.