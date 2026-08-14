"""Interface layer: REST controllers and external adapters.

This package is the outermost ring of the legal-radar-v2 slice. Nothing in
`src/legal_radar_v2` (the domain) imports from here — the dependency arrow
points inward only. Controllers translate transport payloads into domain
calls; gateways translate domain calls into outbound I/O.

Conventions (CLAUDE.md):
  * fail-soft — a controller returns a structured error envelope rather than
    raising, so a bad request never wedges the runner;
  * module-level singletons — module functions delegate to one thread-safe
    instance rather than threading state through call chains;
  * every tunable is an ``ORCH_``-prefixed env var with a sensible default.
"""
from .http.inbox_controller import InboxController, handle_request  # noqa: F401
from .gateways.inbox_gateway import InboxGateway, dispatch  # noqa: F401

__all__ = ["InboxController", "handle_request", "InboxGateway", "dispatch"]
