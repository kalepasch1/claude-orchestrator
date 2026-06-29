/**
 * Attestation feeds (new improvement #3) — turn each product's proprietary
 * judgment (Tomorrow trigger ratings, Smarter clause-at-market calls, Apparently
 * grounded opinions) into a licensable, signed, offline-verifiable data feed.
 *
 * A feed is an append-only, named stream of attestations of a given kind. A
 * consumer reads it, verifies each entry offline, and (optionally) every read is
 * metered — so an attestation feed is a productized API on the same rails as the
 * capability registry.
 *
 * Transport is injected (Supabase/HTTP/in-memory) to stay portable.
 */
import type { ProductId } from '../types.ts';
import { verifyAttestation, type Attestation } from './attestation.ts';

export interface FeedManifest {
  /** stable feed id, e.g. 'tomorrow:trigger_rating' */
  id: string;
  owner: ProductId;
  kind: string;
  title: string;
  description: string;
  /** USD-cents per read (0 = free) */
  pricePerReadCents: number;
}

export interface FeedTransport {
  append(feedId: string, att: Attestation): Promise<void>;
  /** newest-first reads, optionally filtered by `about` */
  read(feedId: string, opts?: { about?: string; limit?: number }): Promise<Attestation[]>;
}

export interface ReadResult {
  /** only entries that pass offline verification are returned */
  attestations: Attestation[];
  /** entries that failed verification (count) — surfaced, never silently dropped */
  rejected: number;
  /** billable reads (for metering) = number of verified entries returned */
  billableReads: number;
  priceCents: number;
}

export class AttestationFeed {
  private readonly transport: FeedTransport;
  private readonly manifest: FeedManifest;
  private readonly onRead?: (r: ReadResult) => void;
  constructor(opts: { transport: FeedTransport; manifest: FeedManifest; onRead?: (r: ReadResult) => void }) {
    this.transport = opts.transport;
    this.manifest = opts.manifest;
    this.onRead = opts.onRead;
  }

  getManifest(): FeedManifest {
    return this.manifest;
  }

  /** Publisher side: only the feed owner's attestations of the feed kind are accepted. */
  async publish(att: Attestation): Promise<{ ok: boolean; reason: string }> {
    if (att.issuer !== this.manifest.owner) return { ok: false, reason: 'issuer_not_owner' };
    if (att.kind !== this.manifest.kind) return { ok: false, reason: 'kind_mismatch' };
    if (!verifyAttestation(att).valid) return { ok: false, reason: 'attestation_invalid' };
    await this.transport.append(this.manifest.id, att);
    return { ok: true, reason: 'ok' };
  }

  /** Consumer side: verified, metered read. */
  async read(opts: { about?: string; limit?: number; asOf?: Date } = {}): Promise<ReadResult> {
    const raw = await this.transport.read(this.manifest.id, { about: opts.about, limit: opts.limit });
    const attestations: Attestation[] = [];
    let rejected = 0;
    for (const a of raw) {
      if (verifyAttestation(a, opts.asOf).valid) attestations.push(a);
      else rejected += 1;
    }
    const result: ReadResult = {
      attestations,
      rejected,
      billableReads: attestations.length,
      priceCents: attestations.length * this.manifest.pricePerReadCents,
    };
    this.onRead?.(result);
    return result;
  }
}

/** In-memory transport for tests / single-process composition. */
export function memoryFeedTransport(): FeedTransport {
  const store = new Map<string, Attestation[]>();
  return {
    async append(feedId, att) {
      store.set(feedId, [att, ...(store.get(feedId) ?? [])]);
    },
    async read(feedId, opts) {
      let items = store.get(feedId) ?? [];
      if (opts?.about) items = items.filter((a) => a.about === opts.about);
      return opts?.limit ? items.slice(0, opts.limit) : items;
    },
  };
}
