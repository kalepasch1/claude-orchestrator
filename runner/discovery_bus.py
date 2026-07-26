"""Real-time knowledge sharing between concurrent DAG tasks.

When Task A discovers something useful (a utility it created, a pattern
it chose, an API shape it settled on, a gotcha it hit), it publishes
to the bus. Task B — running concurrently — reads discoveries before
generating its own code.
"""

import threading
import time
import re
import os
import json
import logging
from collections import defaultdict, Counter
from typing import List, Dict, Any, Optional, Callable

log = logging.getLogger(__name__)


class SharedDiscoveryBus:
    """Thread-safe in-memory discovery bus for concurrent DAG task communication."""

    def __init__(self):
        self._lock = threading.Lock()
        self._discoveries: List[Dict[str, Any]] = []
        self._by_tag = defaultdict(list)
        self._by_task = defaultdict(list)
        self._subscribers: List[tuple] = []

    def publish(self, discovery: Dict[str, Any]) -> None:
        """Publish a discovery. Fields: slug, kind, summary, tags, content,
        file_path, confidence (0-1), ts."""
        discovery.setdefault("ts", time.time())
        discovery.setdefault("confidence", 0.8)
        with self._lock:
            self._discoveries.append(discovery)
            for tag in discovery.get("tags", []):
                self._by_tag[tag].append(discovery)
            self._by_task[discovery["slug"]].append(discovery)
            for callback, filter_fn in self._subscribers:
                try:
                    if filter_fn is None or filter_fn(discovery):
                        callback(discovery)
                except Exception as e:
                    log.warning("subscriber callback failed: %s", e)

    def read_all(self, since_ts: Optional[float] = None) -> List[Dict[str, Any]]:
        """Read all discoveries, optionally filtered by timestamp."""
        with self._lock:
            if since_ts:
                return [d for d in self._discoveries if d.get("ts", 0) > since_ts]
            return list(self._discoveries)

    def read_by_tags(self, tags: List[str]) -> List[Dict[str, Any]]:
        """Read discoveries that have any of the given tags."""
        with self._lock:
            results, seen = [], set()
            for tag in tags:
                for d in self._by_tag.get(tag, []):
                    key = (d.get("slug", ""), d.get("summary", ""))
                    if key not in seen:
                        seen.add(key)
                        results.append(d)
            return results

    def subscribe(self, callback: Callable, filter_fn: Optional[Callable] = None) -> None:
        """Subscribe to all new discoveries. filter_fn(discovery) -> bool to filter."""
        with self._lock:
            self._subscribers.append((callback, filter_fn))

    def context_injection(self, task_slug: str, task_tags: List[str]) -> str:
        """Generate context to inject into a task's prompt with sibling discoveries."""
        with self._lock:
            relevant = []
            for d in self._discoveries:
                if d.get("slug") == task_slug:
                    continue
                tag_overlap = set(d.get("tags", [])) & set(task_tags)
                if tag_overlap or d.get("confidence", 0) >= 0.9:
                    relevant.append(d)
            if not relevant:
                return ""
            lines = ["\n--- SIBLING TASK DISCOVERIES (use these, don't recreate) ---"]
            for d in relevant:
                lines.append(f"\n[{d.get('slug', '?')}] {d.get('kind', '?')}: {d.get('summary', '')}")
                if d.get("file_path"):
                    lines.append(f"  File: {d['file_path']}")
                if d.get("content") and len(d.get("content", "")) < 2000:
                    lines.append(f"  Content:\n{d['content']}")
            lines.append("\n--- END SIBLING DISCOVERIES ---\n")
            return "\n".join(lines)

    def stats(self) -> Dict[str, Any]:
        """Get current bus statistics."""
        with self._lock:
            kinds = [d.get("kind", "") for d in self._discoveries if d.get("kind")]
            return {
                "total_discoveries": len(self._discoveries),
                "by_kind": dict(Counter(kinds)),
                "active_tags": sorted(set(self._by_tag.keys())),
                "tasks_contributing": sorted(set(self._by_task.keys())),
            }

    def invalidate(self) -> None:
        """Clear all discoveries and subscribers."""
        with self._lock:
            self._discoveries.clear()
            self._by_tag.clear()
            self._by_task.clear()
            self._subscribers.clear()


