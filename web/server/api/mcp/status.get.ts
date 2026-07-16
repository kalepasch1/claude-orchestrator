export default defineEventHandler(() => {
  return {
    stats: { totalTools: 47, activeGroups: 5, totalListings: 6 },
    groups: [
      { id: 'apparently', label: 'Apparently', icon: '◈', category: 'Gaming RegTech', toolCount: 10, enabled: true, description: 'Gaming licensing, legal review, compliance checks, disclosure, and jurisdiction intelligence.', pricingSummary: ['$5-$250/call', 'AI-heavy'] },
      { id: 'pareto', label: 'Pareto 2080', icon: '⊕', category: 'Personal Finance', toolCount: 12, enabled: true, description: 'Retirement simulation, tax optimization, portfolio management, treasury, and subscription sweeps.', pricingSummary: ['$0.50-$3/call', 'Pure-logic'] },
      { id: 'smarter', label: 'Smarter', icon: '⚖', category: 'Legal Ops', toolCount: 12, enabled: true, description: 'Negotiation copilot, contract analysis, counterparty intel, research dossiers, and engagement drafting.', pricingSummary: ['$5-$50/call', 'AI-heavy'] },
      { id: 'tomorrow', label: 'Tomorrow', icon: '◎', category: 'OTC Derivatives', toolCount: 10, enabled: true, description: 'Derivatives pricing, risk analytics, regulatory compliance, trade structuring, and market intelligence.', pricingSummary: ['$5-$100/call', 'AI-heavy'] },
      { id: 'orchestrator', label: 'Orchestrator', icon: '⌘', category: 'Cross-Vertical', toolCount: 3, enabled: true, description: 'Parallel execution, cross-vertical intelligence, and system health monitoring.', pricingSummary: ['$0-$20/call', 'Mixed'] },
    ],
    listings: [
      { id: 'gaming-regtech', icon: '◈', displayName: 'HereTomorrow Gaming RegTech', tagline: 'AI-powered gaming licensing and compliance across all US jurisdictions', pricingTier: 'enterprise' },
      { id: 'suptech-platform', icon: '§', displayName: 'Vigil SupTech Platform', tagline: 'Cross-vertical regulatory intelligence for gaming commissions and financial regulators', pricingTier: 'enterprise' },
      { id: 'personal-finance', icon: '⊕', displayName: 'Pareto Financial Intelligence', tagline: 'Retirement planning, tax optimization, and portfolio management', pricingTier: 'professional' },
      { id: 'legal-ops', icon: '⚖', displayName: 'Smarter Legal Ops', tagline: 'AI negotiation copilot and contract intelligence', pricingTier: 'enterprise' },
      { id: 'otc-derivatives', icon: '◎', displayName: 'Tomorrow Derivatives Suite', tagline: 'OTC derivatives pricing, risk, and regulatory compliance', pricingTier: 'enterprise' },
      { id: 'heretomorrow-full', icon: '⌘', displayName: 'HereTomorrow Complete', tagline: 'Full cross-vertical intelligence — gaming, finance, legal, and derivatives', pricingTier: 'enterprise' },
    ],
  }
})
