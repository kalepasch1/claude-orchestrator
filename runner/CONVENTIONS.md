# Convention Linter for claude-orchestrator/runner

This document describes the 5 key conventions enforced by the convention linter on all Python files in the runner directory.

## Overview

The convention linter enforces architectural and safety constraints that keep the runner resilient, maintainable, and fleet-wide configurable. Rules are checked via static analysis using Python's `ast` module.

**Run the linter:**
```bash
python runner/tools/lint_conventions.py
python runner/tools/lint_conventions.py runner/fleet_control.py
python runner/tools/lint_conventions.py runner/
```

## Rule 1: ORCH_ Prefix for Config Keys

**Convention (CLAUDE.md L26):** Config key changes must use `ORCH_` prefix for fleet-wide applicability.

**Rule:** Detect assignments to config dicts (e.g., `fleet_config["KEY"]`) that don't have an `ORCH_` prefix and are not in the safe allowlist.

**Why:** The runner synchronizes configuration across multiple machines via a central database. Only keys prefixed with `ORCH_` are considered safe to propagate fleet-wide. Hardcoding config keys without the prefix breaks this contract and risks inconsistent state.

**Safe keys (no prefix required):**
- `MAX_PARALLEL`
- `MAX_RETRIES`
- `TIMEOUT`
- `DEBUG`
- `LOG_LEVEL`
- `PORT`
- `HOST`

### Examples

✅ **Pass:**
```python
fleet_config["ORCH_MAX_WORKERS"] = 10
config["ORCH_FEATURE_FLAG"] = True
safe_config["MAX_RETRIES"] = 3
```

❌ **Fail:**
```python
fleet_config["MY_KEY"] = value  # Missing ORCH_ prefix
config["WORKER_COUNT"] = 5      # Not in safe allowlist
```

---

## Rule 2: No Hardcoded Secrets in Config Keys

**Convention (CLAUDE.md L27):** Only config keys without secrets or credentials can be pushed fleet-wide.

**Rule:** Detect config keys or variables that:
1. Contain secret patterns: `secret`, `key`, `token`, `password`, `api_key`, `pat` (case-insensitive)
2. Are assigned hardcoded credential values like `sk-...`, `pk_...`, `secret_...`

**Why:** Hardcoded credentials in code violate security best practices and compliance requirements. The runner dynamically reads all credentials from environment variables, ensuring they're never committed to version control.

### Examples

✅ **Pass:**
```python
api_token = os.getenv("ORCH_API_TOKEN")
os.environ["ORCH_GIT_AUTH_REQUIRED"] = "true"  # Value signals need; actual token from env
config["ORCH_ENABLE_AUTH"] = True              # Boolean flag, not secret
```

❌ **Fail:**
```python
os.environ["ORCH_API_KEY"] = "sk-proj-abc123def456"  # Hardcoded secret
secret_token = "Bearer token_abc123xyz"              # Hardcoded credential
fleet_config["ORCH_DATABASE_PASSWORD"] = db_pwd      # Secret in key name
```

---

## Rule 3: Fail-Soft Error Handling

**Convention (CLAUDE.md L22, L36):** Errors during code execution must not wedge the runner; return sensible defaults instead of crashing or silently failing.

**Rule:** Flag:
1. Bare `except:` clauses (catches all exceptions including SystemExit, KeyboardInterrupt)
2. `except Exception:` handlers that don't return a sensible default
3. Unhandled exceptions in module-level functions (should be caught at boundaries)

**Why:** The runner is a long-lived, fleet-deployed service. A single unhandled exception or bare except that doesn't recover crashes the whole process. All error handling must gracefully degrade by returning safe defaults (empty string, empty dict, None).

### Examples

✅ **Pass:**
```python
def read_config(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}  # Sensible default for missing config

def fetch_data(url):
    try:
        return requests.get(url, timeout=5).json()
    except (ConnectionError, Timeout):
        return []  # Empty list is sensible default for fetch failure
```

❌ **Fail:**
```python
def risky_operation():
    try:
        something()
    except:  # Bare except is dangerous
        pass

def process_data(data):
    try:
        return transform(data)
    except Exception:  # No return statement
        log_error()  # Falls through, returns None implicitly
```

---

## Rule 4: Module-Level Singleton Pattern

**Convention (CLAUDE.md L35):** Provide module-level functions that delegate to a thread-safe singleton instance; avoid passing state through call chains.

**Rule:** Flag module-level functions that have `self` as a parameter (mixing class and module API).

