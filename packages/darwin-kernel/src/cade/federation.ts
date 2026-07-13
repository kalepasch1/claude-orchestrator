/**
 * Federated determination + adversarial oracle screening.
 *
 * - federatedDetermination: aggregate multiple participant nodes' LOCAL determinations
 *   into one consensus without moving data, suppressing sub-k cohorts (privacy).
 * - screenOracleSources: red-team the oracle sources themselves (staleness, outliers,
 *   collusion/over-representation) before they enter settlement consensus.
 * Pure.
 */

export interface LocalDetermination {
  nodeId: string;
  stance: number;      // [-1,1]
  confidence: number;  // [0,1]
  /** cohort size behind this node's local result (for k-anonymity). */
  cohortSize: number;
}

export interface FederatedResult {
  stance: number;
  confidence: number;
  contributors: number;
  suppressed: string[]; // node ids dropped for sub-k cohorts
}

/**
 * Confidence-weighted aggregate across nodes whose cohort clears `minCohort`
 * (k-anonymity). No raw data crosses a node boundary — only the local summary.
 */
export function federatedDetermination(
  locals: LocalDetermination[],
  opts: { minCohort?: number } = {},
): FederatedResult {
  const k = opts.minCohort ?? 3;
  const kept = locals.filter((l) => l.cohortSize >= k);
  const suppressed = locals.filter((l) => l.cohortSize < k).map((l) => l.nodeId);
  if (kept.length === 0) return { stance: 0, confidence: 0, contributors: 0, suppressed };
  let ws = 0;
  let wc = 0;
  let w = 0;
  for (const l of kept) {
    const weight = clamp01(l.confidence);
    ws += l.stance * weight;
    wc += clamp01(l.confidence);
    w += weight;
  }
  return {
    stance: w > 0 ? ws / w : 0,
    confidence: wc / kept.length,
    contributors: kept.length,
    suppressed,
  };
}

export interface OracleSourceReading {
  id: string;
  value: number;
  ageMs: number;
  /** provenance/operator cluster — used to detect collusion / over-representation. */
  cluster?: string;
}

export interface OracleScreen {
  admitted: OracleSourceReading[];
  rejected: { id: string; reason: 'stale' | 'outlier' | 'collusion' }[];
}

/**
 * Adversarial oracle: reject stale readings, statistical outliers (robust z vs the
 * median / MAD), and sources that would let one cluster over-represent the panel.
 */
export function screenOracleSources(
  sources: OracleSourceReading[],
  opts: { maxAgeMs?: number; outlierZ?: number; maxPerCluster?: number } = {},
): OracleScreen {
  const maxAge = opts.maxAgeMs ?? 60_000;
  const zCut = opts.outlierZ ?? 3;
  const maxPerCluster = opts.maxPerCluster ?? Infinity;

  const rejected: OracleScreen['rejected'] = [];
  let pool = sources.filter((s) => {
    if (s.ageMs > maxAge) {
      rejected.push({ id: s.id, reason: 'stale' });
      return false;
    }
    return true;
  });

  // robust outlier screen (median + MAD)
  if (pool.length >= 3) {
    const vals = pool.map((s) => s.value).sort((a, b) => a - b);
    const med = median(vals);
    const mad = median(vals.map((v) => Math.abs(v - med))) || 1e-9;
    pool = pool.filter((s) => {
      const z = (0.6745 * (s.value - med)) / mad;
      if (Math.abs(z) > zCut) {
        rejected.push({ id: s.id, reason: 'outlier' });
        return false;
      }
      return true;
    });
  }

  // collusion / over-representation cap per cluster
  const perCluster = new Map<string, number>();
  const admitted: OracleSourceReading[] = [];
  for (const s of pool) {
    const c = s.cluster ?? s.id;
    const n = perCluster.get(c) ?? 0;
    if (n >= maxPerCluster) {
      rejected.push({ id: s.id, reason: 'collusion' });
      continue;
    }
    perCluster.set(c, n + 1);
    admitted.push(s);
  }
  return { admitted, rejected };
}

function median(xs: number[]): number {
  if (xs.length === 0) return 0;
  const s = [...xs].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? (s[mid] ?? 0) : ((s[mid - 1] ?? 0) + (s[mid] ?? 0)) / 2;
}
function clamp01(x: number): number {
  return Math.max(0, Math.min(1, x));
}
