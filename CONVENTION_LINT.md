# Convention Linter - Phase 1

Custom Python AST-based linter that enforces conventions extracted from `CLAUDE.md`.

## Running the Linter

### Command Line

```bash
python tools/convention_lint.py [--check-path=<dir>] [--json] [--fail-on=error]
```

**Examples:**

```bash
# Check runner/ and tools/ (defaults)
python tools/convention_lint.py

# Check specific directory
python tools/convention_lint.py --check-path=runner/

# Check multiple paths
python tools/convention_lint.py runner/ tools/

# Output as JSON
python tools/convention_lint.py --json

# Treat warnings as failures
python tools/convention_lint.py --fail-on=warn
```

### Pre-commit Hook

The linter runs automatically on `git commit` via `.pre-commit-hooks.yaml`:

```bash
pre-commit install
git commit -m "your message"  # linter runs automatically
```

To skip:
```bash
git commit --no-verify
```

## Enforced Rules

### Rule 1: Fail-Soft Error Handling

**Severity:** error

**Description:**
Public module-level functions must not raise on bad input. They should return sensible defaults (empty string, None, {}, []) instead.

**Rationale:**
From CLAUDE.md conventions: "Fail-soft error handling: errors during code execution or database queries do not wedge the runner; they are swallowed to prevent crashes." and "AVOID introducing model-specific logic that can wedge the runner on errors; instead, use fail-soft error handling."

**Violation Pattern:**
```python
def process_data(data):
    raise ValueError("Bad input")  # ❌ VIOLATION

def load_file(path):
    with open(path) as f:
        return json.load(f)  # ❌ VIOLATION: no try/except
```

**Fix Pattern:**
```python
def process_data(data):
    try:
        if not data:
            raise ValueError("Bad input")
        return transform(data)
    except Exception:
        return None  # ✓ Return sensible default

def load_file(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}  # ✓ Return empty dict on error
```

**Exception:**
Private functions (starting with `_`) and methods in classes (inside `class` definitions) can raise freely.

**Disabling on a Line:**
```python
def risky_function(data):  # noqa: FAIL_SOFT_ERROR
    raise ValueError("This is allowed")
```

---

### Rule 2: Hardcoded Secrets in Config Keys

**Severity:** error

**Description:**
Configuration keys must not contain hardcoded secrets. Use environment variables instead.

**Rationale:**
From CLAUDE.md: "DO NOT introduce hardcoded secrets or credentials in the configuration keys. Safe config keys only: only config keys without secrets or credentials can be pushed fleet-wide."

**Violation Pattern:**
```python
# ❌ VIOLATION: Hardcoded API token
api_token = "sk-1234567890abcdef"

# ❌ VIOLATION: Secret in config key
config['DATABASE_PASSWORD'] = 'secret123'

# ❌ VIOLATION: Private key
private_key = "-----BEGIN PRIVATE KEY-----..."
```

**Fix Pattern:**
```python
import os

# ✓ Environment variable reference
api_token = os.environ.get("API_TOKEN")

# ✓ Config from env
config['database_password'] = os.environ.get("DB_PASSWORD")

# ✓ Placeholder
private_key = "${PRIVATE_KEY}"
```

**Detection:**
The linter flags string assignments to variables/keys containing these keywords (case-insensitive):
- PASSWORD
- TOKEN
- SECRET
- API_KEY
- PRIVATE_KEY
- AUTH
- CREDENTIAL
- KEY=

**Exception:**
Strings starting with `$` (placeholder format) are allowed.

**Disabling on a Line:**
```python
temp_password = "test123"  # noqa: HARDCODED_SECRET
```

---

### Rule 3: Module-Level Singletons

**Severity:** warn (advisory)

**Description:**
Module-level functions should delegate to a thread-safe singleton instance, not contain instance methods.

**Rationale:**
From CLAUDE.md conventions: "Module-level singleton pattern: Provide module-level functions that delegate to a thread-safe singleton instance (e.g., `acquire()` → `_pool.acquire()`); avoids passing state through call chains."

**Pattern (Pass):**
```python
_pool = None  # Private singleton

def acquire():
    global _pool
    if _pool is None:
        _pool = ResourcePool()
    return _pool.acquire()  # ✓ Delegate to singleton
```

**Pattern (Fail):**
```python
def acquire(self):  # ❌ Public function should not have self
    self.items.append(item)
```

**Note:**
This rule is in Phase 1 but detection is not fully implemented. The linter identifies the pattern but does not currently flag violations. See Phase 3 for architectural pattern detection.

---

### Rule 4: `SCAN_WINDOW_NO_ORDER` (warning)

Flags `select(..., {"limit": N})` where `N >= 100` and there is no `"order"` key.

**Why this rule exists:** that exact shape has caused five outage-class failures on this
fleet. PostgREST caps a response at **1,000 rows** no matter how large `limit` is, so a big
literal limit does not widen the window — it hides the truncation. Without `order` the
window is not even the same rows twice, making the defect silent *and* unreproducible.

