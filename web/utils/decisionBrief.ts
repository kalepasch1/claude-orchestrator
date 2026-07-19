export type DecisionRisk = { category: string; severity: 'low' | 'medium' | 'high' | 'critical'; statement: string; mitigation: string }

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
}

type ApprovalLike = Record<string, any>

const textOf = (a: ApprovalLike) => [a.kind, a.title, a.why, a.value, a.risk, a.detail, a.draft].filter(Boolean).join(' ').toLowerCase()
const includesAny = (text: string, terms: string[]) => terms.some(term => text.includes(term))

export function deriveDecisionBrief(a: ApprovalLike): DecisionBrief {
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
  }
}

export function canBulkApprove(approvals: ApprovalLike[]): boolean {
  return approvals.length > 0 && approvals.every(approval => !deriveDecisionBrief(approval).material)
}
