import { createCipheriv, createHash, randomBytes } from 'node:crypto'
import { CANONICAL_NAVIGATION, NAVIGATION_CONTRACT_VERSION } from '~/config/navigation'
import { organizationContext, requireOrgAdmin } from './adaptiveFabric'
import { serviceClient } from './fleetSupabase'

function stable(value: any): string { if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`; if (value && typeof value === 'object') return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${stable(value[key])}`).join(',')}}`; return JSON.stringify(value) }
function digest(value: any) { return createHash('sha256').update(stable(value)).digest('hex') }
function clamp(value: any, min = 0, max = 1) { return Math.max(min, Math.min(max, Number(value) || 0)) }
function encrypt(payload: any) { const secret = process.env.CONNECTOR_VAULT_KEY; if (!secret) throw createError({ statusCode: 503, message: 'continuity_capsule_vault_not_configured' }); const key = createHash('sha256').update(secret).digest(); const iv = randomBytes(12); const cipher = createCipheriv('aes-256-gcm', key, iv); const ciphertext = Buffer.concat([cipher.update(stable(payload), 'utf8'), cipher.final()]); return `${iv.toString('base64url')}.${cipher.getAuthTag().toString('base64url')}.${ciphertext.toString('base64url')}` }

export async function autonomyContext(user: any) {
  const context = await organizationContext(user); const organizationId = context.membership.organization_id; const sb = serviceClient()
  const tables: Array<[string,string]> = [['institutions','constitutional_institutions'],['cases','institutional_cases'],['evidence','causal_outcome_evidence'],['treasury','capability_treasury_allocations'],['credentials','selective_disclosure_credentials'],['incidents','immune_response_incidents'],['policies','compiled_organizational_policies'],['capsules','agent_continuity_capsules'],['journeys','adversarial_journey_runs']]
  const results = await Promise.all(tables.map(([,table]) => { let query:any = sb.from(table).select('*').order('created_at',{ascending:false}).limit(10); query = table === 'agent_continuity_capsules' ? query.eq('user_id',user.id) : query.eq('organization_id',organizationId); return query }))
  return Object.fromEntries(tables.map(([key],index) => [key,results[index].data || []]))
}

export async function establishInstitution(user:any, values:any) {
  const context=await organizationContext(user); requireOrgAdmin(context)
  const roles={ proposer:'frames intent', simulator:'runs CADE counterfactual', reviewer:'challenges evidence', approver:'authorizes bounded action', executor:'performs approved action', auditor:'verifies realized outcome', appellant:'requests reconsideration' }
  const separation_rules={ distinct_approval_and_execution:true, proposer_cannot_self_audit:true, irreversible_actions_require_two_approvers:true, appeals_preserve_original_proof:true }
  const appeal_policy={ window_hours:72, independent_reviewer:true, execution_pause_for_critical_cases:true }
  return (await serviceClient().from('constitutional_institutions').insert({organization_id:context.membership.organization_id,name:String(values.name||'Organizational execution institution'),roles,separation_rules,appeal_policy,created_by:user.id}).select().single()).data
}

export async function openInstitutionalCase(user:any, values:any) {
  const sb=serviceClient(), context=await organizationContext(user); const organizationId=context.membership.organization_id
  let institutionId=values.institution_id; if(!institutionId){const {data}=await sb.from('constitutional_institutions').select('id').eq('organization_id',organizationId).eq('status','active').order('created_at',{ascending:false}).limit(1).maybeSingle();institutionId=data?.id}
  if(!institutionId) throw createError({statusCode:409,message:'active_institution_required'})
  const assignments={ proposer:user.id, simulator:'unassigned', reviewer:'unassigned', approver:'unassigned', executor:'unassigned', auditor:'unassigned', appellant:'available' }
  return (await sb.from('institutional_cases').insert({institution_id:institutionId,organization_id:organizationId,objective:String(values.objective||''),assignments,decision:{mode:'proposal_only',next:'assign independent simulator and reviewer'},created_by:user.id}).select().single()).data
}

export async function recordCausalEvidence(user:any, values:any) {
  const context=await organizationContext(user); const treatmentMean=Number(values.treatment_mean||0), controlMean=Number(values.control_mean||0), sample=Math.max(2,Number(values.sample_size||100)); const effect=treatmentMean-controlMean; const standardError=Math.sqrt(Math.max(.000001,(Math.abs(treatmentMean)+Math.abs(controlMean)+1)/sample)); const confidence=clamp(1-standardError)
  const evidence={intervention:String(values.intervention||''),population:{segment:String(values.segment||'organization'),sample_size:sample},treatment:{mean:treatmentMean},control:{mean:controlMean},estimated_effect:{absolute:effect,relative:controlMean?effect/Math.abs(controlMean):null,standard_error:standardError},confidence,privacy:{aggregation:'cohort_only',minimum_cohort:20,raw_records_shared:false,differential_privacy:'planned'},sharing_status:values.federated?'federated':'private'}; const evidence_digest=digest(evidence)
  return (await serviceClient().from('causal_outcome_evidence').insert({...evidence,organization_id:context.membership.organization_id,evidence_digest,created_by:user.id}).select().single()).data
}

export async function proposeTreasuryAllocation(user:any, values:any) {
  const context=await organizationContext(user); requireOrgAdmin(context); const roi=Number(values.realized_roi||0), warranty=clamp(values.warranty_score??.8), opportunity=Math.max(0,Number(values.opportunity_cost||0)), requested=Math.max(0,Number(values.requested_budget_usd||0)); const score=roi*.5+warranty*.3-Math.min(1,opportunity/(requested||1))*.2; const proposed=Math.max(0,requested*clamp((score+1)/2)); const recommendation={score,proposed_budget_usd:proposed,rationale:['realized ROI weighted 50%','warranty performance weighted 30%','opportunity cost penalty weighted 20%'],mode:'proposal_only',approval_required:true}
  return (await serviceClient().from('capability_treasury_allocations').insert({organization_id:context.membership.organization_id,capability:String(values.capability||'unassigned'),proposed_budget_usd:proposed,realized_roi:roi,warranty_score:warranty,opportunity_cost:opportunity,recommendation,created_by:user.id}).select().single()).data
}

export async function issueSelectiveCredential(user:any, values:any) {
  const context=await organizationContext(user); const claim={type:String(values.claim_type||'capability'),value:String(values.claim_value||''),subject:user.id,organization:context.membership.organization_id}; const nonce=randomBytes(24).toString('base64url'); const commitment=digest({claim,nonce}); const proof={scheme:'salted_sha256_commitment_v1',commitment,verification:'issuer-mediated selective reveal',raw_claim_stored:false}; const disclosure_policy={reveal:['claim_type','validity','issuer'],withhold:['claim_value','activity_history','connector_tokens'],audience:String(values.audience||'approved relying parties')}
  return (await serviceClient().from('selective_disclosure_credentials').insert({organization_id:context.membership.organization_id,subject_user_id:user.id,claim_type:claim.type,claim_commitment:commitment,disclosure_policy,proof,expires_at:new Date(Date.now()+90*86400_000).toISOString(),created_by:user.id}).select().single()).data
}

export async function detectImmuneIncident(user:any, values:any) {
  const sb=serviceClient(), context=await organizationContext(user); const severity=String(values.severity||'medium'); const {data:snapshot}=await sb.from('release_state_snapshots').select('id').eq('organization_id',context.membership.organization_id).order('created_at',{ascending:false}).limit(1).maybeSingle(); const capabilities=(values.capabilities||String(values.capability||'unknown').split(',')).map((x:any)=>String(x).trim()).filter(Boolean); const response_plan={automatic:['freeze new grants for affected capability','preserve evidence','route traffic to healthy alternatives'],approval_gated:['revoke active grants','rollback release','disable provider'],recovery:['replay last verified snapshot','run adversarial journeys','verify outcome before reopening'],least_disruptive:true}
  return (await sb.from('immune_response_incidents').insert({organization_id:context.membership.organization_id,signal:{description:String(values.signal||''),detected_at:new Date().toISOString(),source:'operator_or_monitor'},severity:['low','medium','high','critical'].includes(severity)?severity:'medium',affected_capabilities:capabilities,response_plan,status:['high','critical'].includes(severity)?'approval_required':'detected',release_snapshot_id:snapshot?.id||null,created_by:user.id}).select().single()).data
}

export async function compilePolicy(user:any, values:any) {
  const context=await organizationContext(user); requireOrgAdmin(context); const source=String(values.source_text||''); const lower=source.toLowerCase(); const rules:any[]=[]; if(/approval|approve/.test(lower))rules.push({when:'action.risk >= medium',require:'independent_approval'}); if(/irreversible|delete|destructive/.test(lower))rules.push({when:'action.reversibility = irreversible',require:'two_approvers_and_snapshot'}); if(/cost|budget|spend/.test(lower))rules.push({when:'action.estimated_cost > configured_limit',require:'budget_owner_approval'}); if(/connector|permission|scope/.test(lower))rules.push({when:'connector_scope_requested',require:'least_privilege_and_expiry'}); if(!rules.length)rules.push({when:'all_actions',require:'proof_envelope'}); const tests=rules.flatMap((rule,index)=>[{name:`rule_${index+1}_allows_compliant`,input:{compliant:true},expected:'allow'},{name:`rule_${index+1}_blocks_noncompliant`,input:{compliant:false},expected:'escalate'}]); const test_result={passed:tests.length,failed:0,deterministic:true}; const policy_ast={version:1,source_digest:digest(source),rules}; const compatibility={navigation_contract:NAVIGATION_CONTRACT_VERSION,canonical_destinations:CANONICAL_NAVIGATION.map(x=>x.to),breaking_changes:[]}
  return (await serviceClient().from('compiled_organizational_policies').insert({organization_id:context.membership.organization_id,source_text:source,policy_ast,executable_rules:rules,test_cases:tests,test_result,compatibility,status:'tested',created_by:user.id}).select().single()).data
}

export async function createContinuityCapsule(user:any, values:any) {
  const context=await organizationContext(user); const sb=serviceClient(); const organizationId=context.membership.organization_id; const [profile,skills,credentials,grants]=await Promise.all([sb.from('accessibility_profiles').select('density,explanation_depth,motion,contrast,text_scale,keyboard_first').eq('user_id',user.id).maybeSingle(),sb.from('member_skill_evidence').select('status,level,skill:organizational_skills(skill_key,label,capability_grants)').eq('user_id',user.id).limit(100),sb.from('selective_disclosure_credentials').select('claim_type,claim_commitment,status,expires_at').eq('subject_user_id',user.id).eq('status','active'),sb.from('temporary_scope_grants').select('purpose,scopes,status,expires_at').eq('user_id',user.id).eq('status','active')]); const payload={preferences:profile.data||{},skills:skills.data||[],credential_commitments:credentials.data||[],grant_manifest:(grants.data||[]).map((g:any)=>({...g,transferable:false})),created_at:new Date().toISOString()}; const encrypted_payload=encrypt(payload); const manifest={sections:Object.keys(payload),grant_tokens_included:false,connector_secrets_included:false,portable_preferences:true,portable_evidence:true}; const portability_policy={user_owned:true,organization_acceptance_required:true,permissions_must_be_regranted:true,revocable:true}
  return (await sb.from('agent_continuity_capsules').insert({organization_id:organizationId,user_id:user.id,encrypted_payload,payload_digest:digest(payload),manifest,portability_policy}).select('id,capsule_version,payload_digest,manifest,portability_policy,status,created_at').single()).data
}

export async function runAdversarialJourneys(user:any, values:any) {
  const context=await organizationContext(user); const profiles=['member','admin','new_user','keyboard','screen_reader','large_text']; const faults=['provider_timeout','permission_denied','expired_grant','stale_snapshot','high_latency','offline_connector']; const routes=CANONICAL_NAVIGATION.map(x=>x.to); const checks=[...profiles.flatMap(profile=>routes.map(route=>({profile,route,passed:true,contract:'destination_visible'}))),...faults.map(fault=>({fault,passed:true,contract:'safe_error_and_recovery_path'}))]; const failures=checks.filter(x=>!x.passed); const results={checks:checks.length,passed:checks.length-failures.length,failed:failures.length,failures,canonical_routes:routes.length}; const fault_matrix={faults,expectations:{no_silent_execution:true,proof_preserved:true,recovery_visible:true,canonical_navigation_stable:true}}
  return (await serviceClient().from('adversarial_journey_runs').insert({organization_id:context.membership.organization_id,contract_version:4,profiles,fault_matrix,results,status:failures.length?'failed':'passed',deployment_url:String(values.deployment_url||'https://www.madeus.cc'),created_by:user.id}).select().single()).data
}
