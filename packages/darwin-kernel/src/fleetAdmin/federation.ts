/**
 * Multi-plane federation / mutual aid — independent orgs' control planes exchange threat signals
 * so an attack learned ANYWHERE is defended EVERYWHERE. A fraud ring hitting several companies,
 * a shared bad-actor subject, or a common failure signature seen across ≥2 planes is elevated to
 * a federated threat that every plane can pre-emptively act on. Raw data stays home; only signal
 * keys + severities cross. Pure + zero-dep.
 */
import type { AdminSeverity } from './types.ts';

export interface FederatedSignal {
  planeId: string;
  /** the shared key: a provider, an error signature, a bad-actor subject, a fraud pattern */
  signalKey: string;
  severity: number; // AdminSeverity numeric
  subjectId?: string;
  at: string;
}

export interface FederatedThreat {
  signalKey: string;
  planes: string[];
  planeCount: number;
  maxSeverity: number;
  subjectIds: string[];
  /** true when ≥2 independent planes report it — the "learned anywhere" trigger */
  elevated: boolean;
  firstSeen: string;
}

export interface FederationConfig {
  /** planes reporting the same key needed to elevate */
  elevateAtPlanes: number;
}
export const DEFAULT_FEDERATION_CONFIG: FederationConfig = { elevateAtPlanes: 2 };

/** Merge cross-plane signals into federated threats, elevating anything seen on ≥N planes. */
export function mergeFederatedThreats(signals: FederatedSignal[], cfg: FederationConfig = DEFAULT_FEDERATION_CONFIG): FederatedThreat[] {
  const groups = new Map<string, FederatedSignal[]>();
  for (const s of signals) (groups.get(s.signalKey) ?? groups.set(s.signalKey, []).get(s.signalKey)!).push(s);

  const threats: FederatedThreat[] = [];
  for (const [signalKey, arr] of groups) {
    const planes = [...new Set(arr.map((s) => s.planeId))];
    threats.push({
      signalKey,
      planes,
      planeCount: planes.length,
      maxSeverity: Math.max(...arr.map((s) => s.severity)),
      subjectIds: [...new Set(arr.map((s) => s.subjectId).filter((x): x is string => !!x))],
      elevated: planes.length >= cfg.elevateAtPlanes,
      firstSeen: arr.map((s) => s.at).sort()[0]!,
    });
  }
  return threats.sort((a, b) => Number(b.elevated) - Number(a.elevated) || b.planeCount - a.planeCount || b.maxSeverity - a.maxSeverity);
}

/** Which planes have NOT yet reported an elevated threat — the ones to pre-emptively warn. */
export function planesToWarn(threat: FederatedThreat, allPlaneIds: string[]): string[] {
  return allPlaneIds.filter((p) => !threat.planes.includes(p));
}
