import { describe,expect,it } from 'vitest'
import { compileJurisdictionalPolicy } from './jurisdictionalPolicy'

describe('jurisdictional policy compiler',()=>{
  it('pins verified sources to an effective date',()=>{ const result=compileJurisdictionalPolicy({jurisdiction:'Example',domains:['commercial'],as_of:'2026-07-15',sources:[{id:'1',jurisdiction:'Example',domain:'commercial',title:'Authority',effective_from:'2026-01-01',status:'verified',rules:{requirements:[{id:'written_notice'}]}}]}); expect(result.coverage.complete).toBe(true); expect(result.compiled_rules[0].source_id).toBe('1'); expect(result.as_of).toBe('2026-07-15') })
  it('requires professional review when authority coverage is missing',()=>{ const result=compileJurisdictionalPolicy({jurisdiction:'Unknown',domains:['commercial'],sources:[]}); expect(result.professional_review_required).toBe(true); expect(result.coverage.complete).toBe(false) })
  it('always routes employment issuance to local review',()=>{ const result=compileJurisdictionalPolicy({jurisdiction:'Example',domains:['employment'],sources:[{id:'1',jurisdiction:'Example',domain:'employment',title:'Authority',effective_from:'2020-01-01',status:'verified'}]}); expect(result.review_reasons.join(' ')).toContain('employment counsel') })
  it('changes its digest when a nested requirement changes',()=>{ const base={jurisdiction:'Example',domains:['commercial'],sources:[{id:'1',jurisdiction:'Example',domain:'commercial',title:'Authority',effective_from:'2020-01-01',status:'verified',rules:{requirements:[{id:'a',value:1}]}}]}; const changed=structuredClone(base); changed.sources[0].rules.requirements[0].value=2; expect(compileJurisdictionalPolicy(base as any).digest).not.toBe(compileJurisdictionalPolicy(changed as any).digest) })
})
