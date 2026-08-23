# Smart Contract Validation & Legal Gating

## Overview

Smart contract validation enforces legal/licensing gates on fleet-wide configuration changes. Changes touching licensing, registration, custody, transmission, or advice—or containing credential markers—require owner-only approval before deployment.

## Architecture

The validation system consists of three core functions working together:

1. **detect_legal_trigger(config_key)** — Identifies keys requiring legal review
2. **validate_contract_change(old_val, new_val, key)** — Validates change rules
3. **legal_gate_required(change_dict)** — Determines if approval is needed

All functions follow **fail-soft error handling**: invalid input returns a sensible default (False/"") without raising exceptions. This prevents a validation bug from wedging the runner.

## Legal Triggers

A configuration key triggers the legal gate if it:

### Licensing & Registration
- Contains: `license`, `copyright`, `patent`, `terms`
- Contains: `register`, `registration`, `enroll`, `activation`

### Custody & Ownership
- Contains: `custody`, `owner`, `steward`, `guardian`

### Data Transmission
- Contains: `transmission`, `transfer`, `handoff`, `migrate`

### Advisory & Guidance
- Contains: `advice`, `recommendation`, `counsel`, `guidance`

### Credential Markers
Any key containing credential markers triggers the gate (highest priority):
- `PASSWORD`, `TOKEN`, `SECRET`, `KEY`, `API_KEY`, `CREDENTIAL`, `PAT`

Examples of triggering keys:
- `ORCH_LICENSE_KEY` → licensing gate
- `REGISTRATION_ID` → registration gate
- `CUSTODY_PROVIDER` → custody gate
- `TRANSMISSION_ENABLED` → transmission gate
- `DB_PASSWORD` → credential marker
- `GITHUB_TOKEN` → credential marker

Examples of safe keys (no gate required):
- `ORCH_MAX_PARALLEL` → safe tuning knob
- `PER_TASK_GB` → safe resource limit
- `ENABLE_LOGGING` → safe feature flag
- `ORCH_AUTO_PULL` → safe automation control

## Validation Rules

### Rule 1: Cannot Clear Licensing/Registration (Dangerous Rollback)
```python
# Invalid: would revoke license status
validate_contract_change("LICENSE123", None, "ORCH_LICENSE_KEY")
# → (False, "Cannot clear ORCH_LICENSE_KEY: would revoke status")

# Valid: replacing one license with another (with owner approval)
validate_contract_change("LICENSE1", "LICENSE2", "ORCH_LICENSE_KEY")
# → (True, "")
```

### Rule 2: Transmission Enable Requires Explicit Approval
```python
# Invalid: enabling from unset state without explicit acknowledgment
validate_contract_change(None, True, "TRANSMISSION_ENABLED")
# → (False, "TRANSMISSION_ENABLED transition from unset to enabled requires explicit approval")

# Valid: if transmission was already enabled
validate_contract_change(True, False, "TRANSMISSION_ENABLED")
# → (True, "")
```

### Rule 3: Owner Changes Require Audit Trail
```python
# Invalid: clearing owner without explanation
validate_contract_change("owner1", None, "OWNER_ID")
# → (False, "Cannot clear owner on OWNER_ID: audit trail required")

# Valid: transferring ownership (with owner approval)
validate_contract_change("owner1", "owner2", "OWNER_ID")
# → (True, "")
```

## Integration with fleet_control.py

The validation functions integrate into `fleet_config` updates:

```python
from contract_validator import legal_gate_required, validate_contract_change

# When pushing a fleet config update:
changes = {
    "ORCH_MAX_PARALLEL": 20,
    "ORCH_LICENSE_KEY": "NEW_LICENSE"
}

# Step 1: Check if legal gate is required
if legal_gate_required(changes):
    # Step 2: Validate each change
    for key, new_val in changes.items():
        old_val = current_config.get(key)
        is_valid, reason = validate_contract_change(old_val, new_val, key)
        if not is_valid:
            log_approval_required(key, reason)
            block_update(reason)
            return

# If all checks pass and owner has approved:
apply_fleet_config_update(changes)
```

## Error Handling

All functions are fail-soft: they never raise exceptions on bad input.

