# Convention Linting

This repository uses AST-based convention linting to enforce patterns from `CLAUDE.md` before commit.

## Running the Linter

### Command Line
```bash
python tools/lint_conventions.py <file_or_dir> [<file_or_dir> ...]
```

Examples:
```bash
python tools/lint_conventions.py runner/
python tools/lint_conventions.py runner/fleet_control.py
python tools/lint_conventions.py .
```

### Pre-commit Hook
The linter runs automatically on `git commit` via `.pre-commit-config.yaml`:
```bash
pre-commit install
git commit -m "your message"  # linter runs automatically
```

To skip the linter:
```bash
git commit --no-verify
```

## Enforced Rules

### 1. Configuration Key Naming (ORCH_ Prefix)
**Rule:** All fleet_config keys must start with `ORCH_` prefix.

**Rationale:** Ensures fleet-wide config keys are explicitly named and distinguishable from local variables (from CLAUDE.md line 26).

**Example (Pass):**
```python
fleet_config['ORCH_POOL_SIZE'] = 16
fleet_config['ORCH_TIMEOUT'] = 30
config['ORCH_MAX_RETRIES'] = 3
```

**Example (Fail):**
```python
fleet_config['POOL_SIZE'] = 16  # Missing ORCH_ prefix
config['TIMEOUT'] = 30          # Missing ORCH_ prefix
```

**Exception:** Environment variables (os.environ) and non-config dicts do not require ORCH_ prefix.

### 2. Fail-Soft Error Handling
**Rule:** All `try`/`except` blocks must return a sensible default (empty string, None, {}, []).

**Rationale:** Prevents crashes on bad input; code should never raise on user input (from CLAUDE.md conventions).

**Example (Pass):**
```python
def read_file(path):
    try:
        return open(path).read()
    except:
        return ""

def load_config(path):
    try:
        return json.load(path)
    except:
        return {}
```

**Example (Fail):**
```python
def safe_operation():
    try:
        risky_call()
    except:
        pass  # No return statement
```

### 3. Thread Safety
**Rule:** Shared mutable state must be protected with `threading.Lock()`.

**Rationale:** Prevents race conditions in multi-threaded contexts (from CLAUDE.md conventions).

**Example (Pass):**
```python
class Cache:
    def __init__(self):
        self._lock = threading.Lock()
        self._cache = {}

    def set(self, key, value):
        with self._lock:
            self._cache[key] = value
```

### 4. Naming Conventions
**Rule:** Use `snake_case` for functions/variables and `SCREAMING_SNAKE_CASE` for constants.

**Rationale:** Consistent style per PEP 8 (from CLAUDE.md conventions).

**Example (Pass):**
```python
def load_configuration():  # snake_case
    pass

MAX_RETRIES = 3  # SCREAMING_SNAKE_CASE
DEFAULT_TIMEOUT = 30

for i in range(10):  # Loop variables: i, j, k allowed
    pass
```

**Example (Fail):**
```python
def loadConfiguration():  # camelCase not allowed
    pass

cfg = load_config()  # Abbreviated names not allowed
x = get_value()     # Single letter outside loop
```

### 5. Magic Numbers
**Rule:** Magic numbers must be assigned to named constants.

**Rationale:** Improves readability and maintainability (from CLAUDE.md conventions).

**Example (Pass):**
```python
MAX_RETRIES = 3
if attempts > 0:  # 0, 1, -1 are allowed
    pass
```

**Example (Fail):**
```python
if attempts > 3:  # Magic number in comparison
    pass

timeout_seconds = 30  # Magic number in assignment
```

## Adding New Rules

To add a new convention rule:

1. **Define the rule in CLAUDE.md:** Document the convention and rationale.

2. **Add AST visitor method in ConventionChecker:** Edit `tools/lint_conventions.py`:
   ```python
   def visit_YourNode(self, node: ast.YourNode) -> None:
       """Check for your convention."""
       if violation_condition:
           self.violations.append(ConventionViolation(
               self.filepath, node.lineno, 'YOUR_RULE_NAME',
               'Description of the violation'
           ))
       self.generic_visit(node)
   ```

3. **Add test cases in tests/test_lint_conventions.py:**
   ```python
   class TestYourRule(unittest.TestCase):
       """Test rule: Your rule description."""
       
       def test_pass_example(self):
           """Valid pattern passes."""
           code = "your_code_here()"
           violations = self._check_code(code)
           your_violations = [v for v in violations if v.rule == 'YOUR_RULE_NAME']
           self.assertEqual(your_violations, [])
       
       def test_fail_example(self):
           """Invalid pattern fails."""
           code = "bad_code_here()"
           violations = self._check_code(code)
           your_violations = [v for v in violations if v.rule == 'YOUR_RULE_NAME']
           self.assertGreater(len(your_violations), 0)
   ```

4. **Run tests:** `python -m pytest tests/test_lint_conventions.py -v`

5. **Commit:** Include rule definition in CLAUDE.md + implementation + tests.

## Architecture

```
tools/lint_conventions.py          # AST-based linter
  └─ ConventionChecker             # ast.NodeVisitor subclass
     ├─ visit_Assign               # Config key checking
     ├─ visit_FunctionDef          # Naming, error handling
     ├─ visit_Try                  # Fail-soft checking
     └─ ... (other visitors)

tests/test_lint_conventions.py     # 36 test cases covering all rules
  ├─ TestConfigKeyNaming          # 6 tests
  ├─ TestFailSoftErrorHandling    # 6 tests
  ├─ TestThreadSafety             # 3 tests
  ├─ TestMagicNumbers             # 4 tests
  ├─ TestNamingConventions        # 7 tests
  ├─ TestIntegration              # 2 tests
  ├─ TestEdgeCases                # 5 tests
  └─ TestViolationStructure       # 3 tests
```

## Design for Future

Future versions may:
- Extract rules directly from CLAUDE.md via structured comments
- Generate linter from `rules.yaml` manifest
- Support rule severity levels (error, warning)
- Provide auto-fix suggestions
- Integrate with IDE plugins

Today's linter is focused on MVP: catching ORCH_ prefix violations in fleet_config assignments before merge.
