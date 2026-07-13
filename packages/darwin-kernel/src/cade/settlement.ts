/**
 * CADE settlement primitives — turn a Determination into bilateral, posture-safe
 * settlement / capital signals consumed by Tomorrow's determination protocol,
 * compression engine and margin optimizer.
 *
 * Posture invariants encoded here (all pure calc, no I/O):
 *   - the operator is never a principal — these functions only compute/propose;
 *   - offsets are NAMED BILATERAL legs (A↔B), never a pool / CCP;
 *   - haircuts/prices are advisory numbers, never an instruction to move funds.
 */
import type { Determination, OptimalityCertificate } from './types.ts';

/** An attested reading the settlement engine can treat as an oracle source. */
export interface OracleReading {
  sourceId: string;
  /** numeric mark when the issue is quantitative; else the lead-position hash slot. */
  value: number | undefined;
  /** calibrated confidence in [0,1] (from the certificate). */
  confidence: number;
  ageMs: number;
  /** content-addressed evidence (the proof digest) for hash-chained audit. */
  evidenceDigest: string;
  /** the precedent this determination establishes / cites. */
  precedentId: string;
  /** highest assurance tier that resolved it (L0 machine-proved ranks above oracle). */
  provedTier?: 'L0' | 'panel';
}

/**
 * Bridge #1: register an adversarial-consensus Determination as an attested oracle
 * source. Calc-only; the settlement engine decides how to use it under its policy.
 */
export function toOracleReading(
  det: Determination,
  opts: { ageMs?: number; provedTier?: 'L0' | 'panel' } = {},
): OracleReading {
  return {
    sourceId: `cade:${det.proof.id}`,
    value: det.value,
    confidence: det.certificate.confidence,
    ageMs: Math.max(0, opts.ageMs ?? 0),
    evidenceDigest: det.proof.digest,
    precedentId: det.proof.id,
    provedTier: opts.provedTier,
  };
}

/** A bilateral ECP position that pays if a determination is overturned (or upheld). */
export interface ChallengeLeg {
  participantId: string;
  side: 'overturn' | 'uphold';
  notionalUsd: number;
  /** the taker's price = their implied P(overturn) for this leg, in [0,1]. */
  price: number;
}

/**
 * #5 Challenge legs → a money-weighted implied overturn probability, blended with
 * the engine's own confidence. Pure aggregation; the legs themselves are bilateral.
 */
export function impliedOverturnProbability(
  baseConfidence: number,
  legs: ChallengeLeg[],
  priorWeight = 0.5,
): number {
  const base = clamp01(1 - baseConfidence); // engine's own P(overturn)
  let wsum = 0;
  let w = 0;
  for (const l of legs) {
    const n = Math.max(0, l.notionalUsd);
    const p = clamp01(l.side === 'overturn' ? l.price : 1 - l.price);
    wsum += p * n;
    w += n;
  }
  if (w === 0) return base;
  const market = wsum / w;
  return clamp01(priorWeight * base + (1 - priorWeight) * market);
}

export interface EventPosition {
  participantId: string;
  eventId: string;
  notionalUsd: number;
  /** +1 = long the event paying out, -1 = short. */
  side: 1 | -1;
}

export interface CompressionLeg {
  eventId: string;
  a: string; // long participant
  b: string; // short participant
  offsetUsd: number;
}

export interface CompressionResult {
  legs: CompressionLeg[];
  /** gross notional removed. */
  compressedUsd: number;
  /** residual per (participant,event) after bilateral matching. */
  residual: Record<string, number>;
}

/**
 * #7 Legal-event exposure compression: greedily match opposing sides on the same
 * event into NAMED BILATERAL offset legs (A↔B). Never a pool, never a CCP —
 * each leg is a proposed bilateral offset the two named parties may adopt.
 */
export function proposeEventCompression(positions: EventPosition[]): CompressionResult {
  const byEvent = new Map<string, EventPosition[]>();
  for (const p of positions) {
    const arr = byEvent.get(p.eventId) ?? [];
    arr.push(p);
    byEvent.set(p.eventId, arr);
  }
  const legs: CompressionLeg[] = [];
  const residual: Record<string, number> = {};
  let compressedUsd = 0;
  for (const [eventId, arr] of byEvent) {
    const longs = arr.filter((p) => p.side === 1).map((p) => ({ id: p.participantId, n: p.notionalUsd }));
    const shorts = arr.filter((p) => p.side === -1).map((p) => ({ id: p.participantId, n: p.notionalUsd }));
    let i = 0;
    let j = 0;
    while (i < longs.length && j < shorts.length) {
      const L = longs[i];
      const S = shorts[j];
      if (!L || !S) break;
      const m = Math.min(L.n, S.n);
      if (m > 0) {
        legs.push({ eventId, a: L.id, b: S.id, offsetUsd: m });
        compressedUsd += m;
        L.n -= m;
        S.n -= m;
      }
      if (L.n <= 1e-9) i++;
      if (S.n <= 1e-9) j++;
    }
    for (const L of longs) if (L.n > 1e-9) residual[`${L.id}:${eventId}:+`] = L.n;
    for (const S of shorts) if (S.n > 1e-9) residual[`${S.id}:${eventId}:-`] = S.n;
  }
  return { legs, compressedUsd, residual };
}

/**
 * #8 Certainty passport → margin haircut multiplier. Higher certified confidence
 * ⇒ lower enforceability risk ⇒ smaller haircut multiplier (bounded). Advisory
 * input to the margin optimizer; Tomorrow computes it, never holds collateral.
 */
export function marginHaircutMultiplier(
  cert: OptimalityCertificate,
  bounds: { floor?: number; sensitivity?: number } = {},
): number {
  const floor = bounds.floor ?? 0.5;
  const k = bounds.sensitivity ?? 1;
  const mult = 1 - k * clamp01(cert.confidence) * (1 - floor);
  return Math.max(floor, Math.min(1, mult));
}

function clamp01(x: number): number {
  return Math.max(0, Math.min(1, x));
}
