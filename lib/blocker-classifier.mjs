/**
 * blocker-classifier.mjs — Routes blockers in the rework pipeline
 *
 * Classifies error output from failed tasks and decides whether to
 * skip, escalate, or rework based on the error type, rework count,
 * and blocker history.
 *
 * Usage:
 *   import { triageBlocker } from './blocker-classifier.mjs';
 *   const result = triageBlocker(errorOutput, { reworkCount: 2, lastBlockerCategory: 'type-error' });
 *   switch (result.routing.action) { ... }
 */

const MAX_REWORK_ATTEMPTS = 3;
const ESCALATION_CATEGORIES = new Set([
  'secret-leak',
  'dependency-conflict',
  'schema-migration',
  'permission-denied',
  'rate-limit',
  'out-of-memory',
]);

// ── error classification ─────────────────────────────────────────────────────

const CATEGORY_PATTERNS = [
  // Build / compilation errors
  { category: 'type-error',         pattern: /(?:TS\d{4}|TypeError|type\s+error)/i },
  { category: 'syntax-error',       pattern: /(?:SyntaxError|Unexpected\s+token|Parse\s+error)/i },
  { category: 'import-error',       pattern: /(?:Cannot\s+find\s+module|Module\s+not\s+found|ERR_MODULE_NOT_FOUND)/i },
  { category: 'build-error',        pattern: /(?:Build\s+failed|nuxi\s+build.*error|esbuild.*error)/i },

  // Test failures
  { category: 'test-assertion',     pattern: /(?:AssertionError|expect\(.*\)\.to|assert\.|FAIL\s+.*\.test\.)/i },
  { category: 'test-timeout',       pattern: /(?:Timeout.*exceeded|test.*timed?\s*out|SIGTERM)/i },
  { category: 'test-baseline',      pattern: /(?:baseline|known.red|quarantine)/i },

  // Infrastructure
  { category: 'dependency-conflict', pattern: /(?:peer\s+dep|ERESOLVE|conflicting\s+peer)/i },
  { category: 'schema-migration',   pattern: /(?:migration|schema.*drift|ALTER\s+TABLE.*error)/i },
  { category: 'permission-denied',  pattern: /(?:EACCES|Permission\s+denied|EPERM|403\s+Forbidden)/i },
  { category: 'rate-limit',         pattern: /(?:429|rate.limit|too.many.requests|quota.exceeded)/i },
  { category: 'out-of-memory',      pattern: /(?:heap|OOM|ENOMEM|JavaScript\s+heap|allocation\s+failed)/i },
  { category: 'secret-leak',        pattern: /(?:secret|credential|api.key|token).*(?:exposed|leak|commit)/i },

  // Lint / style
  { category: 'lint-error',         pattern: /(?:eslint|lint.*error|prettier.*error)/i },
  { category: 'sfc-error',          pattern: /(?:SFC|single.file.component|vue.*compile)/i },

  // Git / merge
  { category: 'merge-conflict',     pattern: /(?:CONFLICT|merge.*conflict|<{7}|>{7})/i },
  { category: 'git-error',          pattern: /(?:fatal:\s|git.*error|not\s+a\s+git\s+repo)/i },

  // Network / external
  { category: 'network-error',      pattern: /(?:ECONNREFUSED|ETIMEDOUT|fetch.*failed|network.*error)/i },

  // Catch-all
  { category: 'unknown',            pattern: /(?:error|Error|ERROR)/i },
];

function classifyError(errorOutput) {
  const categories = [];
  for (const { category, pattern } of CATEGORY_PATTERNS) {
    if (pattern.test(errorOutput)) {
      categories.push(category);
    }
  }
  return categories.length > 0 ? categories : ['unknown'];
}

function extractErrorSummary(errorOutput, maxLines = 5) {
  const lines = errorOutput.split('\n')
    .map(l => l.trim())
    .filter(l => l && !l.startsWith('at ') && !l.startsWith('node_modules'));
  // Prioritize lines with "error" in them
  const errorLines = lines.filter(l => /error/i.test(l));
  const relevant = errorLines.length > 0 ? errorLines : lines;
  return relevant.slice(0, maxLines).join('\n');
}

