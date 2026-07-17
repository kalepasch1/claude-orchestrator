# Canary: Missing-Branch Recovery Verification

## Purpose
This canary validates that the coder routing system can reconstruct
missing-branch work from reuse-first context, serving as an acceptance
test for the recovery pipeline.

## Verification Criteria
- Recovery pipeline detects missing branches within one polling cycle
- Patch reconstruction uses cached templates when available
- Reconstructed patches preserve the original acceptance intent
- No changes to secrets, dependencies, or product behavior

## Status
Canary deployed as part of routing validation batch.
