# Convention Lint Rules

Automated enforcement of coding conventions extracted from `CLAUDE.md` for the claude-orchestrator project. These rules catch style mismatches early, eliminating rework cycles in code review.

**Scope**: Agent-generated code on branches prefixed with `agent/*`  
**Tool**: `tools/lint_conventions.py`  
**Entry Point**: `.pre-commit-hooks.yaml` (pre-commit) and GitHub Actions CI

---

## Rule 1: Configuration Key Naming

**Convention**: Fleet-wide config keys MUST start with `ORCH_` prefix (safe keys only).

**Rationale**: Centralized config management in `fleet_control.py` applies config changes fleet-wide to all machines. The `ORCH_` prefix ensures keys are explicitly marked as safe for fleet-wide propagation. Keys without this prefix are assumed to be local-only or to contain secrets/credentials.

**Check**: Flag dictionary/assignment keys in `runner/`, `fleet_control.py` that don't match pattern `ORCH_[A-Z_]+`

### Pass Examples

```python
# Config keys with ORCH_ prefix
config['ORCH_POOL_SIZE'] = 16
config['ORCH_TIMEOUT'] = 30
config['ORCH_MAX_RETRIES'] = 3

# Non-config context (dictionary literals)
data = {'name': 'Alice', 'age': 30}
metadata = {'version': '1.0', 'author': 'bot'}
```

### Fail Examples

```python
# Missing ORCH_ prefix
config['POOL_SIZE'] = 16  # ❌ Should be ORCH_POOL_SIZE

# API keys (credentials, never in config)
config['API_KEY'] = os.getenv('SECRET')  # ❌ No ORCH_ prefix, likely a secret

# Hardcoded secret-like keys
config['DATABASE_URL'] = 'postgres://...'  # ❌ Should never be in config
```

---

## Rule 2: Fail-Soft Error Handling

**Convention**: Functions handling external I/O (file, network, DB) MUST return `""` or sensible defaults on error; never raise on bad input (None, missing path, permission denied).

**Rationale**: Errors during code execution or database queries do not wedge the runner. Fail-soft design prevents cascading failures and keeps the fleet healthy. Raising exceptions on bad input forces callers to handle unavailability — instead, design for graceful degradation.

**Check**: Flag try-except blocks that re-raise or lack default return; flag unguarded I/O calls

### Pass Examples

```python
# Return empty string on error
def read_file(path):
    try:
        return open(path).read()
    except:
        return ""

# Return None on missing data
def load_config(path):
    try:
        with open(path) as f:
            return json.load(f)
    except:
        return None

# Return default dict
def fetch_api_data():
    try:
        return requests.get(url, timeout=5).json()
    except:
        return {}

# Return False on unavailability
def is_database_ready():
    try:
        return db.ping()
    except:
        return False
```

### Fail Examples

```python
# No exception handler — unguarded I/O
def read_file(path):
    return open(path).read()  # ❌ Will raise on missing file

# Re-raise without default
def load_data(path):
    try:
        return open(path).read()
    except FileNotFoundError:
        raise  # ❌ Should return ""

# Empty handler without return
def safe_operation():
    try:
        risky_call()
    except:
        pass  # ❌ Should return a sensible default

# Forcing caller to handle
def fetch_user(user_id):
    # ❌ Caller must handle exceptions
    response = requests.get(f'/api/users/{user_id}')
    return response.json()
```

---

## Rule 3: Thread Safety

**Convention**: Shared state (class attributes, module globals) MUST be protected with `threading.Lock()` or wrapped via `@property` guards.

**Rationale**: The runner uses threads for concurrent operations. Unguarded mutations to shared state cause data races. Explicit locks (or property-based guards) make thread safety visible and verifiable.

**Check**: Flag assignments to `self._state`, `self._cache`, `self._pool` (and similar) outside lock context

### Pass Examples

```python
import threading

class ConnectionPool:
    def __init__(self):
        self._lock = threading.Lock()
        self._connections = []

    def acquire(self):
        with self._lock:
            if self._connections:
                return self._connections.pop()
        return None

    def release(self, conn):
        with self._lock:
            self._connections.append(conn)

    @property
    def size(self):
        with self._lock:
            return len(self._connections)

# Module-level singleton
_pool = ConnectionPool()

def acquire():
    return _pool.acquire()
```

### Fail Examples

