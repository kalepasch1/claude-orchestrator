export type BusinessDomain = 'workforce' | 'finance' | 'creative' | 'operations'
export type BusinessRisk = 'low' | 'medium' | 'high'
export interface BusinessCapability { id: string; domain: BusinessDomain; name: string; summary: string; outcome: string; risk: BusinessRisk; action: string; requires: string[] }
export const BUSINESS_DOMAINS = [
  { id: 'operations' as const, label: 'Command', icon: '◈', summary: 'One prioritized operating plan across every business line.' },
  { id: 'workforce' as const, label: 'People', icon: '○', summary: 'Consent-first onboarding, agreements, capacity, benefits, and development.' },
  { id: 'finance' as const, label: 'Money', icon: '$', summary: 'Expenses, revenue, payments, cash, controls, and review-ready tax strategy.' },
  { id: 'creative' as const, label: 'Studio', icon: '✦', summary: 'Motion, Photoshop-class image editing, 3D, and governed production.' },
] as const
export const BUSINESS_CAPABILITIES: BusinessCapability[] = [
  { id: 'operating-plan', domain: 'operations', name: 'Autonomous operating plan', summary: 'Continuously rank work by causal value, urgency, dependencies, risk, and attention cost.', outcome: 'A proof-backed next-best-action plan', risk: 'medium', action: 'operating_plan', requires: [] },
  { id: 'line-health', domain: 'operations', name: 'Business-line health', summary: 'Detect constraint, margin, delivery, compliance, and customer-risk changes before they become incidents.', outcome: 'Exception-only operating brief', risk: 'low', action: 'business_health', requires: [] },
  { id: 'onboard', domain: 'workforce', name: 'Employee onboarding', summary: 'Create a role-specific, jurisdiction-aware onboarding plan and cross-populate the legal evidence pack.', outcome: 'Onboarding case + governed NDA draft', risk: 'high', action: 'employee_onboarding', requires: ['employee_name', 'employee_email', 'role_title', 'jurisdiction'] },
  { id: 'capacity', domain: 'workforce', name: 'Capacity & wellbeing', summary: 'Use employee-controlled and cohort signals to improve workload, recovery, staffing, and benefits without surveillance scoring.', outcome: 'Team intervention proposal', risk: 'medium', action: 'capacity_review', requires: [] },
  { id: 'nda', domain: 'workforce', name: 'NDA & employment documents', summary: 'Draft from approved clauses, check jurisdiction and policy, collect approvals, issue, sign, and retain evidence.', outcome: 'Review-ready document package', risk: 'high', action: 'nda_draft', requires: ['employee_name', 'employee_email', 'jurisdiction'] },
  { id: 'expense', domain: 'finance', name: 'Expense intelligence', summary: 'Normalize transactions and receipts, detect duplicates and policy exceptions, and prepare auditable categorization.', outcome: 'Exception-focused expense review', risk: 'medium', action: 'expense_review', requires: [] },
  { id: 'cash', domain: 'finance', name: 'Cash & revenue command', summary: 'Unify income, invoices, payments, obligations, runway, and business-line contribution.', outcome: 'Rolling cash and value forecast', risk: 'medium', action: 'cash_forecast', requires: [] },
  { id: 'tax', domain: 'finance', name: 'Tax opportunity workbench', summary: 'Find evidence-backed timing, entity, deduction, credit, nexus, and compliance opportunities for qualified review.', outcome: 'Advisor-ready opportunity dossier', risk: 'high', action: 'tax_strategy', requires: ['jurisdiction'] },
  { id: 'motion', domain: 'creative', name: 'AI motion production', summary: 'Route storyboards, keyframes, animation, video, voice, localization, and QA across connected vendors.', outcome: 'Editable motion package + provenance', risk: 'medium', action: 'creative_motion', requires: ['brief'] },
  { id: 'photoshop', domain: 'creative', name: 'Layered image studio', summary: 'Generate, mask, fill, relight, retouch, composite, resize, and export through Adobe and best-fit image providers.', outcome: 'Layer-aware source + production derivatives', risk: 'medium', action: 'creative_image', requires: ['brief'] },
  { id: '3d', domain: 'creative', name: '3D & spatial studio', summary: 'Generate, texture, remesh, rig, animate, review, and export assets with runtime-specific LODs.', outcome: 'Production 3D package + QA manifest', risk: 'medium', action: 'creative_3d', requires: ['brief'] },
]
export const BUSINESS_CAPABILITY_BY_ACTION = Object.fromEntries(BUSINESS_CAPABILITIES.map(item => [item.action, item]))
