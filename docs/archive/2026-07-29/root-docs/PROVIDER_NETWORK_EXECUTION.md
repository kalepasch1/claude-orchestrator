# Provider network execution mesh

The mesh extends the provider execution fabric without weakening its approval,
authority, idempotency, or finality gates.

## Production contract

For an external-effect step in `production`, execution now requires:

1. the existing approval and active authority credential;
2. the existing local saga invariants plus a signed TLC/Apalache receipt for the
   generated TLA+ model;
3. a semantic mutation intent;
4. a fresh certificate made from at least three valid Ed25519 votes from distinct
   institutions in at least two regions;
5. the existing global mutation claim, provider adapter, and normalized finality
   event.

Certificates are cached by semantic obligation for no more than five minutes.
Formal receipts are cached by model digest. Missing production verifier or
consensus configuration fails closed. Sandbox execution can persist generated
models without pretending that they were externally verified.

## Private and threshold computation

The database stores public-key digests, HSM measurements, signatures, ciphertext
digests, and signed verifier receipts. It never stores secret key shares or private
optimization plaintext. Threshold ceremonies require distinct custodians in
geo-separated regions. Private optimization accepts only supported FHE scheme
receipts from configured verifier keys.

## Business controls

- The obligation graph normalizes legal obligations, financial events, and
  governed documents into semantic fingerprints. Duplicate clusters are marked
  `block_duplicate_execution`.
- Liquidity netting validates zero-sum positions and creates an
  `approval_required` round; it cannot settle funds.
- Treasury optimization receives deterministic randomized holdout assignments so
  outcomes can measure causal value rather than task completion.
- Provider synthesis requires OpenAPI, webhook, and sandbox-trace evidence before
  it is proof-ready. Chaos experiments are sandbox-only, reversible, and have a
  blast radius of one.
- Authority rule packages require a configured authority key, signature, effective
  date, machine-readable invariants, and an active organization-scoped source.

## Operator surface

`/business/provider-sovereignty` shows independent proof counts, duplicate
liabilities, netting savings, private proof posture, compiler conformance, chaos
passes, and the transparency head. It exposes only analysis and proposal actions;
provider mutations remain on the established approval and finality rails.
