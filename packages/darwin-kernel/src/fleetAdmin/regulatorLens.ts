/**
 * Regulator co-pilot lens — turn oversight from an audit event into a live, self-serve
 * interface. A regulator asks in English ("show every auto-approved action over $500 in Q2 and
 * prove it was in policy"); this returns a scoped, READ-ONLY, PII-redacted answer with the
 * signed proof digest for each matching decision. No writes, no raw subject data. Pure + zero-dep.
 */
export interface DecisionRecord {
  actionId: string;
  product: string;
  domain: string;
  type: string;
  tier: 'auto' | 'co_pilot' | 'human';
  decision: 'allow' | 'escalate' | 'deny';
  amountUsd?: number;
  subjectId?: string;
  at: string;
  receiptDigest: string;
}

interface Filters {
  minAmountUsd?: number;
  autoOnly?: boolean;
  decision?: 'allow' | 'escalate' | 'deny';
  fromIso?: string;
  toIso?: string;
}

const QUARTERS: Record<string, [string, string]> = {
  q1: ['-01-01', '-04-01'], q2: ['-04-01', '-07-01'], q3: ['-07-01', '-10-01'], q4: ['-10-01', '-12-31'],
};

/** Deterministic parse of a compliance question into structured, safe filters. */
export function parseRegulatorQuery(q: string): Filters {
  const s = q.toLowerCase();
  const f: Filters = {};
  const amt = s.match(/(?:over|above|greater than|>)\s*\$?\s*([\d,]+)/);
  if (amt) f.minAmountUsd = Number(amt[1]!.replace(/,/g, ''));
  if (/auto[- ]?approv|auto[- ]?run|autonomous/.test(s)) f.autoOnly = true;
  if (/denied|blocked/.test(s)) f.decision = 'deny';
  else if (/escalat|human/.test(s)) f.decision = 'escalate';
  const qm = s.match(/q([1-4]).*?(\d{4})|(\d{4}).*?q([1-4])/);
  if (qm) {
    const qtr = `q${qm[1] ?? qm[4]}`;
    const yr = qm[2] ?? qm[3];
    const [a, b] = QUARTERS[qtr]!;
    f.fromIso = `${yr}${a}`; f.toIso = `${yr}${b}`;
  }
  return f;
}

function redactSubject(id?: string): string | undefined {
  if (!id) return undefined;
  let x = 5381;
  for (let i = 0; i < id.length; i++) x = (x * 33) ^ id.charCodeAt(i);
  return `subj_${(x >>> 0).toString(16).slice(0, 8)}`;
}

export interface RegulatorAnswer {
  answer: string;
  filters: Filters;
  matches: (Omit<DecisionRecord, 'subjectId'> & { subject: string | undefined })[];
  count: number;
  proofDigests: string[];
}

/** Answer a regulator query over decision records — filtered, redacted, proof-linked, read-only. */
export function regulatorQuery(query: string, records: DecisionRecord[]): RegulatorAnswer {
  const f = parseRegulatorQuery(query);
  const matches = records.filter((r) =>
    (f.minAmountUsd === undefined || (r.amountUsd ?? 0) >= f.minAmountUsd) &&
    (!f.autoOnly || (r.decision === 'allow' && r.tier === 'auto')) &&
    (!f.decision || r.decision === f.decision) &&
    (!f.fromIso || r.at >= f.fromIso) &&
    (!f.toIso || r.at < f.toIso),
  );
  const redacted = matches.map(({ subjectId, ...r }) => ({ ...r, subject: redactSubject(subjectId) }));
  return {
    answer: `${matches.length} decision(s) match${f.minAmountUsd ? ` over $${f.minAmountUsd}` : ''}${f.autoOnly ? ', auto-approved' : ''}${f.fromIso ? ` in ${f.fromIso.slice(0, 4)}` : ''}. Each carries a signed, offline-verifiable proof digest; subject identifiers are redacted.`,
    filters: f,
    matches: redacted,
    count: matches.length,
    proofDigests: matches.map((r) => r.receiptDigest),
  };
}
