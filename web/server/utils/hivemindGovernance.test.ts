import {describe,expect,it} from 'vitest'
import {computeAttribution,computeSystemicRisk,forecastPrivacy} from './hivemindGovernance'
import {classifyFailureEvidence,computeCreditAccount,evaluateLicensePolicy,simulateConstitution} from './hivemindControlPlane'
describe('hivemind network governance',()=>{it('forecasts option loss before spending privacy budget',()=>{const x=forecastPrivacy({fields:['pattern','outcomes','verification'],audience:'public'},60);expect(x.scenarios).toHaveLength(4);expect(x.scenarios[3].projected_budget).toBeLessThan(60);expect(x.option_value_score).toBeLessThanOrEqual(100)});it('allocates all credits across separated contributors',()=>{const rows=computeAttribution({credit_cents:1000,participants:[{type:'author',ref:'a',weight:2},{type:'verifier',ref:'b',weight:1},{type:'adapter',ref:'c',weight:1}]});expect(rows.reduce((n:number,x:any)=>n+x.credit_cents,0)).toBe(1000);expect(rows[0].credit_cents).toBe(500)});it('surfaces concentrated cascading risk',()=>{const x=computeSystemicRisk({contributions:[{id:'a',title:'A',reuse_count:8},{id:'b',title:'B',reuse_count:1}],signals:[{severity:'high'}]});expect(x.concentration_score).toBeGreaterThan(70);expect(x.cascades[0].adopters_at_risk).toBe(8)})})

describe('hivemind outcome control plane',()=>{
  it('denies execution when a machine license boundary is exceeded',()=>{
    const result=evaluateLicensePolicy({status:'active',expires_at:'2099-01-01',scopes:['execute'],execution_limits:{max_projects:1,max_executions_per_month:10}},{scopes:['execute'],projects:2,monthly_executions:3})
    expect(result.passed).toBe(false)
    expect(result.reasons).toContain('project_limit_exceeded')
  })
  it('clears credits behind a risk reserve and excludes expired value',()=>{
    const account=computeCreditAccount([{amount_cents:10000,status:'available',event_type:'verified_reuse'},{amount_cents:5000,status:'available',event_type:'quality_bonus',expires_at:'2020-01-01'}],'standard',new Date('2026-01-01'))
    expect(account.available_cents).toBe(9000)
    expect(account.reserved_cents).toBe(1000)
    expect(account.expired_cents).toBe(5000)
  })
  it('separates a context mismatch from a portable failure',()=>{
    const result=classifyFailureEvidence({problem_class:'latency',attempted_pattern:'global cache',aggregate_result:{sample_size:24,effect:0},verification:{independent:true},boundary_conditions:{stage:'enterprise',runtime:'edge',constraints:['regulated']}})
    expect(result.classification).toBe('context_mismatch')
  })
  it('holds broad rights-sensitive constitutional changes for revision',()=>{
    const result=simulateConstitution({policy_domain:'privacy',organization_id:'org',proposed_policy:{rule:'allow all data permanently'}},[])
    expect(result.recommendation).toBe('revise')
    expect(result.minority_safeguards.privacy_floor).toBe(true)
  })
})
