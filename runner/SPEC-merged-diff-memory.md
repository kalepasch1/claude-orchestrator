# Specification: merged-diff-memory

**Status:** Implemented (thread-safe singleton cache with TTL and size limits)
**Eviction strategy:** LRU by access time; entries exceeding TTL are lazily pruned on next access.

## Overview
Thread-safe in-process cache for diff results computed from merged branches/PRs. Stores diffs keyed by `(branch_a, branch_b, merge_commit)` and returns cached results within TTL. Fails soft on all errors and memory pressure—returns empty string rather than raising.

## Problem Statement
Computing diffs from merged branches is expensive and results are frequently re-requested during operator sessions and merge evaluation. A local cache avoids redundant computations and reduces API calls.

## Acceptance Criteria

### Functional Requirements
- ✅ Store and retrieve diffs keyed by `(branch_a, branch_b, commit_hash)`
- ✅ Expire cached entries after TTL (default 3600s, configurable via `ORCH_DIFF_CACHE_TTL`)
- ✅ Enforce maximum cache size (default 100MB, configurable via `ORCH_DIFF_CACHE_SIZE`)
- ✅ Truncate individual diffs that exceed 10% of cache size
- ✅ Thread-safe concurrent access via `threading.Lock()`
- ✅ Fail-soft error handling: return empty string on any error, never raise to caller
- ✅ Integrate with `resource_governor.can_claim()` to respect cluster memory pressure

### API Specification

**Module-level functions (thread-safe singleton delegators):**
- `get_diff(branch_a: Optional[str], branch_b: Optional[str], commit_hash: Optional[str]) -> str`
  - Returns cached diff string on hit, empty string on miss/error/TTL-expired
  - Returns empty string if any key is None or empty string
  
- `put_diff(branch_a: Optional[str], branch_b: Optional[str], commit_hash: Optional[str], diff_content: Optional[str]) -> None`
  - Caches diff if all keys and content are non-empty
  - Silently ignores put if any parameter is None or empty string
  - Returns silently on error (no exception raised)

- `stats() -> Dict[str, int]`
  - Returns `{entries: int, bytes_used: int, hits: int, misses: int}`
  - Thread-safe snapshot of cache state
  
- `invalidate() -> None`
  - Clears all cached diffs and resets counters
  - Thread-safe, idempotent

### Non-Functional Requirements
- ✅ **Thread-safety:** All public methods thread-safe via `threading.Lock()`
- ✅ **Fail-soft:** No public method raises on error; all errors swallowed silently
- ✅ **Configuration:** All tunables are environment variables with sensible defaults
- ✅ **Resource awareness:** Respects `resource_governor` if available; gracefully handles if missing
- ✅ **Memory bounded:** Hard limit on total bytes cached (100MB default)
- ✅ **Per-entry limit:** Individual entries truncated to 10% of cache size
- ✅ **Unicode:** Handles unicode content correctly with `errors="replace"`

## Implementation Files
- **Primary:** `/runner/merged_diff_memory.py` (169 lines)
- **Tests:** `/runner/test_merged_diff_memory.py` (560 lines, 30+ test cases)

## Environment Variables
| Variable | Default | Purpose |
|---|---|---|
| `ORCH_DIFF_CACHE_TTL` | 3600 | Time-to-live in seconds |
| `ORCH_DIFF_CACHE_SIZE` | 100 | Max cache size in MB |

## Test Coverage
**30+ test cases covering:**
- ✅ Normal paths: cache hit, miss, TTL expiry
- ✅ Edge cases: None/empty keys, None/empty content, unicode
- ✅ Size limits: eviction, truncation, resource_governor blocking
- ✅ Concurrency: 10+ threads concurrent get/put/invalidate
- ✅ Error handling: exception swallowing, graceful degradation
- ✅ Multiple keys: different branches/commits create separate entries
- ✅ Large content: 5-50MB diffs within and exceeding limits
- ✅ Stats/invalidate: accurate counting, idempotence

## Integration Points
- **`resource_governor.py`:** Optional; `can_claim()` gated on memory pressure
- **Operators:** Can call `stats()` to observe cache health; `invalidate()` to reset
- **Merge evaluation pipelines:** Call `put_diff()` after computing merge diff; call `get_diff()` to reuse

## Guarantees
1. **Atomicity within operations:** Each get/put/stats/invalidate is atomic w.r.t. concurrent calls
2. **No exceptions to caller:** All errors (bad keys, I/O, resource limits) silently handled
3. **Memory bounded:** Cache size hard-limited; oversized entries truncated, not stored
4. **TTL enforcement:** Expired entries auto-evicted on access
5. **Idempotent invalidate:** Safe to call multiple times, from multiple threads

## Success Metrics
- Cache hit rate > 80% in operator sessions (tracked via `stats()`)
- Memory usage stays within configured limit under load
- No deadlocks under concurrent load (20+ threads)
- Zero exceptions raised to callers on bad input or resource pressure
