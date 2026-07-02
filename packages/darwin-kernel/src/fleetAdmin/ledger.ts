/**
 * The escalation-learning flywheel — the real 20–200×. Every human decision in the
 * single queue trains the autonomy of the WHOLE fleet, not one app. When an
 * (action-type) has been approved-without-edit enough times in a row, the ledger
 * proposes promoting it toward `auto` — but the promotion itself is a material
 * change, so a human still confirms it (fail-safe). Generalized from Smarter's
 * per-workspace streak promotion, lifted to the portfolio level.
 *
 * Pure + serializable so it can live in Supabase (`fleet_autonomy_ledger`) and be
 * hydrated in-memory exactly like Smarter's kv collections.
 */
import type { AdminDomain, AutonomyTier } from './types.ts';

export interface LedgerEntry {
  /** the action verb this entry tracks, e.g. 'billing:issue_refund' */
  actionType: string;
  domain: AdminDomain;
  /** consecutive human approvals with NO edit */
  streak: number;
  /** total decisions seen (denominator for the autonomy rate) */
  total: number;
  /** approvals-without-edit (numerator) */
  cleanApprovals: number;
  edits: number;
  rejections: number;
  /** set when a human confirms promotion to a higher tier */
  promotedTier?: AutonomyTier;
  promotedAt?: string;
  updatedAt: string;
}

export interface PromotionCandidate {
  actionType: string;
  domain: AdminDomain;
  streak: number;
  agreementRate: number;
  /** the tier we recommend promoting TO (never above the domain ceiling) */
  recommendTier: AutonomyTier;
}

export const AUTO_PROMOTE_STREAK = 20;
export const MIN_AGREEMENT_RATE = 0.95;

export class FleetAutonomyLedger {
  private entries = new Map<string, LedgerEntry>();

  constructor(seed: LedgerEntry[] = []) {
    for (const e of seed) this.entries.set(key(e.domain, e.actionType), e);
  }

  /** Record the outcome of a human decision from the queue. Drives the streak. */
  record(params: {
    domain: AdminDomain;
    actionType: string;
    decision: 'approve' | 'modify' | 'reject';
    at?: string;
  }): LedgerEntry {
    const k = key(params.domain, params.actionType);
    const now = params.at ?? new Date().toISOString();
    const e =
      this.entries.get(k) ??
      {
        actionType: params.actionType,
        domain: params.domain,
        streak: 0,
        total: 0,
        cleanApprovals: 0,
        edits: 0,
        rejections: 0,
        updatedAt: now,
      };
    e.total += 1;
    if (params.decision === 'approve') {
      e.streak += 1;
      e.cleanApprovals += 1;
    } else {
      e.streak = 0; // any edit or rejection resets the trust streak
      if (params.decision === 'modify') e.edits += 1;
      else e.rejections += 1;
    }
    e.updatedAt = now;
    this.entries.set(k, e);
    return e;
  }

  agreementRate(domain: AdminDomain, actionType: string): number {
    const e = this.entries.get(key(domain, actionType));
    if (!e || e.total === 0) return 0;
    return e.cleanApprovals / e.total;
  }

  /**
   * Action-types that have earned a promotion offer: long clean streak + high
   * agreement, not already promoted. The plane surfaces these as a special
   * "stop asking → let me auto-handle these" card (still human-confirmed).
   */
  promotionCandidates(ceilingOf: (d: AdminDomain) => AutonomyTier): PromotionCandidate[] {
    const out: PromotionCandidate[] = [];
    for (const e of this.entries.values()) {
      if (e.promotedAt) continue;
      if (e.streak < AUTO_PROMOTE_STREAK) continue;
      if (this.agreementRate(e.domain, e.actionType) < MIN_AGREEMENT_RATE) continue;
      const ceiling = ceilingOf(e.domain);
      out.push({
        actionType: e.actionType,
        domain: e.domain,
        streak: e.streak,
        agreementRate: this.agreementRate(e.domain, e.actionType),
        recommendTier: ceiling === 'auto' ? 'auto' : 'co_pilot',
      });
    }
    return out.sort((a, b) => b.streak - a.streak);
  }

  /** A human confirms a promotion (the material step). */
  confirmPromotion(domain: AdminDomain, actionType: string, tier: AutonomyTier, at?: string): boolean {
    const e = this.entries.get(key(domain, actionType));
    if (!e) return false;
    e.promotedTier = tier;
    e.promotedAt = at ?? new Date().toISOString();
    this.entries.set(key(domain, actionType), e);
    return true;
  }

  /** Fleet-wide "% autonomous" north-star, weighted by volume. */
  autonomyRate(): { rate: number; totalDecisions: number } {
    let clean = 0;
    let total = 0;
    for (const e of this.entries.values()) {
      clean += e.cleanApprovals;
      total += e.total;
    }
    return { rate: total ? clean / total : 0, totalDecisions: total };
  }

  snapshot(): LedgerEntry[] {
    return [...this.entries.values()];
  }
}

function key(domain: AdminDomain, actionType: string): string {
  return `${domain}::${actionType}`;
}