# --- Discovery extraction from task results ---

_SHARED_PATH_RE = re.compile(r'^\+\+\+ b/(types/|shared/|lib/|utils/|composables/)(.+)', re.M)
_EXPORT_RE = re.compile(r'^\+(export (?:interface|type|function|const|class) (\w+))', re.M)
_API_ROUTE_RE = re.compile(
    r'^\+.*(?:app\.(get|post|put|delete|patch)|router\.\w+|defineEventHandler).*[\'"]([^\'"]+)[\'"]',
    re.M
)
_GOTCHA_RE = re.compile(
    r'^\+\s*(?://|#)\s*(?:GOTCHA|HACK|WORKAROUND|NOTE|WARNING|BUG|FIXME):\s*(.+)',
    re.M | re.I
)


def extract_discoveries(slug: str, tags: List[str], result: Any, repo_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Parse a task's output for things sibling tasks should know about."""
    discoveries = []
    diff_text = ""
    if isinstance(result, dict):
        diff_text = result.get("diff", result.get("text", ""))
    elif isinstance(result, str):
        diff_text = result
    if not diff_text:
        return discoveries

    # Shared files created
    for match in _SHARED_PATH_RE.finditer(diff_text):
        file_path = match.group(1) + match.group(2)
        full_path = os.path.join(repo_path, file_path) if repo_path else None
        content = ""
        if full_path and os.path.exists(full_path):
            try:
                with open(full_path, encoding="utf-8") as f:
                    content = f.read()
                    if len(content) > 5000:
                        content = content[:5000] + "\n... (truncated)"
            except Exception as e:
                log.warning("failed to read %s: %s", full_path, e)
        discoveries.append({
            "slug": slug,
            "kind": "shared_file_created",
            "summary": f"Created shared file {file_path}",
            "tags": tags + ["shared", file_path.split("/")[0]],
            "content": content,
            "file_path": file_path,
            "confidence": 0.95,
            "ts": time.time(),
        })

    # Exports
    for match in _EXPORT_RE.finditer(diff_text):
        discoveries.append({
            "slug": slug,
            "kind": "export_created",
            "summary": f"Exported {match.group(2)} — import from this task's files",
            "tags": tags + ["export", match.group(2).lower()],
            "content": match.group(1),
            "confidence": 0.85,
            "ts": time.time(),
        })

    # API routes
    for match in _API_ROUTE_RE.finditer(diff_text):
        discoveries.append({
            "slug": slug,
            "kind": "api_route_defined",
            "summary": f"API route {match.group(1).upper()} {match.group(2)}",
            "tags": tags + ["api", "route"],
            "content": match.group(0).lstrip("+"),
            "confidence": 0.90,
            "ts": time.time(),
        })

    # Gotchas / workarounds
    for match in _GOTCHA_RE.finditer(diff_text):
        discoveries.append({
            "slug": slug,
            "kind": "gotcha",
            "summary": match.group(1).strip(),
            "tags": tags + ["gotcha", "warning"],
            "confidence": 0.95,
            "ts": time.time(),
        })

    return discoveries


# Global singleton for single-bus-per-session use
_default_bus = None
_default_bus_lock = threading.Lock()


def get_default_bus() -> SharedDiscoveryBus:
    """Get or create the default module-level bus."""
    global _default_bus
    if _default_bus is None:
        with _default_bus_lock:
            if _default_bus is None:
                _default_bus = SharedDiscoveryBus()
    return _default_bus


def invalidate() -> None:
    """Clear the default bus (for testing)."""
    global _default_bus
    with _default_bus_lock:
        if _default_bus:
            _default_bus.invalidate()
        _default_bus = None
