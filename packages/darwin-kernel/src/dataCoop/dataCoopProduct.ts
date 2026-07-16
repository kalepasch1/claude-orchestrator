/**
 * Data-coop product module — surfaces the kernel `runCoopRound` engine as an
 * opt-in product where users earn a normalized "data dividend" for consented,
 * k-anon / ε-DP-gated sharing, with suppression below the k-floor.
 *
 * Consent + privacy gates fail-closed: no consent → rejected; cohort below
 * k-floor → suppressed, no rewards paid, no data leaves the boundary.
 */
import type { ProductId } from '../types.ts';
import type { ClaimKind } from '../passport/passport.ts';
import type { ConsentGrant } from '../identity/graph.ts';
import type { PrivacyConfig } from '../federated/privacy.ts';
import {
  runCoopRound,
  type ContributionIntent,
  type RewardSchedule,
  type RewardLedgerEntry,
  type CoopRoundResult,
} from './dataCoop.ts';
import { toUsdCents, type RateTable, DEFAULT_RATES } from './exchange.ts';

/** A reward-ledger writer accumulates entries across rounds. */
export class RewardLedgerWriter {
  private entries: RewardLedgerEntry[] = [];

  append(entry: RewardLedgerEntry): void {
    this.entries.push(entry);
  }

  appendAll(entries: RewardLedgerEntry[]): void {
    this.entries.push(...entries);
  }

  /** All entries written so far. */
  all(): RewardLedgerEntry[] {
    return [...this.entries];
  }

  /** Entries for a specific subject. */
  forSubject(subject: string): RewardLedgerEntry[] {
    return this.entries.filter((e) => e.subject === subject);
  }

  /** Total normalized value (USD-cents) across all entries. */
  totalNormalizedCents(rates: RateTable = DEFAULT_RATES): number {
    return this.entries.reduce((sum, e) => sum + toUsdCents(e.amount, e.currency, rates), 0);
  }
}

/** Configuration for a data-coop product pool. */
export interface DataCoopPoolConfig {
  /** Source product contributing data. */
  from: ProductId;
  /** Target product consuming the aggregate. */
  to: ProductId;
  /** Consent scope required. */
  scope: ClaimKind;
  /** Reward schedule for accepted contributors. */
  schedule: RewardSchedule;
  /** Privacy config (k-floor, epsilon). Defaults to kernel defaults. */
  privacy?: PrivacyConfig;
  /** Max contribution sensitivity for DP mechanism. */
  sensitivity?: number;
}

/** Result of running a data-coop product round. */
export interface DataCoopProductResult {
  round: CoopRoundResult;
  /** Normalized total dividend paid (USD-cents). */
  totalDividendCents: number;
  /** Whether data was suppressed due to k-floor. */
  suppressed: boolean;
}

/**
 * Run one data-coop product round: consent-gate contributions, apply k-anon +
 * ε-DP, pay data dividends to the reward ledger. Fail-closed.
 */
export function runDataCoopProductRound(params: {
  pool: DataCoopPoolConfig;
  contributions: { subject: string; value: number }[];
  consent: ConsentGrant[];
  ledger: RewardLedgerWriter;
  rates?: RateTable;
  rng?: () => number;
  asOf?: Date;
}): DataCoopProductResult {
  const rates = params.rates ?? DEFAULT_RATES;

  const intents: ContributionIntent[] = params.contributions.map((c) => ({
    subject: c.subject,
    from: params.pool.from,
    to: params.pool.to,
    scope: params.pool.scope,
    value: c.value,
  }));

  const round = runCoopRound({
    contributions: intents,
    consent: params.consent,
    schedule: params.pool.schedule,
    privacy: params.pool.privacy,
    sensitivity: params.pool.sensitivity,
    rng: params.rng,
    asOf: params.asOf,
  });

  // Write rewards to ledger
  params.ledger.appendAll(round.rewards);

  const totalDividendCents = round.rewards.reduce(
    (sum, r) => sum + toUsdCents(r.amount, r.currency, rates),
    0,
  );

  return { round, totalDividendCents, suppressed: round.suppressed };
}