```python
# These all return sensible defaults instead of raising:
detect_legal_trigger(None)  # → False
detect_legal_trigger(123)   # → False
detect_legal_trigger("")    # → False

validate_contract_change("old", "new", None)  # → (True, "")
legal_gate_required(None)    # → False
legal_gate_required([])      # → False
legal_gate_required({"bad": dict})  # → False (or processes safely)
```

## Approval Workflow

1. **Operator** pushes config changes to fleet
2. **Validator** runs `legal_gate_required(changes)`
3. **If gate triggered**:
   - Changes are staged (not applied)
   - Owner is notified for review
   - Change details are logged
   - Each change is validated with `validate_contract_change`
4. **Owner reviews** and approves/rejects
5. **If approved**: Changes are applied via `fleet_control.apply_config()`
6. **If rejected**: Changes are discarded, reason logged

## Testing

The validation system includes 58 comprehensive tests:

- **16 tests** for `detect_legal_trigger` covering all trigger types, credential markers, case insensitivity, and error handling
- **10 tests** for `validate_contract_change` covering dangerous transitions, valid modifications, and error handling
- **11 tests** for `legal_gate_required` covering mixed config changes, empty dicts, and edge cases
- **10 tests** for real-world integration scenarios
- **8 tests** for edge cases and boundary conditions
- **3 tests** for case-insensitive behavior

Run tests:
```bash
python3 -m pytest runner/tests/test_contract_validator.py -v
```

## Configuration Examples

### Safe Fleet Config Update (No Gate)
```python
changes = {
    "ORCH_MAX_PARALLEL": 15,
    "ORCH_AUTO_PULL": True,
    "PER_TASK_GB": 1.2,
}
legal_gate_required(changes)  # → False (all keys are safe)
```

### License Update (Gate Required)
```python
changes = {
    "ORCH_LICENSE_KEY": "NEW_LICENSE"
}
legal_gate_required(changes)  # → True (license key triggers gate)
# Owner must approve
```

### Registration Update (Gate Required)
```python
changes = {
    "REGISTRATION_ID": "CUST_12345"
}
legal_gate_required(changes)  # → True (registration triggers gate)
# Owner must approve
```

### Mixed Safe & Legal (Gate Required)
```python
changes = {
    "ORCH_MAX_PARALLEL": 20,  # Safe
    "ORCH_LICENSE_KEY": "LICENSE123",  # Legal trigger
    "ENABLE_LOGGING": True,  # Safe
}
legal_gate_required(changes)  # → True (has legal triggers)
# Gate is required even though most keys are safe
```

### Dangerous License Clear (Gate + Invalid)
```python
changes = {
    "ORCH_LICENSE_KEY": None  # Clearing license
}
legal_gate_required(changes)  # → True
is_valid, reason = validate_contract_change("LICENSE123", None, "ORCH_LICENSE_KEY")
# is_valid → False
# reason → "Cannot clear ORCH_LICENSE_KEY: would revoke status"
# Change is blocked, owner is informed of the dangerous operation
```

## Fail-Soft Design

All validation functions are designed to never crash:

```python
# Graceful handling of unusual inputs
detect_legal_trigger(None)  # → False (not a trigger)
validate_contract_change({}, [], "key")  # → (True, "") (internal error → allow)
legal_gate_required(object())  # → False (not a dict → no gate)
```

This is intentional: a validation bug should never prevent legitimate config updates. Instead, uncertain cases fall through to the approval process where the owner makes the final decision.

## Owner-Only Approval

When legal gate is triggered, approval must come from the fleet owner (configured via `config_approval.py`). The approval process:

1. Records the requested changes
2. Logs all trigger reasons (which keys and why)
3. Notifies owner with full change details
4. Waits for explicit owner approval via web UI or API
5. On approval: applies changes with audit trail
6. On rejection: logs reason and discards changes

## Rollback & Audit

All legal gate approvals are logged with:
- Timestamp
- Owner who approved
- Changes approved
- Validation results
- Reason for approval (if provided)

Rollback of legal gate changes requires the same approval process.

## Future Extensions

This system can be extended to handle:

1. **Time-based gates**: License expiration checks
2. **Integration gates**: Registration validation via external API
3. **Custody verification**: Verify new owner is authorized
4. **Transmission safety**: Check encryption/privacy settings before enabling data transfer
5. **Advice constraints**: Limit who can modify advisory settings

See `fleet_control.py` for integration points.
