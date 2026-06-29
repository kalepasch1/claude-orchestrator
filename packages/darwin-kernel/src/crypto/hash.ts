/**
 * Canonical hashing — the content-addressing foundation for the whole kernel.
 *
 * Determinism rule: object keys are sorted recursively before serialization so
 * that two semantically-identical payloads always produce the same digest,
 * regardless of key order. This is what makes proofs, receipts, and passports
 * verifiable off-platform by a third party who never saw the original object.
 */
import { createHash } from 'node:crypto';

/** Stable, key-sorted JSON. Arrays keep order; objects are sorted by key. */
export function canonicalize(value: unknown): string {
  return JSON.stringify(sortDeep(value));
}

function sortDeep(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortDeep);
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(value as Record<string, unknown>).sort()) {
      out[key] = sortDeep((value as Record<string, unknown>)[key]);
    }
    return out;
  }
  return value;
}

/** SHA-256 hex digest of the canonical form of `value`. */
export function sha256Canonical(value: unknown): string {
  return createHash('sha256').update(canonicalize(value)).digest('hex');
}

/** SHA-256 hex digest of a raw string/buffer. */
export function sha256(input: string | Uint8Array): string {
  return createHash('sha256').update(input).digest('hex');
}

/** A short, collision-resistant content id with a typed prefix, e.g. `vp_3f9a…`. */
export function contentId(prefix: string, value: unknown): string {
  return `${prefix}_${sha256Canonical(value).slice(0, 40)}`;
}
