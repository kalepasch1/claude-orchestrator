/**
 * Fix propagation across the fleet — when one app's incident is resolved a certain way,
 * propose the SAME remediation to every other app exhibiting the correlated signal. One
 * approval fixes N apps at once. This is the runtime-ops analogue of the orchestrator's
 * `fix_propagation.py` (which propagates code fixes) — here it propagates admin fixes.
 * Pure + zero-dep.
 */
import type { AdminAction, AdminEvent } from './types.ts';
import type { Incident } from './correlate.ts';
import { correlationKeys } from './correlate.ts';
import { contentId } from '../crypto/hash.ts';

export interface PropagationProposal {
  /** the peer event that shares the incident's root-cause signal */
  targetEvent: AdminEvent;
  /** the proposed remediation for that peer, cloned from the fix that worked */
  action: AdminAction;
  sharedSignals: string[];
}

/**
 * Given the incident, the action that fixed ONE of its events, and the pool of open
 * events, propose the same fix for every other event that shares a root-cause signal
 * with the incident and hasn't already been actioned.
 */
export function propagateFix(
  incident: Incident,
  fixingAction: AdminAction,
  openEvents: AdminEvent[],
  alreadyActionedEventIds: Set<string> = new Set(),
): PropagationProposal[] {
  const incidentSignals = new Set(incident.rootCauseSignals);
  if (incidentSignals.size === 0) return [];

  const proposals: PropagationProposal[] = [];
  for (const ev of openEvents) {
    // Skip the event that was already fixed (the origin) + anything already actioned.
    // Every OTHER event sharing the incident's signal is a propagation target — that is
    // the whole point: one fix, applied across every app in the blast radius.
    if (ev.id === fixingAction.eventId) continue;
    if (alreadyActionedEventIds.has(ev.id)) continue;
    const shared = correlationKeys(ev).filter((k) => incidentSignals.has(k));
    if (shared.length === 0) continue;

    const action: AdminAction = {
      ...fixingAction,
      id: contentId('act', { from: fixingAction.id, to: ev.id }),
      product: ev.product,
      domain: ev.domain,
      eventId: ev.id,
      subjectId: ev.subjectId,
      intent: `${fixingAction.intent} (propagated from ${fixingAction.product} — same root cause: ${shared.join(', ')})`,
      // A propagated fix is proposed, never silently auto-applied: it is a fresh action
      // that must clear the gate on its own domain/blast for THIS app.
      at: new Date(ev.at).toISOString(),
    };
    proposals.push({ targetEvent: ev, action, sharedSignals: shared });
  }
  return proposals;
}
