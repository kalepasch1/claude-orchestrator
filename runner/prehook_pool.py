#!/usr/bin/env python3
"""prehook_pool.py — run independent pre-hooks concurrently, and say how long it took.

WHY THIS EXISTS. runner.py's pre-hook pipeline already fans its read-only hooks out
across a ThreadPoolExecutor (the `parallel_gates` pattern applied to hooks). Two things
were still missing, and both are about being able to SEE the pipeline rather than
assume it:

  1. Nothing logged total pre-hook wall time. The pipeline has a 60s guard
     (`ORCH_PREHOOK_MAX_S`) that silently skips the remaining hooks when it trips —
     so the one number that tells an operator whether the guard is firing, and why,
     was never emitted. "Death by a thousand hooks" was diagnosed by reading code.
  2. Nothing asserted the hooks actually run in parallel. A future edit that moves a
     `.result()` inside the submit loop serialises the whole fan-out and changes no
     test — the pool would still be there, doing one thing at a time.

Extracting the fan-out into a named function makes both testable without standing up
runner.py's ~900-line task body. Behaviour is unchanged: same executor, same
fail-soft contract (a hook that raises is logged and skipped, never propagated).

Stdlib only, per the task's no-new-dependencies constraint.
"""
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

_log = logging.getLogger(__name__)

#: Default fan-out width. Matches ORCH_HOOK_WORKERS in runner.py so the two cannot drift.
DEFAULT_WORKERS = 6


def hook_workers(default=None):
    """Fan-out width from ORCH_HOOK_WORKERS. Fail-soft: garbage falls back to the default."""
    fallback = DEFAULT_WORKERS if default is None else default
    try:
        value = int(os.environ.get("ORCH_HOOK_WORKERS", fallback))
    except (TypeError, ValueError):
        return fallback
    return value if value > 0 else fallback


def run_hooks(hooks, workers=None, label="pre-hooks"):
    """Run `hooks` concurrently and return {"results": [...], "wall_s": float, "errors": {...}}.

    `hooks` is a mapping {name: callable} or an iterable of (name, callable) pairs.
    Each callable takes no arguments. Non-None return values are collected in
    `results`, in completion order — callers that mutate shared state (the prompt)
    must do it serially from `results`, not inside the hook, which is the same
    contract the inline pipeline already follows.

    Fail-soft: a hook that raises is recorded in `errors` and does not stop the others.
    A hook that hangs is bounded by the caller's own timing guard, not here — cancelling
    a thread mid-flight is not something the stdlib can do safely, and a hook that hangs
    forever is a bug to see in the log rather than to hide behind a timeout.
    """
    items = list(hooks.items()) if hasattr(hooks, "items") else list(hooks or [])
    out = {"results": [], "wall_s": 0.0, "errors": {}}
    if not items:
        return out

    n = workers if workers is not None else hook_workers()
    n = max(1, min(int(n), len(items)))
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=n) as pool:
        futures = {pool.submit(fn): name for name, fn in items}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                result = fut.result()
            except Exception as e:
                out["errors"][name] = str(e)
                _log.debug("hook %s failed: %s", name, e)
                continue
            if result is not None:
                out["results"].append(result)
    out["wall_s"] = round(time.time() - t0, 3)

    # The number the 60s guard is judged against. INFO, not DEBUG: an operator asking
    # "why did my hooks get skipped" should not have to raise the log level to find out.
    _log.info("%s: %d hooks across %d workers in %.3fs (%d failed)",
              label, len(items), n, out["wall_s"], len(out["errors"]))
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import time as _t
    print(run_hooks({f"h{i}": (lambda: _t.sleep(0.1)) for i in range(5)}))