**Why:** The runner uses a thread-safe singleton pattern for shared resources (connection pools, caches, config). Module-level functions like `acquire()` should delegate to the singleton, not expose class methods at module level. This keeps the API clean and prevents callers from accidentally instantiating multiple singletons.

### Examples

✅ **Pass:**
```python
_pool = None  # Module-level singleton

def acquire():
    """Module-level delegation to singleton."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool()
    return _pool.acquire()

class ConnectionPool:
    def acquire(self):
        """Instance method."""
        return self._get_connection()
```

❌ **Fail:**
```python
def acquire(self):  # Module-level with self parameter
    return self._pool.acquire()

def release(self, conn):  # Module-level with self parameter
    self._pool.release(conn)
```

---

## Rule 5: Return Sensible Defaults on Error

**Convention (CLAUDE.md L36, L44):** Design for graceful degradation; missing files → return `""`, missing data → return `[]` or `{}`, never force caller to handle unavailability.

**Rule:** Flag functions that:
1. Raise `ValueError`, `TypeError`, `KeyError` on input validation (None, empty string, missing path)
2. Lack error handlers for expected failures (file not found, permission denied)

**Why:** Callers shouldn't be forced to wrap every function call in try/except. Well-designed functions return safe defaults for expected error cases, letting callers ignore them. Only raise exceptions for truly exceptional cases (bugs, corruption).

### Examples

✅ **Pass:**
```python
def get_user(user_id):
    """Returns user or empty dict on not found."""
    user = db.query(f"SELECT * FROM users WHERE id={user_id}")
    return user if user else {}

def read_cache_file(path):
    """Returns cache content or empty string on error."""
    if not path:
        return ""
    try:
        with open(path) as f:
            return f.read()
    except (FileNotFoundError, IOError):
        return ""

def parse_config(config_str):
    """Returns parsed config or sensible default on parse failure."""
    if not config_str:
        return {}
    try:
        return json.loads(config_str)
    except json.JSONDecodeError:
        return {}
```

❌ **Fail:**
```python
def get_user(user_id):
    if not user_id:
        raise ValueError("user_id required")  # Return {} instead
    user = db.query(f"SELECT * FROM users WHERE id={user_id}")
    return user

def read_file(path):
    if not path:
        raise ValueError("path required")  # Return "" instead
    with open(path) as f:
        return f.read()  # Raises FileNotFoundError, no fallback

def parse_config(config_str):
    return json.loads(config_str)  # Raises on parse error, no fallback
```

---

## Running the Linter

### Check all Python files in runner:
```bash
cd /Users/kpasch/Documents/beethoven/claude-orchestrator
python runner/tools/lint_conventions.py
```

### Check specific files:
```bash
python runner/tools/lint_conventions.py runner/fleet_control.py runner/db.py
```

### Check a subdirectory:
```bash
python runner/tools/lint_conventions.py runner/bots/
```

### Run tests:
```bash
python -m pytest runner/tests/test_lint_conventions.py -v
```

### Pre-commit hook (optional):
```bash
# Copy hook to .git/hooks/pre-commit
cp runner/tools/lint_conventions.py .git/hooks/pre-commit
# Or add manually to existing pre-commit hook
```

---

## Output Format

Violations are printed in standard linter format:
```
runner/fleet_control.py:42:config-orch-prefix: Config key 'MY_KEY' missing ORCH_ prefix or not in safe allowlist
runner/db.py:105:fail-soft-error-handling: Bare 'except:' clause found; use specific exceptions and return sensible default
runner/cache.py:23:module-singleton-pattern: Module-level function 'acquire' has 'self' parameter; use module delegation instead
```

**Exit codes:**
- `0`: No violations found
- `1`: One or more violations found

---

## Updating the Linter

To add new rules or update existing ones:

1. Edit `runner/tools/lint_conventions.py`: Add detection logic to `ConventionChecker`
2. Add test cases to `runner/tests/test_lint_conventions.py`
3. Update this document with the new rule
4. Run tests to verify: `python -m pytest runner/tests/test_lint_conventions.py`

---

## Exceptions

In rare cases, a violation may be justified. Document it with an inline comment:

```python
# Convention exception: bare except used to catch runner crash and restart
try:
    main()
except:  # noqa: E722
    log.critical("Runner crashed, restarting...")
    restart()
```

Note: The linter does not yet support `# noqa` suppressions; this is a future enhancement.
