export * from './constitution.ts';
export * from './compiler.ts';
export * from './receipts.ts';
export * from './materiality.ts';
export * from './policyService.ts';

import type { AgentAction } from '../types.ts';
import {
  evaluateConstitution,
  type Constitution,
  type ConstitutionDecision,
} from './constitution.ts';
import { buildReceipt, type Receipt } from './receipts.ts';

/**
 * The one call every product makes before a bot acts: evaluate against the
 * constitution AND mint a signed, chained receipt in a single step. Returns the
 * verdict the caller enforces plus the receipt to persist (append-only).
 */
export function governAction(params: {
  action: AgentAction;
  constitution: Constitution | null | undefined;
  prevReceipt?: Receipt | null;
  chain?: string;
}): { verdict: ConstitutionDecision; receipt: Receipt } {
  const verdict = evaluateConstitution(params.action, params.constitution);
  const chain = params.chain ?? `${params.action.product}:${params.action.subjectId ?? 'global'}`;
  const receipt = buildReceipt({
    chain,
    action: params.action,
    verdict,
    prev: params.prevReceipt ?? null,
    at: params.action.at,
  });
  return { verdict, receipt };
}
export * from './receiptProjection.ts';
