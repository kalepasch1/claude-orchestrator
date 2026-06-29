/**
 * @darwin/kernel — shared cross-product kernel.
 *
 * The load-bearing layer beneath tomorrow, smarter, apparently, pareto, galop,
 * hisanta and the orchestrator. Zero runtime dependencies (Node/Web crypto only).
 *
 *   governance/   — constitution eval (fail-closed) + signed hash-chained receipts + materiality
 *   passport/     — portable, offline-verifiable risk/identity credential (KYC once, reuse everywhere)
 *   identity/     — consent-scoped cross-product identity graph + cross-sell routing
 *   federated/    — k-anonymity + ε-DP so products learn from each other without moving raw data
 *   orchestrator/ — capability registry + task queue client (publish a process once, run it anywhere)
 */
export * from './types.ts';
export * as crypto from './crypto/hash.ts';
export { getPublicKeyPem, signDigest, verifyDigest } from './crypto/signing.ts';
export type { Signature } from './crypto/signing.ts';

export * from './governance/index.ts';
export * from './passport/index.ts';
export * from './attestation/index.ts';
export * from './identity/index.ts';
export * from './federated/index.ts';
export * from './dataCoop/index.ts';
export * from './orchestratorClient/index.ts';
export * from './flywheel.ts';
export * as products from './products/index.ts';
export * as cade from './cade/index.ts';
