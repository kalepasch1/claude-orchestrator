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

## Built-in provider gateway

When `ORCHESTRATOR_WEB_URL` or `BUSINESS_AGENT_ADAPTER_URL` points at the orchestrator web application, the runner uses the built-in signed routes at `/v1/business-saga/execute` and `/v1/business-saga/reconcile`.

The Connections UI supports encrypted, organization-scoped credential bundles for Stripe, DocuSign, Gusto, Plaid Transfer, and Avalara. Sandbox is always the default. A workflow must explicitly select production and must still satisfy its step approval and exact organizational-authority scope.

- Stripe supports bounded payouts, refunds, invoice preparation, idempotency keys, signed events, and status reconciliation.
- DocuSign supports version-pinned envelope issuance and HMAC-verified completion evidence.
- Gusto supports employee records, payroll preparation, and payroll submission acknowledgements.
- Plaid performs transfer authorization before creation and waits for settlement or funds-available finality.
- Avalara creates uncommitted tax transactions and evidence; statutory filing remains fail-closed until a qualified filing provider or professional adapter is configured.
- OpenAI Responses can facilitate non-binding internal preparation with strict structured output. It cannot authorize or represent an external effect.

Provider-specific missing fields create a minimum human-input request in the Virtual Executive Team UI. Answering it updates only the waiting step and resumes the same idempotent saga.

## Provider intelligence mesh

The built-in gateway learns field-path mappings only from verified executions. Values are never stored in the mapping model, and a mapping cannot change an execution until it has at least three successful observations and 90% confidence. A stable randomized holdout compares this optimization layer against the existing safe baseline; it never withholds the underlying business operation.

Every request runs through a non-mutating provider digital twin before credentials are leased. Production requests with a blocking or review verdict do not reach the provider. Treatment routes rank eligible accounts by observed fees, settlement latency, failure rate, jurisdiction, and risk. Webhook, polling, and read-after-write evidence normalize into `provider-finality/v1` records before causal metrics are updated.

Signed adapters are compiled from OpenAPI 3 specifications only for pinned provider sandbox origins. They remain inactive until an HSM signature and a live, all-2xx sandbox conformance run both succeed.

For short-lived credentials, configure:

```text
CONNECTOR_CREDENTIAL_BROKER_URL=https://broker.example.com
CONNECTOR_CREDENTIAL_BROKER_TOKEN=deployment-secret
CONNECTOR_CREDENTIAL_BROKER_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\n..."
CONNECTOR_HSM_SIGNER_URL=https://signer.example.com
CONNECTOR_HSM_SIGNER_TOKEN=deployment-secret
```

The broker response must bind the credential digest, reference, lease ID, expiry, nonce, and key ID under an Ed25519 signature. Leases over 15 minutes, expired leases, nonce mismatches, digest mismatches, and invalid signatures fail closed. Only the credential reference and lease evidence are persisted.
