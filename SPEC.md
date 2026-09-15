Here is the SPEC.md contents based on the provided signals:

**Product Purpose**

The Claude Code app is a workflow management tool that enables developers to manage and execute code changes in a production-ready environment. It integrates with a centralized configuration management system, ensures data consistency, and provides fail-soft error handling.

**Invariants**

*   **Data Integrity**: All code changes must be integrated into the `orchestrator/dev` branch before reaching production.
*   **Security**: Hardcoded secrets and credentials are not allowed in the configuration keys.
*   **Correctness**: Changes must be propagated between machines using git, and database operations are used for configuration management.

**Current Direction**

The current direction is to maintain the existing workflow and conventions, including centralized configuration management, safe config keys, DB + git for synchronization, and fail-soft error handling.