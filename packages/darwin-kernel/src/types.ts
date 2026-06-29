/** Shared vocabulary across all products. Kept deliberately small and stable. */

/** Which product an action / identity / event originates from. */
export type ProductId =
  | 'tomorrow'
  | 'smarter'
  | 'apparently'
  | 'pareto'
  | 'galop'
  | 'hisanta'
  | 'orchestrator'
  | 'darwinlife';

export const ALL_PRODUCTS: ProductId[] = [
  'tomorrow',
  'smarter',
  'apparently',
  'pareto',
  'galop',
  'hisanta',
  'orchestrator',
  'darwinlife',
];

/** The universal verdict any gate returns. Fail-closed: unknown => escalate. */
export type Decision = 'allow' | 'escalate' | 'deny';

/** Severity used for findings/alerts across products. */
export type Severity = 'info' | 'warning' | 'critical';

/** A namespaced action a bot/agent wants to take. Examples:
 *  'tomorrow:fabric_run', 'pareto:money_move', 'smarter:send_email',
 *  'galop:cash_out', 'hisanta:deliver_ai_message', 'apparently:publish_opinion'. */
export interface AgentAction {
  product: ProductId;
  /** dot/colon-namespaced verb, e.g. 'money_move' or 'send_email' */
  type: string;
  /** the principal acting (bot id or agent id) */
  actor: string;
  /** subject the action concerns (deal id, account id, child id, ...) */
  subjectId?: string;
  /** money magnitude in USD, if any (drives §1a-style overrides) */
  amountUsd?: number;
  /** free-form, used by rule predicates */
  metadata?: Record<string, unknown>;
  /** ISO timestamp; injected for determinism in tests */
  at?: string;
}
