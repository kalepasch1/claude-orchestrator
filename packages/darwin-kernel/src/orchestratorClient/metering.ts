/**
 * Capability metering (improvement #2) — turns the capability registry into a
 * metered internal API economy. Every cross-product invocation emits a signed
 * usage record: who called, whose engine ran, cost, latency. That single record
 * powers (a) internal transfer pricing (Pareto's engine serving Tomorrow's bank
 * vertical is a priced internal API) and (b) external billing (the embed kit /
 * RaaS as a metered developer platform).
 *
 * The usage record reuses the governance signing anchor so usage is tamper-evident
 * and verifiable off-platform — the same receipt is both audit AND invoice line.
 */
import { sha256Canonical, contentId } from '../crypto/hash.ts';
import { signDigest, verifyDigest, type Signature } from '../crypto/signing.ts';
import type { ProductId } from '../types.ts';
import type { CapabilityRegistry } from './capabilityRegistry.ts';

export interface UsageRecord {
  id: string;
  capabilityId: string;
  /** product that invoked */
  caller: ProductId;
  /** product that owns the capability (the payee) */
  owner: ProductId;
  /** measured wall-clock ms */
  latencyMs: number;
  /** billable units (e.g. tokens, calls, compute) */
  units: number;
  /** priced amount in USD-cents (transfer or external) */
  amountCents: number;
  at: string;
  digest: string;
  signature: Signature;
}

export interface PriceBook {
  /** USD-cents per unit, by capability id; fallback used when absent */
  perUnitCents: Record<string, number>;
  fallbackPerUnitCents: number;
}

export const DEFAULT_PRICEBOOK: PriceBook = { perUnitCents: {}, fallbackPerUnitCents: 1 };

export function priceUsage(capabilityId: string, units: number, book: PriceBook = DEFAULT_PRICEBOOK): number {
  const per = book.perUnitCents[capabilityId] ?? book.fallbackPerUnitCents;
  return Math.round(per * units);
}

export function buildUsageRecord(params: {
  capabilityId: string;
  caller: ProductId;
  owner: ProductId;
  latencyMs: number;
  units: number;
  book?: PriceBook;
  at?: string;
}): UsageRecord {
  const amountCents = priceUsage(params.capabilityId, params.units, params.book);
  const body = {
    capabilityId: params.capabilityId,
    caller: params.caller,
    owner: params.owner,
    latencyMs: params.latencyMs,
    units: params.units,
    amountCents,
    at: params.at ?? new Date().toISOString(),
  };
  const digest = sha256Canonical(body);
  return { id: contentId('use', body), ...body, digest, signature: signDigest(digest) };
}

export function verifyUsageRecord(rec: UsageRecord): boolean {
  const { id: _id, digest, signature, ...body } = rec;
  if (sha256Canonical(body) !== digest) return false;
  return verifyDigest(digest, signature);
}

/** Roll usage into a per-(owner←caller) settlement ledger (transfer pricing). */
export interface Settlement {
  owner: ProductId;
  caller: ProductId;
  calls: number;
  amountCents: number;
}
export function settleUsage(records: UsageRecord[]): Settlement[] {
  const m = new Map<string, Settlement>();
  for (const r of records) {
    if (!verifyUsageRecord(r)) continue; // tampered records never settle
    const key = `${r.owner}<=${r.caller}`;
    const s = m.get(key) ?? { owner: r.owner, caller: r.caller, calls: 0, amountCents: 0 };
    s.calls += 1;
    s.amountCents += r.amountCents;
    m.set(key, s);
  }
  return [...m.values()].sort((a, b) => b.amountCents - a.amountCents);
}

/**
 * Wrap a registry so every `instantiate` is timed, priced, and metered.
 * Returns the capability output plus the signed usage record to persist.
 */
export class MeteredRegistry {
  private readonly registry: CapabilityRegistry;
  private readonly caller: ProductId;
  private readonly book: PriceBook;
  private readonly onUsage?: (rec: UsageRecord) => void;
  constructor(opts: {
    registry: CapabilityRegistry;
    caller: ProductId;
    book?: PriceBook;
    onUsage?: (rec: UsageRecord) => void;
  }) {
    this.registry = opts.registry;
    this.caller = opts.caller;
    this.book = opts.book ?? DEFAULT_PRICEBOOK;
    this.onUsage = opts.onUsage;
  }

  async invoke(params: {
    capabilityId: string;
    owner: ProductId;
    input: Record<string, unknown>;
    /** unit count to bill (default 1 call) */
    units?: number;
    now?: () => number;
  }): Promise<{ output: unknown; usage: UsageRecord }> {
    const clock = params.now ?? (() => Date.now());
    const start = clock();
    const output = await this.registry.instantiate(params.capabilityId, params.input);
    const latencyMs = Math.max(0, clock() - start);
    const usage = buildUsageRecord({
      capabilityId: params.capabilityId,
      caller: this.caller,
      owner: params.owner,
      latencyMs,
      units: params.units ?? 1,
      book: this.book,
    });
    this.onUsage?.(usage);
    return { output, usage };
  }
}
