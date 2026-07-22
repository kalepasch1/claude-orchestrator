export interface OrchestratorCapability {
  slug: string
  icon: string
  eyebrow: string
  name: string
  domain: string
  summary: string
  actions: string[]
  keywords: string[]
  outcomes: string[]
}

export const ORCHESTRATOR_CAPABILITIES: OrchestratorCapability[] = [
  { slug: 'engineering-orchestrator', icon: '↗', eyebrow: 'Build & ship', name: 'Engineering', domain: 'engineering', summary: 'Build products, fix defects, improve systems, and ship verified releases.', actions: ['Build a feature', 'Repair production', 'Improve performance'], keywords: ['code', 'software', 'web', 'mobile', 'api', 'bug', 'deploy'], outcomes: ['Working implementation', 'Test and QA evidence', 'Verified release'] },
  { slug: 'design-orchestrator', icon: '✦', eyebrow: 'Create & refine', name: 'Design + Creative', domain: 'product-design', summary: 'Design interfaces, brands, graphics, motion, campaigns, and production-ready derivatives.', actions: ['Design a product', 'Create a campaign', 'Generate derivatives'], keywords: ['ui', 'ux', 'figma', 'brand', 'graphics', 'motion', 'video', 'artwork'], outcomes: ['Editable source', 'Visual variants', 'Accessibility and brand QA'] },
  { slug: 'business-orchestrator', icon: '◇', eyebrow: 'Operate & compound', name: 'Business Operations', domain: 'business', summary: 'Coordinate priorities, people, finance, vendors, legal obligations, and operating decisions across every company.', actions: ['Run the business', 'Plan the quarter', 'Coordinate a cross-company initiative'], keywords: ['business', 'operations', 'finance', 'people', 'vendor', 'company', 'portfolio', 'priority'], outcomes: ['Operating plan', 'Assigned execution', 'Decision and verification record'] },
  { slug: 'legal-orchestrator', icon: '§', eyebrow: 'Review & protect', name: 'Legal + Compliance', domain: 'legal-ops', summary: 'Review agreements, draft redlines, form entities, and run evidence-backed compliance work. Illuminati provides CADE gradient risk scoring, policy compilation, outcome-preserving alternatives, and execution gating for every agent action.', actions: ['Review a contract', 'Prepare a filing', 'Assess compliance', 'Score agent risk (CADE)', 'Compile a policy', 'Generate alternatives'], keywords: ['contract', 'redline', 'entity', 'filing', 'policy', 'risk', 'cade', 'compliance', 'illuminati', 'gateway', 'alternatives', 'evidence'], outcomes: ['Issue map', 'Reviewable redline', 'Evidence-backed recommendation', 'CADE risk score with confidence', 'Machine-readable policy controls', 'Ranked compliant alternatives'] },
  { slug: 'growth-orchestrator', icon: '↗', eyebrow: 'Find & grow demand', name: 'Marketing + Growth', domain: 'growth', summary: 'Develop positioning, content, campaigns, experiments, and measurable growth programs.', actions: ['Plan a launch', 'Create content', 'Improve conversion'], keywords: ['marketing', 'sales', 'campaign', 'seo', 'content', 'conversion'], outcomes: ['Campaign assets', 'Experiment plan', 'Measured growth result'] },
  { slug: 'research-orchestrator', icon: '◎', eyebrow: 'Understand & decide', name: 'Research + Strategy', domain: 'platform', summary: 'Investigate markets, competitors, users, and strategic choices with traceable evidence.', actions: ['Research a market', 'Compare options', 'Write a decision brief'], keywords: ['research', 'strategy', 'market', 'competitor', 'decision', 'evidence'], outcomes: ['Traceable sources', 'Decision model', 'Recommended next action'] },
  { slug: 'security-orchestrator', icon: '◇', eyebrow: 'Secure & govern', name: 'Security + Trust', domain: 'security', summary: 'Audit access, data, dependencies, policies, and remediation paths across the portfolio.', actions: ['Audit security', 'Fix access controls', 'Model threats'], keywords: ['security', 'privacy', 'access', 'audit', 'threat', 'dependency'], outcomes: ['Risk-ranked findings', 'Remediation plan', 'Verification proof'] },
]

export const capabilityBySlug = (slug: string) => ORCHESTRATOR_CAPABILITIES.find(item => item.slug === slug)

export const CAPABILITY_DESTINATIONS = ORCHESTRATOR_CAPABILITIES.flatMap(capability => [
  { label: capability.name, description: capability.summary, to: `/orchestrators/${capability.slug}`, keywords: capability.keywords },
  ...capability.actions.map(action => ({ label: action, description: `${capability.name} command`, to: `/orchestrators/${capability.slug}?intent=${encodeURIComponent(action)}`, keywords: [...capability.keywords, action.toLowerCase()] })),
])