```python
class ConnectionPool:
    def __init__(self):
        self._connections = []

    def acquire(self):
        # ❌ Unguarded mutation to shared state
        return self._connections.pop()

    def add(self, conn):
        # ❌ No lock protection
        self._connections.append(conn)

# Module global without protection
_cache = {}

def cache_set(key, value):
    # ❌ Unguarded mutation to module global
    _cache[key] = value
```

---

## Rule 4: Naming Consistency

**Convention**: Use `snake_case` for variables and functions; `SCREAMING_SNAKE_CASE` for module constants; descriptive names (no abbreviations like `tmp`, `cfg`, `x`).

**Rationale**: Consistent naming improves readability and catches typos. Magic numbers are harder to understand and maintain than named constants. Abbreviations lose meaning over time.

**Check**: Flag functions not in `snake_case`; flag assignments to abbreviations; flag magic numbers in comparisons/returns

### Pass Examples

```python
# snake_case functions and variables
def load_configuration():
    config = read_file('config.json')
    timeout_seconds = config.get('timeout', 30)
    return config

# SCREAMING_SNAKE_CASE constants
MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30
POOL_SIZE = 16

# Descriptive variable names
def process_items():
    start_time = time.time()
    max_attempts = 5
    for attempt in range(max_attempts):
        if time.time() - start_time > DEFAULT_TIMEOUT:
            break
    return result
```

### Fail Examples

```python
# ❌ camelCase function
def loadConfiguration():
    pass

# ❌ Abbreviated variable names
def process():
    cfg = load_config()  # Should be: config = load_config()
    tmp = parse(cfg)  # Should be: parsed_config = parse(config)
    t = time.time()  # Should be: current_time = time.time()

# ❌ Magic numbers without constants
if attempts > 3:  # Should use: MAX_RETRIES constant
    retry()

if elapsed_time > 30:  # Should use: DEFAULT_TIMEOUT constant
    timeout()
```

---

## Rule 5: Module Structure (Singleton Delegation)

**Convention**: Prefer module-level functions that delegate to thread-safe singleton instances; avoid passing state (pool, cache, logger) through function signatures.

**Rationale**: Singleton delegation keeps the public API simple and avoids threading state through call chains. Module-level functions are the public interface; private singletons handle shared state.

**Check**: Flag functions that accept `pool`, `cache`, `logger`, or similar state as parameters

### Pass Examples

```python
# Module private singleton
class _ResourcePool:
    def __init__(self):
        self._lock = threading.Lock()
        self._items = []

    def acquire(self):
        with self._lock:
            if self._items:
                return self._items.pop()
        return None

_pool = _ResourcePool()

# Public API delegates to singleton
def acquire():
    return _pool.acquire()

def process():
    resource = acquire()  # Use module-level function, not pass pool
    if resource:
        use_resource(resource)
```

### Fail Examples

```python
# ❌ Passing state through parameters
def process(pool, cache, logger):
    resource = pool.acquire()
    cached_value = cache.get('key')
    logger.info('Processing...')

# ❌ No clear separation of public API from implementation
def main():
    pool = ConnectionPool()
    cache = Cache()
    process(pool, cache)  # Should use module-level functions instead

# ❌ Module-level state accessed directly
_cache = {}

def cache_set(key, value):
    _cache[key] = value  # Unguarded access to module global
```

---

## Enforcement

### Pre-Commit Hook
Runs locally on `agent/*` branches before commit:
```bash
python tools/lint_conventions.py runner/
```
Exits with code 1 if violations found; blocks commit.

### GitHub Actions CI
Runs on PRs with `agent/` in branch name; blocks merge if violations detected.

### Local Usage
```bash
# Check a single file
python tools/lint_conventions.py runner/my_module.py

# Check a directory
python tools/lint_conventions.py runner/

# Check multiple targets
python tools/lint_conventions.py runner/ fleet_control.py
```

---

## Success Criteria

- All `agent/*` branches pass lint on first push (zero rework cycles)
- Pre-commit runs in <500ms
- Linter correctly identifies all 5 rule violations in test cases (20+ tests)
- Documentation matches CLAUDE.md conventions

## Related

- [CLAUDE.md](../CLAUDE.md) — Full project conventions
- [lint_conventions.py](../tools/lint_conventions.py) — Linter implementation
- [test_lint_conventions.py](../tests/test_lint_conventions.py) — Test suite (20+ cases)
