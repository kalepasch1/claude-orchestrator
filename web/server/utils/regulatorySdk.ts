/** Server-only client for Madeus authority policy. Never expose fleetSecret to a browser. */
export type RegulatoryCapabilityRequest = { key: string }
export type RegulatoryGateDecision = 'allow' | 'hold' | 'block'
export type RegulatoryGateReceipt = {
  decision: RegulatoryGateDecision
  receipt_digest: string
  policy_digest: string
  reasons: Array<{ capability: string; decision: RegulatoryGateDecision; reason: string }>
  required_actions: Array<{ capability: string; action: string }>
  expires_at: string
}

export function createRegulatoryPolicyClient(options: { baseUrl: string; fleetSecret: string; organizationId: string }) {
  if (!options.baseUrl || !options.fleetSecret || !options.organizationId) throw new Error('regulatory_sdk_configuration_required')
  const invoke = async <T>(body: Record<string, any>): Promise<T> => {
    const response = await fetch(`${options.baseUrl.replace(/\/$/, '')}/api/hivemind/regulatory/runtime`, {
      method: 'POST', headers: { 'content-type': 'application/json', 'x-fleet-secret': options.fleetSecret },
      body: JSON.stringify({ organization_id: options.organizationId, ...body }),
    })
    if (!response.ok) throw new Error(`regulatory_policy_error:${response.status}`)
    return response.json() as Promise<T>
  }
  return {
    deploymentGate(input: { project_ref: string; release_ref: string; jurisdiction?: string; requested_capabilities: RegulatoryCapabilityRequest[]; authority_evidence?: Record<string, any> }) {
      return invoke<RegulatoryGateReceipt>({ action: 'deployment_gate', ...input })
    },
    featurePolicy(input: { project_ref: string; jurisdiction?: string; features: string[] }) { return invoke({ action: 'feature_policy', ...input }) },
    agreementPolicy(input: { agreement_control_id: string; action: Record<string, any> }) { return invoke({ action: 'agreement_policy', ...input }) },
    recordEvidence(input: Record<string, any>) { return invoke({ action: 'evidence', ...input }) },
    measureObligation(input: Record<string, any>) { return invoke({ action: 'obligation', ...input }) },
    recordAuthoritySource(input: Record<string, any>) { return invoke({ action: 'authority_source', ...input }) },
    recordFeedbackOutcome(input: Record<string, any>) { return invoke({ action: 'feedback_outcome', ...input }) },
    recordLaunchTelemetry(input: Record<string, any>) { return invoke({ action: 'launch_telemetry', ...input, explicit_approval: false }) },
    attestProductBehavior(input: Record<string, any>) { return invoke({ action: 'product_attestation', ...input }) },
    compileLawControls(input: Record<string, any>) { return invoke({ action: 'compile_law', ...input }) },
    reportAuthorityDegradation(input: Record<string, any>) { return invoke({ action: 'immune_response', ...input }) },
    coordinateTransaction(input: Record<string, any>) { return invoke({ action: 'coordinate_transaction', ...input }) },
    createComplianceReceipt(input: Record<string, any>) { return invoke({ action: 'runtime_receipt', ...input }) },
    simulateCustomerOutcomes(input: Record<string, any>) { return invoke({ action: 'customer_outcome_twin', ...input }) },
    prepareAtomicTransaction(input: Record<string, any>) { return invoke({ action: 'atomic_transaction', ...input }) },
    verifyZkProof(input: Record<string, any>) { return invoke({ action: 'verify_zk_proof', ...input }) },
    recordCapacityPerformance(input: Record<string, any>) { return invoke({ action: 'capacity_performance', ...input }) },
  }
}
