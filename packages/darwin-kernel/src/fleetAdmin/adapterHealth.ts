/**
 * Self-healing adapters — the plane maintains its own connective tissue. When an app's
 * /api/fleet/execute starts failing or its emit schema drifts, this detects it from the
 * execution/error stream, raises an infra incident, and drafts a code-fix TASK for the
 * orchestrator's existing Claude-Code runner (the same runner that ships code fixes). The
 * admin plane starts repairing the adapters that feed it. Pure + zero-dep.
 */
import { contentId } from '../crypto/hash.ts';
import { AdminSeverity, type AdminEvent } from './types.ts';

export interface ExecutionOutcome {
  product: string;
  ok: boolean;
  error?: string;
  at: string;
}

export interface AdapterHealthReport {
  product: string;
  total: number;
  failures: number;
  failureRate: number;
  status: 'healthy' | 'degraded' | 'failing';
  /** the dominant error string, if any (the thing to fix) */
  topError?: string;
  /** an infra AdminEvent to raise when failing (feeds the plane like any other event) */
  incident?: AdminEvent;
  /** a code-fix task for the orchestrator runner (build | efficiency workload) */
  proposedFix?: { slug: string; prompt: string };
}

export interface HealthConfig {
  degradedRate: number;
  failingRate: number;
  minSample: number;
}
export const DEFAULT_HEALTH_CONFIG: HealthConfig = { degradedRate: 0.1, failingRate: 0.3, minSample: 5 };

/** The canonical required fields on an emitted AdminEvent — used for drift detection. */
export const REQUIRED_EVENT_FIELDS = ['id', 'product', 'domain', 'category', 'severity', 'title', 'at'] as const;

/** Detect emit-schema drift: which required fields an incoming event object is missing. */
export function detectEventDrift(obj: Record<string, unknown>): string[] {
  return REQUIRED_EVENT_FIELDS.filter((f) => obj[f] === undefined || obj[f] === null);
}

function topError(outcomes: ExecutionOutcome[]): string | undefined {
  const counts = new Map<string, number>();
  for (const o of outcomes) if (!o.ok && o.error) counts.set(o.error, (counts.get(o.error) ?? 0) + 1);
  return [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];
}

/** Assess each app's adapter health from its recent execution outcomes. */
export function assessAdapterHealth(
  outcomes: ExecutionOutcome[],
  cfg: HealthConfig = DEFAULT_HEALTH_CONFIG,
): AdapterHealthReport[] {
  const byProduct = new Map<string, ExecutionOutcome[]>();
  for (const o of outcomes) (byProduct.get(o.product) ?? byProduct.set(o.product, []).get(o.product)!).push(o);

  const reports: AdapterHealthReport[] = [];
  for (const [product, arr] of byProduct) {
    const total = arr.length;
    const failures = arr.filter((o) => !o.ok).length;
    const failureRate = total ? Math.round((failures / total) * 100) / 100 : 0;
    let status: AdapterHealthReport['status'] = 'healthy';
    if (total >= cfg.minSample && failureRate >= cfg.failingRate) status = 'failing';
    else if (total >= cfg.minSample && failureRate >= cfg.degradedRate) status = 'degraded';

    const report: AdapterHealthReport = { product, total, failures, failureRate, status, topError: topError(arr) };

    if (status === 'failing') {
      const at = arr[arr.length - 1]?.at ?? new Date().toISOString();
      report.incident = {
        id: contentId('ev', { adapter: product, at }),
        product: product as AdminEvent['product'],
        domain: 'infra',
        category: 'system_error',
        severity: AdminSeverity.URGENT,
        title: `Adapter failing: ${product} /api/fleet/execute`,
        summary: `${failures}/${total} recent executions failed (${Math.round(failureRate * 100)}%). Top error: ${report.topError ?? 'unknown'}.`,
        details: { failureRate, topError: report.topError },
        at,
      };
      report.proposedFix = {
        slug: `fix-fleet-adapter-${product}`,
        prompt:
          `The Fleet Admin adapter for ${product} (server/api/fleet/execute + server/utils/fleet-adapter) is failing ` +
          `${Math.round(failureRate * 100)}% of executions. Dominant error: "${report.topError ?? 'unknown'}". ` +
          `Diagnose and fix the execute handler so cleared AdminActions run reliably, keep it idempotent on action.id, ` +
          `and return {ok, ref, undoToken?}. Add a regression test. Do not change the kernel contract.`,
      };
    }
    reports.push(report);
  }
  return reports.sort((a, b) => b.failureRate - a.failureRate);
}
