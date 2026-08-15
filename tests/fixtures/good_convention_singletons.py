"""
Good convention example: Module-level singleton pattern.

This module follows the convention: "Provide module-level functions that
delegate to a thread-safe singleton instance (e.g., acquire() → _pool.acquire());
avoids passing state through call chains"
"""
import threading


# Private singleton instance
_pool = None
_pool_lock = threading.Lock()


class ResourcePool:
    """Internal pool implementation (singleton)."""

    def __init__(self, size=10):
        self._items = [object() for _ in range(size)]
        self._available = [True] * size
        self._lock = threading.Lock()

    def acquire(self):
        """Acquire a resource from the pool."""
        with self._lock:
            for i, available in enumerate(self._available):
                if available:
                    self._available[i] = False
                    return self._items[i]
        return None

    def release(self, item):
        """Release a resource back to the pool."""
        with self._lock:
            if item in self._items:
                idx = self._items.index(item)
                self._available[idx] = True


# OK: Module-level function delegating to singleton
def acquire():
    """Public API: Acquire a resource."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ResourcePool()
    return _pool.acquire()


# OK: Module-level function delegating to singleton
def release(item):
    """Public API: Release a resource."""
    global _pool
    if _pool is not None:
        _pool.release(item)


# OK: Helper function without self
def get_pool_size():
    """Helper function (no self parameter)."""
    return 10


# OK: Class with methods (allowed to have self)
class Worker:
    """Helper class with methods."""

    def __init__(self):
        self.resource = acquire()

    def process(self):
        """Process data with acquired resource."""
        return len(str(self.resource))

    def cleanup(self):
        """Release resource."""
        if self.resource:
            release(self.resource)
