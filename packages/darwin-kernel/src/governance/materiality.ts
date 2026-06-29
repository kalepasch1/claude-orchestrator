/**
 * Materiality classifier — decides whether a change (code edit OR runtime action)
 * needs human approval before it takes effect. Generalized from Tomorrow's
 * gitAutomation classifier + the orchestrator's approval-card gate.
 *
 * FAIL CLOSED: empty/unknown input => material (requires approval).
 */
export interface MaterialityRule {
  /** regex (string form) matched against the change path or action key */
  pattern: string;
  reason: string;
}

export interface MaterialityResult {
  material: boolean;
  matched: string[];
  reason: string;
}

/** Portfolio-wide defaults. Each product appends its own sensitive paths. */
export const DEFAULT_MATERIAL_PATTERNS: MaterialityRule[] = [
  { pattern: 'governance/', reason: 'agent governance core' },
  { pattern: 'constitution', reason: 'policy enforcement layer' },
  { pattern: 'passport|identity', reason: 'cross-product identity/credentials' },
  { pattern: 'migrations?/|schema\\.prisma', reason: 'database schema' },
  { pattern: 'funds?/|webhook|stripe|plaid|payout|settlement', reason: 'money movement' },
  { pattern: 'auth|middleware|rls|policy', reason: 'access control' },
  { pattern: '\\.env|secret|signing', reason: 'secrets / signing keys' },
  { pattern: 'kyc|aml|sanctions|ecp', reason: 'compliance gates' },
];

/**
 * Classify a list of changed paths (or a single action key).
 * Non-material only if NOTHING matches and the input is non-empty.
 */
export function classifyMateriality(
  changedPaths: string[],
  extra: MaterialityRule[] = [],
): MaterialityResult {
  if (!changedPaths || changedPaths.length === 0) {
    return { material: true, matched: [], reason: 'empty_changeset_fail_closed' };
  }
  const rules = [...DEFAULT_MATERIAL_PATTERNS, ...extra];
  const matched: string[] = [];
  for (const path of changedPaths) {
    for (const r of rules) {
      try {
        if (new RegExp(r.pattern, 'i').test(path)) matched.push(`${path} :: ${r.reason}`);
      } catch {
        // a malformed pattern must not make a material change look safe
        matched.push(`${path} :: pattern_error_fail_closed`);
      }
    }
  }
  return matched.length > 0
    ? { material: true, matched, reason: 'matched_material_patterns' }
    : { material: false, matched: [], reason: 'no_material_patterns' };
}
