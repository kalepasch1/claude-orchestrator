/** Small, dependency-free vector helpers + a deterministic fallback embedder. */
import { sha256 } from '../crypto/hash.ts';
import type { CompetenceVector, Embedder } from './types.ts';

export function dot(a: number[], b: number[]): number {
  const n = Math.min(a.length, b.length);
  let s = 0;
  for (let i = 0; i < n; i++) s += (a[i] ?? 0) * (b[i] ?? 0);
  return s;
}

export function norm(a: number[]): number {
  return Math.sqrt(dot(a, a));
}

export function cosine(a: number[], b: number[]): number {
  const na = norm(a);
  const nb = norm(b);
  if (na === 0 || nb === 0) return 0;
  return dot(a, b) / (na * nb);
}

/** Cosine over sparse competence maps (shared keys only). */
export function competenceCosine(a: CompetenceVector, b: CompetenceVector): number {
  let s = 0;
  let na = 0;
  let nb = 0;
  for (const k of Object.keys(a)) na += (a[k] ?? 0) ** 2;
  for (const k of Object.keys(b)) nb += (b[k] ?? 0) ** 2;
  for (const k of Object.keys(a)) {
    if (k in b) s += (a[k] ?? 0) * (b[k] ?? 0);
  }
  if (na === 0 || nb === 0) return 0;
  return s / (Math.sqrt(na) * Math.sqrt(nb));
}

/** Euclidean distance — used as the "novelty" signal in panel selection. */
export function distance(a: number[], b: number[]): number {
  const n = Math.max(a.length, b.length);
  let s = 0;
  for (let i = 0; i < n; i++) {
    const d = (a[i] ?? 0) - (b[i] ?? 0);
    s += d * d;
  }
  return Math.sqrt(s);
}

export function centroid(vectors: number[][]): number[] {
  if (vectors.length === 0) return [];
  const dim = vectors.reduce((m, v) => Math.max(m, v.length), 0);
  const out = new Array<number>(dim).fill(0);
  for (const v of vectors) for (let i = 0; i < dim; i++) out[i] = (out[i] ?? 0) + (v[i] ?? 0);
  for (let i = 0; i < dim; i++) out[i] = (out[i] ?? 0) / vectors.length;
  return out;
}

/**
 * Deterministic fallback embedder: hashed token bag into a fixed-dim unit vector.
 * Good enough for clustering/diversity in tests; products inject a real embedder.
 */
export function hashEmbedder(dim = 64): Embedder {
  return {
    embed(text: string): number[] {
      const out = new Array<number>(dim).fill(0);
      const tokens = text.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
      for (const t of tokens) {
        const h = sha256(t);
        const idx = parseInt(h.slice(0, 8), 16) % dim;
        const sign = (parseInt(h.slice(8, 9), 16) & 1) === 0 ? 1 : -1;
        out[idx] = (out[idx] ?? 0) + sign;
      }
      const nrm = norm(out);
      if (nrm > 0) for (let i = 0; i < dim; i++) out[i] = (out[i] ?? 0) / nrm;
      return out;
    },
  };
}

export function summarize(samples: number[]): { p5: number; p50: number; p95: number; tailMean: number } {
  const s = [...samples].sort((a, b) => a - b);
  const at = (q: number) => s[Math.min(s.length - 1, Math.max(0, Math.floor(q * (s.length - 1))))] ?? 0;
  const tailCut = Math.max(1, Math.floor(0.05 * s.length));
  const tail = s.slice(0, tailCut);
  const tailMean = tail.reduce((a, b) => a + b, 0) / tail.length;
  return { p5: at(0.05), p50: at(0.5), p95: at(0.95), tailMean };
}