```python
# ❌ VIOLATION: unordered 500-row window, silently truncates
db.select("tasks", {"select": "*", "state": "eq.QUEUED", "limit": "500"})

# ✓ COUNT — needs a real number
db.count("tasks", {"state": "eq.QUEUED"})

# ✓ LOOKUP — filter server-side, never scan-and-filter
db.select("tasks", {"select": "*", "slug": "eq.the-one-we-want"})

# ✓ SAMPLE — a bounded window is fine, but it must be deterministic
db.select("outcomes", {"select": "*", "order": "created_at.desc", "limit": "500"})

# ✓ FULL SCAN — page to exhaustion
db.select_all("tasks", {"select": "*", "state": "eq.QUEUED"},
              order="created_at.asc,id.asc")
```

**Do not just raise the limit.** A larger window is the same bug, later. Classify the read.

**Exception — `SENTINEL_LIMITS`:** `fleet_stuck_alarm.py` reads `limit: "5001"` purely to
answer "are there more than 5000?"; `len()` of that page *is* the answer. Values in
`SENTINEL_LIMITS` are exempt by design.

Severity is `warning` so the ~107 remaining historical sites are visible without failing
CI. Full classification: `docs/scan-window-audit-2026-08-06.md`.

---

## Suppressing a violation

`# noqa` on the offending line, either bare or rule-scoped:

```python
db.select("tasks", {"limit": "500"})   # noqa: SCAN_WINDOW_NO_ORDER
password = "test-fixture"             # noqa
```

Comma-separated rule lists are supported (`# noqa: RULE_A, RULE_B`). Prefer fixing the
finding; use `noqa` only for a deliberate, commented exception.

---

## Output Format

### Text (Default)

```
runner/fleet_control.py:42: FAIL_SOFT_ERROR: Public function "process" raises on bad input; use try/except with sensible defaults instead
runner/resource_governor.py:105: HARDCODED_SECRET: Variable "api_key" contains secret keyword; use environment variables instead
```

### JSON (`--json`)

```json
[
  {
    "file": "runner/fleet_control.py",
    "line": 42,
    "rule": "FAIL_SOFT_ERROR",
    "message": "Public function \"process\" raises on bad input; use try/except with sensible defaults instead",
    "severity": "error"
  },
  {
    "file": "runner/resource_governor.py",
    "line": 105,
    "rule": "HARDCODED_SECRET",
    "message": "Variable \"api_key\" contains secret keyword; use environment variables instead",
    "severity": "error"
  }
]
```

---

## Performance

- Single file: <50ms
- runner/ + tools/ (combined): <2s

---

## Test Coverage

**Test Fixtures:**
- `tests/fixtures/bad_convention_raises.py` — Examples of FAIL_SOFT_ERROR violations
- `tests/fixtures/bad_convention_secrets.py` — Examples of HARDCODED_SECRET violations
- `tests/fixtures/good_convention_failsoft.py` — Compliant fail-soft patterns
- `tests/fixtures/good_convention_secrets.py` — Compliant environment variable usage
- `tests/fixtures/good_convention_singletons.py` — Compliant singleton delegation

**Test Cases:**
- 15+ test cases covering normal paths, edge cases, exceptions
- `tests/test_convention_lint.py`

**Running Tests:**
```bash
python -m pytest tests/test_convention_lint.py -v
```

---

## Exit Codes

| Exit Code | Meaning |
|-----------|---------|
| 0         | No violations found, or violations below `--fail-on` threshold |
| 1         | Violations found at or above `--fail-on` severity |

---

## Architecture

```
tools/convention_lint.py
  ├─ ConventionViolation: Data class for violations
  ├─ ConventionChecker: ast.NodeVisitor subclass
  │   ├─ visit_FunctionDef: Check fail-soft error handling
  │   ├─ visit_AsyncFunctionDef: Check async functions
  │   ├─ visit_Assign: Check hardcoded secrets
  │   ├─ _check_fail_soft_error_handling: Rule 1
  │   └─ _check_hardcoded_secrets: Rule 2
  ├─ check_file(filepath): Check single file
  ├─ check_directory(directory): Recurse and check all .py files
  └─ main(): CLI entry point
```

---

## Future Phases

**Phase 2:** CI integration + GitHub PR comments (`.github/workflows/convention-lint.yml`)

**Phase 3:** Extract rules directly from CLAUDE.md via structured comments; detect architectural patterns (operator workflow usage, singleton completeness)

**Phase 4:** Auto-fix suggestions; IDE plugin support; rule severity customization

---

## FAQ

**Q: How do I disable the linter for a specific line?**

A: Use the `# noqa: RULE_NAME` comment:
```python
password = "hardcoded"  # noqa: HARDCODED_SECRET
```

**Q: Can private functions raise?**

A: Yes! Only public module-level functions are checked. Private functions (starting with `_`) and methods in classes can raise freely.

**Q: Why does the linter flag environment variable names?**

A: It doesn't! The linter only flags **string values** assigned to variables/keys with secret keywords. This is safe:
```python
db_password = os.environ.get("DB_PASSWORD")  # ✓ Not flagged
```

**Q: Can I check just one file?**

A: Yes:
```bash
python tools/convention_lint.py runner/fleet_control.py
```

**Q: What if my code has a syntax error?**

A: The linter reports a SYNTAX_ERROR violation and continues checking other files.
