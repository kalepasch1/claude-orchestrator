import{organizationContext,requireOrgAdmin}from'../../../utils/adaptiveFabric'
import{requireConnectorUser}from'../../../utils/connectorFabric'
import{resolveCredential}from'../../../utils/businessProviderFabric'
import{runSandboxConformance}from'../../../utils/providerIntelligence'
import{runSyntheticSchemaConformance,verifyAdapterCapabilityProof}from'../../../utils/providerAutonomy'
import{fuzzProviderLifecycle}from'../../../utils/providerSovereignty'
import{appendTransparencyEntry,inferAndPersistStateMachines}from'../../../utils/providerSovereigntyCompoundingStore'
import{serviceClient}from'../../../utils/fleetSupabase'

function authHeaders(manifest:any,credential:any){const headers:Record<string,string>={};for(const auth of manifest.auth||[]){if(auth.type==='http'&&auth.scheme==='bearer'){const token=credential.access_token||credential.api_key;if(token)headers.authorization=`Bearer ${token}`}else if(auth.type==='http'&&auth.scheme==='basic'){const username=credential.username||credential.account_id,password=credential.password||credential.license_key;if(username&&password)headers.authorization=`Basic ${Buffer.from(`${username}:${password}`).toString('base64')}`}else if(auth.type==='apiKey'){const value=credential[auth.key]||credential.api_key;if(value)headers[auth.name]=String(value)}}return headers}

export default defineEventHandler(async event=>{
 const user=await requireConnectorUser(event),context=await organizationContext(user);requireOrgAdmin(context)
 const body=await readBody<any>(event),sb=serviceClient(),org=context.membership.organization_id
 const{data:adapter}=await sb.from('provider_adapter_manifests').select('*').eq('id',String(body.adapter_id||'')).eq('organization_id',org).eq('status','conformance_pending').maybeSingle()
 if(!adapter)throw createError({statusCode:404,message:'pending_adapter_not_found'})
 const{data:proofRow}=await sb.from('provider_adapter_capability_proofs').select('*').eq('adapter_id',adapter.id).eq('verified',true).limit(1).maybeSingle()
 if(!proofRow)throw createError({statusCode:409,message:'verified_capability_proof_required'})
 verifyAdapterCapabilityProof(adapter.manifest,proofRow)
 const synthetic=runSyntheticSchemaConformance(adapter.manifest,Number(body.synthetic_case_limit||200)),operations=(adapter.manifest.operations||[]).map((x:any)=>String(x.operation_id||x.operationId||x.id)).filter(Boolean),fuzzRuns=operations.map((operation:string)=>fuzzProviderLifecycle(adapter.provider,operation,`${adapter.spec_digest}:${operation}`,Number(body.fuzz_scenarios||250))),machines=await inferAndPersistStateMachines(org,adapter,Array.isArray(body.lifecycle_traces)?body.lifecycle_traces:[])
 const{data:account}=await sb.from('connector_accounts').select('*').eq('organization_id',org).eq('provider',adapter.provider).eq('environment','sandbox').eq('status','connected').limit(1).maybeSingle()
 if(!account)throw createError({statusCode:409,message:'connected_sandbox_provider_required'})
 const credential=await resolveCredential(account,org),auth=authHeaders(adapter.manifest,credential)
 const result=await runSandboxConformance(adapter.manifest,Array.isArray(body.tests)?body.tests:[],async request=>{const response:any=await $fetch.raw(request.url,{method:request.method,headers:{...request.headers,...auth},body:request.body,timeout:30000,ignoreResponseError:true});return{status:response.status}})
 const active=result.status==='passed'&&synthetic.status==='passed'&&fuzzRuns.length>0&&fuzzRuns.every((x:any)=>x.status==='passed')&&machines.length>0&&machines.every((x:any)=>x.status==='verified')
 const[{data:run,error},syntheticInsert,fuzzInsert]=await Promise.all([sb.from('provider_adapter_conformance_runs').insert({organization_id:org,adapter_id:adapter.id,environment:'sandbox',tests:result.tests,passed:result.passed,failed:result.failed,status:result.status,evidence_digest:result.evidence_digest}).select().single(),sb.from('provider_synthetic_sandbox_runs').insert({organization_id:org,adapter_id:adapter.id,case_count:synthetic.case_count,passed:synthetic.passed,failed:synthetic.failed,coverage:synthetic.coverage,evidence_digest:synthetic.evidence_digest,status:synthetic.status}),sb.from('provider_lifecycle_fuzz_runs').insert(fuzzRuns.map((f:any)=>({organization_id:org,adapter_id:adapter.id,provider:adapter.provider,operation:f.operation,seed:f.seed,scenarios:f.scenarios,transitions:f.transitions,invariant_violations:f.invariant_violations,coverage:f.coverage,evidence_digest:f.evidence_digest,status:f.status})))])
 if(error||syntheticInsert.error||fuzzInsert.error)throw createError({statusCode:500,message:'conformance_result_persistence_failed'})
 await sb.from('provider_adapter_manifests').update({status:active?'active':'rejected',activated_at:active?new Date().toISOString():null}).eq('id',adapter.id)
 await appendTransparencyEntry(org,'adapter_conformance',adapter.spec_digest,{live:result.evidence_digest,synthetic:synthetic.evidence_digest,fuzz:fuzzRuns.map((x:any)=>x.evidence_digest),machines:machines.map((x:any)=>x.machine_digest),active})
 return{run,synthetic:{status:synthetic.status,case_count:synthetic.case_count,coverage:synthetic.coverage},lifecycle_fuzz:{runs:fuzzRuns.length,passed:fuzzRuns.filter((x:any)=>x.status==='passed').length},state_machines:{runs:machines.length,verified:machines.filter((x:any)=>x.status==='verified').length},capability_proof:proofRow.proof_digest,adapter_status:active?'active':'rejected'}
})
