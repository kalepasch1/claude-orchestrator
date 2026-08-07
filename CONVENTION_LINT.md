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
Module-level functions should not have a `self` parameter. Public functions at module scope should delegate to singleton instances, not be instance methods.

**Rationale:**
From CLAUDE.md conventions: "Module-level singleton pattern: Provide module-level functions that delegate to a thread-safe singleton instance (e.g., `acquire()` → `_pool.acquire()`); avoids passing state through call chains."

**Violation Pattern:**
```python
# ❌ VIOLATION: Public function has 'self' parameter
def acquire(self):
    return self.pool.acquire()

# ❌ VIOLATION: Should delegate to singleton, not be a method
def release(self, item):
    self.items.append(item)
```

**Fix Pattern:**
```python
_pool = None  # Private singleton

def acquire():
    global _pool
    if _pool is None:
        _pool = ResourcePool()
    return _pool.acquire()  # ✓ Delegate to singleton

def release(item):
    return _pool.release(item)  # ✓ Delegate to singleton
```

**Exception:**
Methods in classes (inside `class` definitions) can have `self` parameters freely.

**Disabling on a Line:**
```python
def acquire(self):  # noqa: MODULE_SINGLETON
    return self.pool.acquire()
```

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

**Test Classes:**
- `TestFailSoftErrorHandling` — 6 test cases for fail-soft rule
- `TestHardcodedSecrets` — 8 test cases for hardcoded secrets rule
- `TestModuleLevelSingletons` — 6 test cases for module singleton rule
- `TestIntegration` — 10 integration tests with multiple violations
- `TestEdgeCases` — 12 edge case tests
- `TestCLIAndFormatting` — 5 formatting and output tests

**Test Coverage:**
- 47+ test cases covering:
  - Normal compliance paths
  - Single violations per rule
  - Mixed violations across rules
  - Edge cases (nested functions, lambda, empty files, async functions)
  - False-positive avoidance (private functions, methods in classes)
  - `# noqa` skip logic
  - Output formatting (text and JSON)
  - Severity levels

**Running Tests:**
```bash
python -m pytest tests/test_convention_lint.py -v
python -m unittest tests.test_convention_lint
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
  │   ├─ to_dict(): JSON serialization
  │   └─ __str__(): Text formatting
  ├─ ConventionChecker: ast.NodeVisitor subclass
  │   ├─ _parse_noqa_comments(): Extract # noqa directives
  │   ├─ _is_rule_disabled(): Check if rule disabled on line
  │   ├─ visit_FunctionDef: Dispatch to rule checkers
  │   ├─ visit_AsyncFunctionDef: Handle async functions
  │   ├─ visit_ClassDef: Track class context
  │   ├─ visit_Assign: Check hardcoded secrets
  │   ├─ _check_fail_soft_error_handling: Rule 1 checker
  │   ├─ _check_hardcoded_secrets: Rule 2 checker
  │   ├─ _check_module_singletons: Rule 3 checker
  │   └─ _has_try_except_with_return: Helper for Rule 1
  ├─ check_file(filepath): Check single file, returns violations
  ├─ check_directory(directory): Recurse and check all .py files
  ├─ main(): CLI entry point with argument parsing
  └─ Exit codes: 0 (pass), 1 (violations)
```

**Design Notes:**
- AST-based: All checks use Python's `ast` module for syntax-aware analysis
- Noqa-aware: `# noqa: RULE_NAME` comments disable specific rules on a line
- Fail-soft: Violations are collected; errors don't stop processing
- Efficient: Single pass through AST; no external tools invoked

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
