#!/usr/bin/env python3
"""
decomposition_events.py — decomposition-completion event handler for the
missing-branch auto-creator (slice 3).

The missing_branch bottleneck starts at DECOMPOSITION time: when a parent
task is split into slices, the child tasks exist in the queue before any
agent branch exists, and the scan-based auto-creator
(branch_orchestrator.find_missing_branches) only catches them on its next
sweep. This module is the event-driven half: decomposers emit
`decomposition_completed`, and the handler provisions `agent/<slug>`
branches for the new children immediately.

Conventions (per CLAUDE.md):
- Module-level singleton; functions delegate to it; `invalidate()` resets.
- Fail-soft: a provisioning failure never breaks decomposition; the child
  simply falls back to the scan-based sweep.
- Env-var configuration with sensible defaults.
- Provisioner is injectable so tests never touch git.
"""
import os
import threading

ENABLED = os.environ.get(
    "ORCH_DECOMP_EVENT_AUTOCREATE_ENABLED", "true"
).lower() == "true"
MAX_PER_EVENT = int(os.environ.get("ORCH_DECOMP_EVENT_AUTOCREATE_BATCH", "20"))

_lock = threading.Lock()
_handler = None


def _default_provisioner(slug, repo_path, base_branch):
    """Provision agent/<slug> via the scan-based auto-creator's primitive."""
    import branch_orchestrator
    return branch_orchestrator.provision_branch(slug, repo_path, base_branch)


class DecompositionEventHandler:
    """Tracks decomposition events and provisions branches for new slices."""

    def __init__(self, provisioner=None):
        self.provisioner = provisioner or _default_provisioner
        self.lock = threading.Lock()
        self.events = []

    def handle(self, parent_slug, child_tasks, repo_path=None, base_branch="master"):
        """Handle one decomposition_completed event. Returns a result dict.

        Never raises: per-child provisioning failures are collected and the
        child is left for the scan-based sweep (fail-soft).
        """
        children = list(child_tasks or [])[:MAX_PER_EVENT]
        result = {
            "parent_slug": parent_slug,
            "children": len(children),
            "provisioned": [],
            "skipped": [],
            "errors": [],
        }
        for child in children:
            slug = (child or {}).get("slug") if isinstance(child, dict) else None
            if not slug or slug == parent_slug:
                result["skipped"].append(slug)
                continue
            if not ENABLED or not repo_path:
                result["skipped"].append(slug)
                continue
            try:
                self.provisioner(
                    slug, repo_path, (child.get("base_branch") or base_branch)
                )
                result["provisioned"].append(slug)
            except Exception as exc:  # fail-soft: sweep picks it up later
                result["errors"].append({"slug": slug, "error": str(exc)})
        with self.lock:
            self.events.append(result)
        return result


def _get_handler():
    global _handler
    if _handler is None:
        with _lock:
            if _handler is None:
                _handler = DecompositionEventHandler()
    return _handler


def invalidate():
    """Reset the singleton (tests / lifecycle)."""
    global _handler
    with _lock:
        _handler = None


def on_decomposition_completed(parent_slug, child_tasks, repo_path=None,
                               base_branch="master"):
    """Public event entry point — delegate to the singleton handler."""
    return _get_handler().handle(parent_slug, child_tasks, repo_path, base_branch)


def recent_events():
    """Observability: events handled by the current singleton."""
    h = _get_handler()
    with h.lock:
        return list(h.events)
