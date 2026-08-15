export type DecisionRisk = { category: string; severity: 'low' | 'medium' | 'high' | 'critical'; statement: string; mitigation: string }

/** One decision option offered by the orchestrator, from `approvals.brief_json.options`. */
export type DecisionOption = { label: string; detail?: string; recommended?: boolean }

export type DecisionBrief = {
  classification: string
  plainLanguage: string
  proposedChanges: string[]
  authorizationMeaning: string
  completionMeaning: string
  rewards: string[]
  risks: DecisionRisk[]
  prerequisites: string[]
  missingEvidence: string[]
  verification: string[]
  rollback: string
  reversibility: 'reversible' | 'partially_reversible' | 'hard_to_reverse'
  blastRadius: string
  recommendation: 'APPROVE WITH CONDITIONS' | 'HOLD FOR EVIDENCE' | 'ESCALATE' | 'ACKNOWLEDGE'
  confidence: number
  denyMeaning: string
  material: boolean

  // ── Orchestrator-supplied content ────────────────────────────────────────
  /**
   * `'orchestrator'` when `approvals.prebrief` or `approvals.brief_json` supplied
   * any of the content below, `'derived'` when the brief is purely heuristic.
   *
   * WHY THIS EXISTS
   * ---------------
   * `legal_prebrief.py` writes a plain-English brief into `approvals.prebrief`
   * and `owner_decision_model.py` writes options / a recommended index / a model
   * rationale into `approvals.brief_json`. This function read neither: it
   * classified from `kind`/`title`/`why` alone, so every one of those writes was
   * invisible in the review UI and the feature looked stalled. Both fields are
   * now read, and orchestrator content wins over the heuristic — a model that
   * actually read the item beats keyword matching on its title.
   */
  source: 'derived' | 'orchestrator'
  /** The verbatim `approvals.prebrief` text, when present. */
  prebrief?: string
  /** Decision options from `brief_json.options`. */
  options: DecisionOption[]
  /** Index into `options` the orchestrator recommends, when it named one. */
  recommendedIndex?: number
  /** `brief_json.model_rationale` — why the orchestrator recommends that option. */
  modelRationale?: string
}

type ApprovalLike = Record<string, any>

// ─── Orchestrator field readers ───────────────────────────────────────────────

const RECOMMENDATIONS = ['APPROVE WITH CONDITIONS', 'HOLD FOR EVIDENCE', 'ESCALATE', 'ACKNOWLEDGE'] as const
const REVERSIBILITIES = ['reversible', 'partially_reversible', 'hard_to_reverse'] as const
const SEVERITIES = ['low', 'medium', 'high', 'critical'] as const

/**
 * `brief_json` arrives as an object from PostgREST but as a string from any path
 * that has round-tripped through text (CSV export, older rows, a raw fetch that
 * did not parse jsonb). Accept both; never throw on malformed JSON.
 */
function readBriefJson(value: unknown): Record<string, any> | null {
  if (!value) return null
  if (typeof value === 'object' && !Array.isArray(value)) return value as Record<string, any>
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value)
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null
    } catch { return null }
  }
  return null
}

const nonEmptyString = (v: unknown): string | undefined =>
  typeof v === 'string' && v.trim() ? v.trim() : undefined

const stringList = (v: unknown): string[] | undefined => {
  if (!Array.isArray(v)) return undefined
  const items = v.map(item => nonEmptyString(item)).filter((s): s is string => Boolean(s))
  return items.length ? items : undefined
}

function readOptions(v: unknown): DecisionOption[] {
  if (!Array.isArray(v)) return []
  return v
    .map((raw): DecisionOption | null => {
      if (typeof raw === 'string') return raw.trim() ? { label: raw.trim() } : null
      if (raw && typeof raw === 'object') {
        const label = nonEmptyString((raw as any).label) ?? nonEmptyString((raw as any).title)
        if (!label) return null
        return {
          label,
          detail: nonEmptyString((raw as any).detail) ?? nonEmptyString((raw as any).description),
          recommended: Boolean((raw as any).recommended),
        }
      }
      return null
    })
    .filter((o): o is DecisionOption => o !== null)
}

function readRisks(v: unknown): DecisionRisk[] | undefined {
  if (!Array.isArray(v)) return undefined
  const risks = v
    .map((raw): DecisionRisk | null => {
      if (!raw || typeof raw !== 'object') return null
      const statement = nonEmptyString((raw as any).statement) ?? nonEmptyString((raw as any).risk)
      if (!statement) return null
      const severity = (raw as any).severity
      return {
        category: nonEmptyString((raw as any).category) ?? 'Operational',
        severity: SEVERITIES.includes(severity) ? severity : 'medium',
        statement,
        mitigation: nonEmptyString((raw as any).mitigation) ?? 'No mitigation supplied by the orchestrator.',
      }
    })
    .filter((r): r is DecisionRisk => r !== null)
  return risks.length ? risks : undefined
}

