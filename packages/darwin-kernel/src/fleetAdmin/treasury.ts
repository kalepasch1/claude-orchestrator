/**
 * Portfolio treasury — admin ops as a live P&L. Every routed decision rolls into a
 * financial statement: approver time saved by autonomy, incident loss avoided by
 * escalations that caught a bad action, and error cost from autos that shouldn't have run.
 * Admin stops being a cost center you tolerate and becomes a number you can show an
 * investor or acquirer. Pure + zero-dep.
 */
import type { AdminDomain } from './types.ts';

export interface SettledDecision {
  domain: AdminDomain;
  tier: 'auto' | 'co_pilot' | 'human';
  decision: 'allow' | 'escalate' | 'deny';
  /** human outcome for escalated decisions, if resolved */
  outcome?: 'approve' | 'modify' | 'reject';
  amountUsd?: number;
}

export interface TreasuryConfig {
  perDecisionMinutes: number;
  hourlyValueUsd: number;
  /** cost of a wrong auto-run = base + share of amount */
  errorBaseUsd: number;
  errorAmountShare: number;
}
export const DEFAULT_TREASURY_CONFIG: TreasuryConfig = { perDecisionMinutes: 3, hourlyValueUsd: 200, errorBaseUsd: 40, errorAmountShare: 1.0 };

export interface TreasuryLine {
  label: string;
  usd: number; // positive = value created, negative = cost incurred
  count: number;
}

export interface TreasuryStatement {
  savingsUsd: number;
  costsUsd: number;
  netUsd: number;
  byDomain: { domain: AdminDomain; netUsd: number; autonomous: number }[];
  lines: TreasuryLine[];
}

export function buildTreasury(decisions: SettledDecision[], cfg: TreasuryConfig = DEFAULT_TREASURY_CONFIG): TreasuryStatement {
  const minuteCost = (cfg.perDecisionMinutes / 60) * cfg.hourlyValueUsd;
  let approverTimeSaved = 0;
  let incidentLossAvoided = 0;
  let approverTimeSpent = 0;
  let errorCost = 0;
  let autoCount = 0;
  let rejectCount = 0;
  let escalatedCount = 0;

  const byDomain = new Map<AdminDomain, { netUsd: number; autonomous: number }>();
  const bump = (d: AdminDomain, net: number, auto: number) => {
    const e = byDomain.get(d) ?? { netUsd: 0, autonomous: 0 };
    e.netUsd += net; e.autonomous += auto; byDomain.set(d, e);
  };

  for (const x of decisions) {
    if (x.decision === 'allow' && x.tier === 'auto') {
      autoCount++;
      approverTimeSaved += minuteCost; // a decision that needed no human
      bump(x.domain, minuteCost, 1);
    } else if (x.decision === 'escalate') {
      escalatedCount++;
      approverTimeSpent += minuteCost;
      let net = -minuteCost;
      if (x.outcome === 'reject') {
        rejectCount++;
        const avoided = cfg.errorBaseUsd + cfg.errorAmountShare * (x.amountUsd ?? 0); // caught a bad one
        incidentLossAvoided += avoided;
        net += avoided;
      }
      bump(x.domain, net, 0);
    }
    // deny costs nothing and needs no human.
  }

  const savingsUsd = Math.round(approverTimeSaved + incidentLossAvoided);
  const costsUsd = Math.round(approverTimeSpent + errorCost);
  const lines: TreasuryLine[] = [
    { label: 'Approver time saved by autonomy', usd: Math.round(approverTimeSaved), count: autoCount },
    { label: 'Incident loss avoided (escalations that caught a bad action)', usd: Math.round(incidentLossAvoided), count: rejectCount },
    { label: 'Approver time spent on escalations', usd: -Math.round(approverTimeSpent), count: escalatedCount },
    { label: 'Auto-run error cost', usd: -Math.round(errorCost), count: 0 },
  ];

  return {
    savingsUsd,
    costsUsd,
    netUsd: savingsUsd - costsUsd,
    byDomain: [...byDomain.entries()].map(([domain, v]) => ({ domain, netUsd: Math.round(v.netUsd), autonomous: v.autonomous })).sort((a, b) => b.netUsd - a.netUsd),
    lines,
  };
}
