export interface ConnectorOptimizationInput {
  provider: string
  connected: boolean
  configured: boolean
  samples: number
  succeeded: number
  qualityTotal: number
  costTotal: number
  policyIncidents: number
  capabilities: string[]
}

export interface ConnectorOptimization {
  provider: string
  score: number
  reliability: number
  averageQuality: number
  averageCostUsd: number
  recommendation: 'activate' | 'prefer' | 'observe' | 'deprioritize'
  reason: string
  capabilities: string[]
}

export function optimizeConnectors(inputs: ConnectorOptimizationInput[]): ConnectorOptimization[] {
  return inputs.map(input => {
    const reliability = input.samples ? input.succeeded / input.samples : input.connected || input.configured ? .9 : .55
    const averageQuality = input.samples ? input.qualityTotal / input.samples : input.connected || input.configured ? .8 : .6
    const averageCostUsd = input.samples ? input.costTotal / input.samples : 0
    const access = input.connected || input.configured ? 1 : .35
    const evidence = Math.min(1, input.samples / 20)
    const incidentPenalty = Math.min(.4, input.policyIncidents * .08)
    const costEfficiency = Math.max(0, 1 - averageCostUsd * 10)
    const score = Math.max(0, Math.min(100, Math.round((reliability * .32 + averageQuality * .23 + access * .2 + evidence * .1 + costEfficiency * .15 - incidentPenalty) * 100)))
    let recommendation: ConnectorOptimization['recommendation'] = 'observe'
    if (!(input.connected || input.configured) && score >= 55) recommendation = 'activate'
    else if ((input.connected || input.configured) && score >= 76) recommendation = 'prefer'
    else if ((input.connected || input.configured) && (score < 48 || input.policyIncidents >= 2)) recommendation = 'deprioritize'
    const reason = recommendation === 'activate'
      ? 'Strong capability coverage; connect only when an outcome requires it.'
      : recommendation === 'prefer'
        ? 'Best observed balance of reliability, quality, access, policy safety, and cost.'
        : recommendation === 'deprioritize'
          ? 'Observed value or policy safety is below the portfolio threshold.'
          : 'Keep in shadow mode until more realized-outcome evidence is available.'
    return { provider: input.provider, score, reliability, averageQuality, averageCostUsd, recommendation, reason, capabilities: input.capabilities }
  }).sort((a, b) => b.score - a.score || a.provider.localeCompare(b.provider))
}

