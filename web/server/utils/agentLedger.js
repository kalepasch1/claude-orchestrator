import { govern } from './darwin/govern.ts';

/** Action states that must pass the darwin govern gate before proceeding. */
const GATED_STATES = new Set(['awaiting_approval', 'approved', 'executing']);

/** Per-chain last-known receipt (in-memory; replace with DB lookup for multi-process). */
const _receipts = new Map();

/**
 * Transition an agent action to targetState. Calls darwin govern() before any
 * gated state, persists the receipt append-only, and enforces deny decisions.
 * Fail-soft on receipt persistence so a missing darwin_receipts table never
 * crashes the transition path — that table is provisioned by an OPERATOR step.
 */
export async function transitionAction(action, targetState, supabase) {
  if (!GATED_STATES.has(targetState)) {
    return { state: targetState };
  }

  const chain = `${action.actor}:${action.userId ?? 'global'}`;
  const prevReceipt = _receipts.get(chain) ?? null;
  const { decision, receipt } = govern(action, prevReceipt);
  _receipts.set(chain, receipt);

  // Persist receipt append-only (fail-soft if table absent)
  if (supabase) {
    try {
      await supabase.from('darwin_receipts').insert({
        id: receipt.id,
        chain: receipt.chain,
        seq: receipt.seq,
        prev_hash: receipt.prevHash,
        decision: receipt.decision,
        actor: action.actor,
        action_type: action.type,
        digest: receipt.digest,
        signature_value: receipt.signature.value,
        signature_algorithm: receipt.signature.algorithm,
        public_key_pem: receipt.signature.publicKeyPem,
        at: receipt.at,
      });
    } catch (err) {
      console.warn('[agentLedger] darwin_receipts persist failed (fail-soft):', err?.message);
    }
  }

  if (decision === 'deny') {
    throw new Error(`[agentLedger] action denied by darwin governance: ${action.type}`);
  }

  return { decision, receipt, state: targetState };
}