// ── routing logic ────────────────────────────────────────────────────────────

/**
 * @param {string} errorOutput - Raw error output from the failed task
 * @param {{ reworkCount?: number, lastBlockerCategory?: string }} context
 * @returns {{
 *   routing: { action: 'skip'|'escalate'|'rework', reason: string },
 *   classification: { categories: string[], primaryCategory: string, summary: string },
 *   metadata: { reworkCount: number, isRepeatBlocker: boolean }
 * }}
 */
export function triageBlocker(errorOutput, context = {}) {
  const { reworkCount = 0, lastBlockerCategory = '' } = context;
  const errorStr = String(errorOutput ?? '');

  const categories = classifyError(errorStr);
  const primaryCategory = categories[0];
  const summary = extractErrorSummary(errorStr);
  const isRepeatBlocker = primaryCategory === lastBlockerCategory && reworkCount > 0;

  const classification = { categories, primaryCategory, summary };
  const metadata = { reworkCount, isRepeatBlocker };

  // ── Decision tree ──

  // 1. Always escalate dangerous categories
  if (categories.some(c => ESCALATION_CATEGORIES.has(c))) {
    return {
      routing: {
        action: 'escalate',
        reason: `Category "${primaryCategory}" requires human review — cannot be auto-resolved`,
      },
      classification,
      metadata,
    };
  }

  // 2. Too many rework attempts → escalate
  if (reworkCount >= MAX_REWORK_ATTEMPTS) {
    return {
      routing: {
        action: 'escalate',
        reason: `Rework limit reached (${reworkCount}/${MAX_REWORK_ATTEMPTS}) — task is stuck on "${primaryCategory}"`,
      },
      classification,
      metadata,
    };
  }

  // 3. Same category keeps blocking → escalate after 2nd repeat
  if (isRepeatBlocker && reworkCount >= 2) {
    return {
      routing: {
        action: 'escalate',
        reason: `Repeated blocker "${primaryCategory}" after ${reworkCount} reworks — likely systemic issue`,
      },
      classification,
      metadata,
    };
  }

  // 4. Known-red test baseline failures → skip (don't burn rework cycles)
  if (primaryCategory === 'test-baseline') {
    return {
      routing: {
        action: 'skip',
        reason: 'Failure matches test baseline (known-red) — not a regression',
      },
      classification,
      metadata,
    };
  }

  // 5. Merge conflicts → rework (auto-resolvable)
  if (primaryCategory === 'merge-conflict') {
    return {
      routing: {
        action: 'rework',
        reason: 'Merge conflict detected — rework with fresh rebase',
      },
      classification,
      metadata,
    };
  }

  // 6. Build/type/import errors → rework (fixable by code changes)
  if (['type-error', 'syntax-error', 'import-error', 'build-error', 'lint-error', 'sfc-error'].includes(primaryCategory)) {
    return {
      routing: {
        action: 'rework',
        reason: `"${primaryCategory}" is auto-fixable — rework attempt ${reworkCount + 1}/${MAX_REWORK_ATTEMPTS}`,
      },
      classification,
      metadata,
    };
  }

  // 7. Test failures → rework (up to limit)
  if (['test-assertion', 'test-timeout'].includes(primaryCategory)) {
    return {
      routing: {
        action: 'rework',
        reason: `Test failure "${primaryCategory}" — rework attempt ${reworkCount + 1}/${MAX_REWORK_ATTEMPTS}`,
      },
      classification,
      metadata,
    };
  }

  // 8. Default: rework if under limit, escalate otherwise
  if (reworkCount < MAX_REWORK_ATTEMPTS) {
    return {
      routing: {
        action: 'rework',
        reason: `Unclassified error — rework attempt ${reworkCount + 1}/${MAX_REWORK_ATTEMPTS}`,
      },
      classification,
      metadata,
    };
  }

  return {
    routing: {
      action: 'escalate',
      reason: `Unresolvable after ${reworkCount} attempts`,
    },
    classification,
    metadata,
  };
}

export default { triageBlocker };