/** A confidence the orchestrator may express as 0–1 or 0–100. */
function readConfidence(v: unknown): number | undefined {
  if (typeof v !== 'number' || !Number.isFinite(v)) return undefined
  const scaled = v > 0 && v <= 1 ? v * 100 : v
  return Math.max(0, Math.min(100, Math.round(scaled)))
}

function readIndex(bj: Record<string, any>, optionCount: number): number | undefined {
  for (const key of ['recommended_index', 'suggested_option_index']) {
    const raw = bj[key]
    if (typeof raw === 'number' && Number.isInteger(raw) && raw >= 0 && raw < optionCount) return raw
  }
  return undefined
}

/**
 * Overlay whatever the orchestrator actually wrote onto the heuristic brief.
 * Every field is optional and individually validated: a partially-populated or
 * malformed `brief_json` degrades to the derived value rather than blanking the
 * card, which is the failure mode that matters on a review screen.
 */
function applyOrchestratorContent(base: DecisionBrief, a: ApprovalLike): DecisionBrief {
  const prebrief = nonEmptyString(a.prebrief)
  const bj = readBriefJson(a.brief_json ?? a.briefJson)
  if (!prebrief && !bj) return base

  const brief: DecisionBrief = { ...base, source: 'orchestrator' }

  // The prebrief is the human-readable summary a person wrote this feature for.
  if (prebrief) {
    brief.prebrief = prebrief
    brief.plainLanguage = prebrief
  }

  if (!bj) return brief

  // brief_json.plain_language outranks the prebrief only when explicitly set.
  const plain = nonEmptyString(bj.plain_language) ?? nonEmptyString(bj.plainLanguage) ?? nonEmptyString(bj.summary)
  if (plain) brief.plainLanguage = plain

  const classification = nonEmptyString(bj.classification)
  if (classification) brief.classification = classification

  const proposedChanges = stringList(bj.proposed_changes ?? bj.proposedChanges)
  if (proposedChanges) brief.proposedChanges = proposedChanges

  const rewards = stringList(bj.rewards)
  if (rewards) brief.rewards = rewards

  const prerequisites = stringList(bj.prerequisites)
  if (prerequisites) brief.prerequisites = prerequisites

  const missingEvidence = stringList(bj.missing_evidence ?? bj.missingEvidence)
  if (missingEvidence) brief.missingEvidence = missingEvidence

  const verification = stringList(bj.verification)
  if (verification) brief.verification = verification

  const risks = readRisks(bj.risks)
  if (risks) brief.risks = risks

  const rollback = nonEmptyString(bj.rollback)
  if (rollback) brief.rollback = rollback

  const blastRadius = nonEmptyString(bj.blast_radius ?? bj.blastRadius)
  if (blastRadius) brief.blastRadius = blastRadius

  if (RECOMMENDATIONS.includes(bj.recommendation)) brief.recommendation = bj.recommendation
  if (REVERSIBILITIES.includes(bj.reversibility)) brief.reversibility = bj.reversibility

  const confidence = readConfidence(bj.confidence)
  if (confidence !== undefined) brief.confidence = confidence

  if (typeof bj.material === 'boolean') brief.material = bj.material

  brief.options = readOptions(bj.options)
  brief.recommendedIndex = readIndex(bj, brief.options.length)
  if (brief.recommendedIndex !== undefined) {
    brief.options = brief.options.map((o, i) => ({ ...o, recommended: i === brief.recommendedIndex }))
  }

  brief.modelRationale = nonEmptyString(bj.model_rationale) ?? nonEmptyString(bj.modelRationale) ?? nonEmptyString(bj.rationale)

  return brief
}

const textOf = (a: ApprovalLike) => [a.kind, a.title, a.why, a.value, a.risk, a.detail, a.draft].filter(Boolean).join(' ').toLowerCase()
const includesAny = (text: string, terms: string[]) => terms.some(term => text.includes(term))

/**
 * Build a decision brief for an approval card.
 *
 * Two layers: the keyword heuristic below, then whatever the orchestrator wrote
 * into `approvals.prebrief` / `approvals.brief_json` overlaid on top. Cards with
 * neither field behave exactly as before.
 */
export function deriveDecisionBrief(a: ApprovalLike): DecisionBrief {
  return applyOrchestratorContent(deriveHeuristicBrief(a ?? {}), a ?? {})
}

