/**
 * Governance marketplace — a two-sided market that turns governed autonomy into a NETWORK
 * good. Orgs publish battle-tested constitutions, DP-anonymized precedent packs, and intent
 * playbooks; others discover + install them, so a new company inherits a mature refund policy
 * or fraud-response plan on day one. Every listing is content-addressed + Ed25519-signed, so
 * an installer verifies provenance + integrity offline before trusting it. Pure + zero-dep;
 * transport is injected (registry / HTTP / in-memory).
 */
import { sha256Canonical } from '../crypto/hash.ts';
import { signDigest, verifyDigest, getPublicKeyPem, type Signature } from '../crypto/signing.ts';

export type ListingKind = 'constitution' | 'precedent_pack' | 'playbook';

export interface MarketListingBody {
  id: string; // content id over {kind,title,version,payload}
  kind: ListingKind;
  title: string;
  owner: string;
  version: string;
  tags: string[];
  /** opaque, kind-specific payload. precedent_pack payloads MUST be DP-aggregated. */
  payload: Record<string, unknown>;
  publicKeyPem: string;
  publishedAt: string;
}
export interface MarketListing extends MarketListingBody {
  digest: string;
  signature: Signature;
}

export interface ListingStats {
  installs: number;
  ratingSum: number;
  ratingCount: number;
}

/** Sign a listing so installers can verify provenance + integrity offline. */
export function signListing(body: Omit<MarketListingBody, 'publicKeyPem'>): MarketListing {
  const full: MarketListingBody = { ...body, publicKeyPem: getPublicKeyPem() };
  const digest = sha256Canonical(full);
  return { ...full, digest, signature: signDigest(digest) };
}

/** Stateless verification: digest intact AND signature valid against the embedded key. */
export function verifyListing(listing: MarketListing): boolean {
  const { digest, signature, ...body } = listing;
  if (sha256Canonical(body) !== digest) return false;
  return verifyDigest(digest, signature);
}

export interface MarketTransport {
  publish(listing: MarketListing): Promise<void>;
  search(query: string, kind?: ListingKind, tags?: string[]): Promise<MarketListing[]>;
  get(id: string): Promise<MarketListing | null>;
  recordInstall(id: string): Promise<void>;
  rate(id: string, stars: number): Promise<void>;
  stats(id: string): Promise<ListingStats | null>;
}

export class GovernanceMarketplace {
  private readonly transport: MarketTransport;
  constructor(transport: MarketTransport) {
    this.transport = transport;
  }

  publish(listing: MarketListing): Promise<void> {
    if (!verifyListing(listing)) return Promise.reject(new Error('invalid_listing_signature'));
    return this.transport.publish(listing);
  }
  discover(query: string, kind?: ListingKind, tags?: string[]): Promise<MarketListing[]> {
    return this.transport.search(query, kind, tags);
  }
  /** Install a listing: verify it first, then return its payload + record the install. */
  async install(id: string): Promise<{ listing: MarketListing; payload: Record<string, unknown> }> {
    const listing = await this.transport.get(id);
    if (!listing) throw new Error(`listing_not_found:${id}`);
    if (!verifyListing(listing)) throw new Error(`listing_failed_verification:${id}`);
    await this.transport.recordInstall(id);
    return { listing, payload: listing.payload };
  }
  rate(id: string, stars: number): Promise<void> {
    return this.transport.rate(id, Math.max(1, Math.min(5, stars)));
  }
}

/** In-memory transport for tests + single-process composition. */
export function memoryMarketTransport(): MarketTransport {
  const store = new Map<string, MarketListing>();
  const stats = new Map<string, ListingStats>();
  const st = (id: string) => stats.get(id) ?? stats.set(id, { installs: 0, ratingSum: 0, ratingCount: 0 }).get(id)!;
  return {
    async publish(l) { store.set(l.id, l); st(l.id); },
    async search(query, kind, tags) {
      const q = query.toLowerCase();
      return [...store.values()].filter(
        (l) => (!kind || l.kind === kind) &&
          (l.title.toLowerCase().includes(q) || l.tags.some((t) => t.includes(q)) || (tags ?? []).some((t) => l.tags.includes(t))),
      );
    },
    async get(id) { return store.get(id) ?? null; },
    async recordInstall(id) { st(id).installs += 1; },
    async rate(id, stars) { const s = st(id); s.ratingSum += stars; s.ratingCount += 1; },
    async stats(id) { return stats.get(id) ?? null; },
  };
}
