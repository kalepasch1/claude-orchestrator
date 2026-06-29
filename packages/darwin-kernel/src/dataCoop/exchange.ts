/**
 * Rewards-currency exchange (new improvement #4) — makes the three previously-
 * isolated rewards economies (Apparently points / Hisanta sparks / Galop coins)
 * FUNGIBLE via a published rate table, so a data-coop "data dividend" earned in
 * one product is spendable across the portfolio. The shared currency is the
 * connective tissue that turns three retention loops into one.
 *
 * Pure. Rates are USD-cents per 1 unit of the currency.
 */
import type { RewardCurrency, RewardLedgerEntry } from './dataCoop.ts';

export type RateTable = Record<RewardCurrency, number>; // USD-cents per unit

export const DEFAULT_RATES: RateTable = {
  apparently_points: 1, // 1 point = 1 cent
  hisanta_sparks: 0.5, // 1 spark = half a cent
  galop_coins: 0.25, // 1 coin = quarter cent
};

export function toUsdCents(amount: number, currency: RewardCurrency, rates: RateTable = DEFAULT_RATES): number {
  return amount * rates[currency];
}

/** Convert between currencies via their USD-cent anchors. */
export function convert(
  amount: number,
  from: RewardCurrency,
  to: RewardCurrency,
  rates: RateTable = DEFAULT_RATES,
): number {
  const usd = toUsdCents(amount, from, rates);
  return usd / rates[to];
}

export interface NormalizedBalance {
  /** total value of all entries in USD-cents */
  totalUsdCents: number;
  /** per-currency native totals */
  byCurrency: Partial<Record<RewardCurrency, number>>;
  /** the whole balance expressed in a single chosen currency */
  inCurrency: { currency: RewardCurrency; amount: number };
}

/** Roll a subject's reward ledger into one fungible balance. */
export function normalizeBalance(
  entries: RewardLedgerEntry[],
  displayCurrency: RewardCurrency = 'apparently_points',
  rates: RateTable = DEFAULT_RATES,
): NormalizedBalance {
  const byCurrency: Partial<Record<RewardCurrency, number>> = {};
  let totalUsdCents = 0;
  for (const e of entries) {
    byCurrency[e.currency] = (byCurrency[e.currency] ?? 0) + e.amount;
    totalUsdCents += toUsdCents(e.amount, e.currency, rates);
  }
  return {
    totalUsdCents,
    byCurrency,
    inCurrency: { currency: displayCurrency, amount: totalUsdCents / rates[displayCurrency] },
  };
}