/** Keyword classification over the card's own text. No orchestrator input. */
function deriveHeuristicBrief(a: ApprovalLike): DecisionBrief {
  const text = textOf(a)
  const secret = includesAny(text, ['secret', 'token', 'credential', 'api key', 'client secret'])
  const oauth = includesAny(text, ['oauth', 'login', 'account consent'])
  const migration = includesAny(text, ['migration', 'schema', 'database', 'deploy cade-publish-store'])
  const deploy = includesAny(text, ['deploy', 'release', 'production'])
  const legal = a.kind === 'legal' || includesAny(text, ['legal sign-off', 'counsel', 'regulatory', 'binding terms'])
  const publishing = includesAny(text, ['medium_integration_token', 'medium', 'publish', 'canonicalurl', 'canonical url'])
  const autonomous = includesAny(text, ['autonomous=true', 'autonomous publishing', 'auto-publish'])
  const informational = includesAny(text, ['acknowledge', 'informational notice', 'already applied'])
  const material = secret || oauth || migration || deploy || legal || publishing || Boolean(a.material)

  if (publishing && secret && migration) {
    return {
      classification: 'Credential + external publishing + production migration',
      plainLanguage: 'This request would connect Tomorrow to a Medium account, set the public website used in canonical links, and add database storage that records CADE publishing attempts and outcomes. Content remains human-reviewed unless the separate autonomous-publishing flag is later enabled.',
      proposedChanges: [
        'Store a Medium integration token in the approved production secret vault; never in source code, logs, or card text.',
        'Set and validate the canonical website base URL used in published links and attribution.',
        'Apply the reviewed cade-publish-store database migration and record its migration receipt.',
        'Keep CADE_PUBLISH_AUTONOMOUS disabled so a person reviews every external publication.',
      ],
      authorizationMeaning: 'Approval authorizes an operator to provision the scoped secret, configure the canonical URL, and execute the reviewed migration. It does not mean the token has been supplied, the migration has succeeded, or any article may be published automatically.',
      completionMeaning: 'Complete only after secret-vault receipt, token-scope test, canonical-link preview, migration verification, rollback evidence, and a human-reviewed dry-run publication receipt are attached.',
      rewards: ['Restores Medium publishing through one controlled integration.', 'Creates an auditable, idempotent publication store instead of relying on memory or logs.', 'Preserves human editorial review while enabling CADE drafting and recovery.', 'Correct canonical URLs protect attribution and reduce duplicate-content/SEO errors.'],
      risks: [
        { category: 'Credential security', severity: 'high', statement: 'A leaked or over-scoped Medium token could permit unauthorized publishing or account access.', mitigation: 'Use the deployment vault, minimum provider scope, masked logs, rotation instructions, and a revocation test.' },
        { category: 'Content and legal', severity: 'high', statement: 'External publication can create attribution, copyright, confidentiality, advertising, defamation, or regulatory exposure.', mitigation: 'Keep autonomous publishing disabled and require a named human reviewer plus publication receipt.' },
        { category: 'Database', severity: 'medium', statement: 'A migration can fail, drift from production, or create duplicate publication state.', mitigation: 'Review SQL, snapshot current schema, test idempotency, record checksum, and verify rollback/forward-fix steps.' },
        { category: 'Canonical URL', severity: 'medium', statement: 'An incorrect base URL can misattribute content and damage search indexing.', mitigation: 'Require an HTTPS allowlisted origin and preview the exact final canonical URL.' },
        { category: 'External side effect', severity: 'medium', statement: 'Published content may be cached, syndicated, or indexed even after deletion.', mitigation: 'Use draft/private mode for the first test and treat final publication as only partially reversible.' },
      ],
      prerequisites: ['Provider-issued token owner and account are identified.', 'Token permissions and expiration/rotation policy are documented.', 'Canonical base URL is HTTPS and allowlisted.', 'Migration SQL, checksum, backup, and rollback or forward-fix plan are attached.', 'CADE_PUBLISH_AUTONOMOUS is verified false in production.'],
      missingEvidence: ['Token scope/owner attestation', 'Exact canonical base URL preview', 'Migration diff and rollback evidence', 'Named editorial reviewer and content policy', 'Dry-run result and monitoring owner'],
      verification: ['Secret exists in the deployment vault and is absent from git/logs.', 'Provider identity and least-privilege scope test succeeds.', 'Migration table/index checks and ledger receipt succeed.', 'Dry-run creates one idempotent draft with the correct canonical URL.', 'Audit log records reviewer, content digest, provider response, and rollback path.'],
      rollback: 'Revoke/rotate the Medium token, disable the integration, restore the previous base URL, and use the reviewed migration rollback or forward-fix. Already published or syndicated content may not be fully retractable.',
      reversibility: 'partially_reversible',
      blastRadius: 'Tomorrow production publishing, the connected Medium account, publication metadata, and public canonical links; no other portfolio project should inherit the credential.',
      recommendation: 'APPROVE WITH CONDITIONS',
      confidence: 88,
      denyMeaning: 'No production state changes. Medium publishing remains unavailable and dependent recovery tasks stay paused; drafting and human copy/paste publishing can continue.',
      material: true,
      source: 'derived',
      options: [],
    }
  }

  const risks: DecisionRisk[] = []
  const prerequisites: string[] = []
  const missingEvidence: string[] = []
  const proposedChanges: string[] = []
  if (secret) {
    proposedChanges.push('Provision or change a protected credential outside source control.')
    risks.push({ category: 'Credential security', severity: 'high', statement: 'Credential exposure or excess scope could grant unintended access.', mitigation: 'Use the approved vault, least privilege, masking, rotation, and revocation verification.' })
    prerequisites.push('Credential owner, scope, storage destination, expiration, and revocation path are documented.')
    missingEvidence.push('Credential-scope and vault-placement evidence')
  }
  if (oauth) {
    proposedChanges.push('Authorize an external account connection and delegated permissions.')
    risks.push({ category: 'Delegated access', severity: 'high', statement: 'OAuth consent may expose account data or permit external actions.', mitigation: 'Show requested scopes, tenant/account, data flow, retention, and disconnect behavior.' })
    missingEvidence.push('Exact OAuth scopes and account/tenant identity')
  }
  if (migration) {
    proposedChanges.push('Change the production database schema or stored state.')
    risks.push({ category: 'Database', severity: 'high', statement: 'Migration failure or schema drift can affect production availability and data integrity.', mitigation: 'Require reviewed SQL, backup, compatibility check, checksum, verification, and rollback/forward-fix plan.' })
    prerequisites.push('Migration diff and production compatibility review are complete.')
    missingEvidence.push('Migration verification and recovery plan')
  }
  if (deploy) {
    proposedChanges.push('Change a deployed production service or configuration.')
    risks.push({ category: 'Availability', severity: 'medium', statement: 'A release can introduce errors or service interruption.', mitigation: 'Require build/test evidence, canary or preview, health checks, owner, and rollback trigger.' })
    missingEvidence.push('Build, test, preview, and rollback receipts')
  }
  if (legal) {
    risks.push({ category: 'Legal authority', severity: 'critical', statement: 'The decision may create or waive legal rights or obligations.', mitigation: 'Identify the exact instrument, authority, parties, jurisdiction, alternatives, and counsel basis.' })
    missingEvidence.push('Legal instrument, authority, jurisdiction, and counsel rationale')
  }
  if (!risks.length) risks.push({ category: 'Operational', severity: 'low', statement: 'The downstream effect is not fully described.', mitigation: 'Attach a bounded execution plan and verification receipt.' })

  const recommendation = legal ? 'ESCALATE' : missingEvidence.length ? 'HOLD FOR EVIDENCE' : informational ? 'ACKNOWLEDGE' : 'APPROVE WITH CONDITIONS'
  return {
    classification: [secret && 'Credential', oauth && 'OAuth', migration && 'Migration', deploy && 'Deployment', legal && 'Legal'].filter(Boolean).join(' + ') || 'Operational authorization',
    plainLanguage: a.why || a.detail || 'A protected orchestration action needs an explicit decision.',
    proposedChanges: proposedChanges.length ? proposedChanges : [a.draft || a.title || 'Execute the described protected action.'],
    authorizationMeaning: 'Approval grants permission to attempt only the described action within the stated scope. Approval is not evidence that execution succeeded.',
    completionMeaning: 'Completion requires an execution receipt, verification results, actor identity, timestamp, changed resources, and rollback status.',
    rewards: [a.value || 'Unblocks the dependent workflow after verified completion.'],
    risks,
    prerequisites,
    missingEvidence,
    verification: ['Record who executed the action and when.', 'Attach before/after state and independent success checks.', 'Confirm no permission, data, or project exceeded the approved scope.'],
    rollback: material ? 'A tested rollback or revocation path must be attached before execution.' : 'Return to the prior state and record the reversal.',
    reversibility: legal ? 'hard_to_reverse' : (publishing || migration || deploy ? 'partially_reversible' : 'reversible'),
    blastRadius: a.project ? `Limited to ${a.project} unless the execution plan explicitly identifies shared infrastructure.` : 'Unknown until affected projects, accounts, data, and infrastructure are listed.',
    recommendation,
    confidence: Math.max(35, 82 - missingEvidence.length * 9 - (legal ? 12 : 0)),
    denyMeaning: a.risk || 'No protected state changes; dependent work remains paused until the request is revised or approved.',
    material,
    source: 'derived',
    options: [],
  }
}

export function canBulkApprove(approvals: ApprovalLike[]): boolean {
  return approvals.length > 0 && approvals.every(approval => !deriveDecisionBrief(approval).material)
}
