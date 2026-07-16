import type { AppSource, MarketplaceListing } from './types.js';

export const APP_SOURCES: Record<string, AppSource> = {
  apparently: {
    id: 'apparently', label: 'Apparently', baseUrl: 'https://apparently.heretomorrow.us',
    devUrl: 'http://localhost:3000', icon: '◈', category: 'Gaming RegTech',
    pricingTier: 'enterprise',
    costProfile: { aiCallsPerRequest: 6, avgLatencyMs: 12000, estimatedCostPerCall: 0.45 },
    repoPath: '/Users/kpasch/Documents/apparently',
    apiScanGlob: 'server/api/**/*.{ts,js}', engineScanGlob: 'server/engines/**/*.{ts,js}',
  },
  pareto: {
    id: 'pareto', label: 'Pareto 2080', baseUrl: 'https://pareto.heretomorrow.us',
    devUrl: 'http://localhost:3007', icon: '⊕', category: 'Personal Finance',
    pricingTier: 'professional',
    costProfile: { aiCallsPerRequest: 1, avgLatencyMs: 2000, estimatedCostPerCall: 0.02 },
    repoPath: '/Users/kpasch/Documents/pareto/2080',
    apiScanGlob: 'server/api/**/*.{ts,js}', engineScanGlob: 'server/utils/**/*.js',
  },
  smarter: {
    id: 'smarter', label: 'Smarter', baseUrl: 'https://smarter.heretomorrow.us',
    devUrl: 'http://localhost:3002', icon: '⚖', category: 'Legal Ops',
    pricingTier: 'enterprise',
    costProfile: { aiCallsPerRequest: 3, avgLatencyMs: 8000, estimatedCostPerCall: 0.35 },
    repoPath: '/Users/kpasch/Documents/smarter',
    apiScanGlob: 'server/api/**/*.{ts,js}', engineScanGlob: 'server/engines/**/*.{ts,js}',
  },
  tomorrow: {
    id: 'tomorrow', label: 'Tomorrow', baseUrl: 'https://tomorrow.heretomorrow.us',
    devUrl: 'http://localhost:3001', icon: '◎', category: 'OTC Derivatives',
    pricingTier: 'enterprise',
    costProfile: { aiCallsPerRequest: 4, avgLatencyMs: 10000, estimatedCostPerCall: 0.40 },
    repoPath: '/Users/kpasch/Documents/tomorrow',
    apiScanGlob: 'server/api/**/*.{ts,js}', engineScanGlob: 'server/engines/**/*.{ts,js}',
  },
  orchestrator: {
    id: 'orchestrator', label: 'Orchestrator', baseUrl: 'https://madeus.heretomorrow.us',
    devUrl: 'http://localhost:3005', icon: '⌘', category: 'Cross-Vertical Coordination',
    pricingTier: 'enterprise',
    costProfile: { aiCallsPerRequest: 0, avgLatencyMs: 500, estimatedCostPerCall: 0.01 },
    repoPath: '/Users/kpasch/Documents/beethoven/claude-orchestrator',
    apiScanGlob: 'web/server/api/**/*.ts', engineScanGlob: 'runner/**/*.py',
  },
};

export const MARKETPLACE_LISTINGS: MarketplaceListing[] = [
  { appId: 'apparently', displayName: 'HereTomorrow Gaming RegTech', tagline: 'AI-powered gaming licensing and compliance across all US jurisdictions', category: 'RegTech', pricingTier: 'enterprise', icon: '◈' },
  { appId: 'vigil', displayName: 'Vigil SupTech Platform', tagline: 'Cross-vertical regulatory intelligence for gaming commissions and financial regulators', category: 'SupTech', pricingTier: 'enterprise', icon: '§' },
  { appId: 'pareto', displayName: 'Pareto Financial Intelligence', tagline: 'Retirement planning, tax optimization, and portfolio management', category: 'FinTech', pricingTier: 'professional', icon: '⊕' },
  { appId: 'smarter', displayName: 'Smarter Legal Ops', tagline: 'AI negotiation copilot and contract intelligence', category: 'LegalTech', pricingTier: 'enterprise', icon: '⚖' },
  { appId: 'tomorrow', displayName: 'Tomorrow Derivatives Suite', tagline: 'OTC derivatives pricing, risk, and regulatory compliance', category: 'FinTech', pricingTier: 'enterprise', icon: '◎' },
  { appId: 'heretomorrow', displayName: 'HereTomorrow Complete', tagline: 'Full cross-vertical intelligence — gaming, finance, legal, and derivatives', category: 'Enterprise', pricingTier: 'enterprise', icon: '⌘' },
];

export const OWNER_EMAIL = 'kalepasch@gmail.com';
