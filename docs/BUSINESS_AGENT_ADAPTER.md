# Business agent adapter contract

Virtual executive agents can prepare internal records without a third-party adapter. Any external effect—such as creating a worker, submitting payroll, moving money, filing a return, issuing a signature request, or changing an identity provider—remains disabled until all of these controls are satisfied:

1. The saga step has an approved approval record.
2. The agent has an active organizational authority credential containing the exact required scope.
3. Prior saga steps are complete.
4. A provider adapter URL and `FLEET_SHARED_SECRET` are configured.
5. The adapter returns a durable execution receipt.

Configure a shared adapter with `BUSINESS_AGENT_ADAPTER_URL`, or a provider-specific override such as `BUSINESS_AGENT_PAYROLL_URL`. The runner appends `/v1/business-saga/execute`.

## Request

```json
{
  "version": "business-saga/v1",
  "step_id": "uuid",
  "saga_id": "uuid",
  "agent": "payroll_controller",
  "operation": "submit_payroll",
  "provider": "payroll",
  "scopes": ["payroll.write"],
  "input": {},
  "idempotency_key": "stable-key",
  "authority_scope": "payroll.submit",
  "approval_id": "uuid"
}
```

Headers include `x-fleet-secret`, `content-type: application/json`, and the same stable value in `idempotency-key`.

The adapter must authenticate the fleet secret using constant-time comparison, reject unknown operations and excess scopes, verify the provider account belongs to the saga organization, and use the idempotency key as a durable uniqueness constraint. Credentials belong in the adapter's secret store; they must never be returned to the orchestrator.

## Response

Success requires a durable receipt:

```json
{
  "ok": true,
  "external_ref": "provider-object-id",
  "receipt_digest": "sha256-of-canonical-provider-receipt",
  "provider_status": "accepted"
}
```

An error response uses `ok: false`, `retryable: true|false`, and a non-sensitive `error`. A success without `receipt_digest` or `external_ref` is rejected. The worker retries transient errors at most five times and then blocks the saga for review.

## Conformance requirements

- Sandbox and production credentials must be physically separate.
- Every mutating operation must be exactly-once under `idempotency-key`.
- The receipt must be retrievable later for reconciliation.
- Provider webhooks must be signature-verified before updating finality.
- Logs must contain digests and provider references, not payroll, tax, banking, employee-health, or contract payloads.
- Compensation operations require their own approval and authority check; an adapter may not infer permission from the original action.

No adapter configuration means no external effect. This is intentional and is covered by automated tests.
