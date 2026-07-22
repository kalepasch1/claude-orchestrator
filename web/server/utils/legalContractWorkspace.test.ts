import { describe,expect,it } from 'vitest'
import { LEGAL_TEMPLATE_BY_KEY } from '../../config/legalContracts'
import { analyzeDraft,generateStructuredDraft } from './legalContractWorkspace'

describe('legal contract workspace',()=>{
  it('builds a versionable agreement from a prompt and facts',()=>{ const draft=generateStructuredDraft(LEGAL_TEMPLATE_BY_KEY.msa as any,{party_a:'Acme',party_b:'Beta',services:'Design',fees:'$10,000',term:'12 months',jurisdiction:'Delaware'},'Protect Acme while staying commercially balanced'); expect(draft.content.clauses.length).toBeGreaterThan(8); expect(draft.rendered).toContain('MASTER SERVICES AGREEMENT'); expect(draft.digest).toHaveLength(64) })
  it('makes missing business terms blocking findings',()=>{ const draft=generateStructuredDraft(LEGAL_TEMPLATE_BY_KEY.employment_agreement as any,{jurisdiction:'New York'},'Draft'); const result=analyzeDraft(LEGAL_TEMPLATE_BY_KEY.employment_agreement as any,draft.content,{coverage:{complete:true},review_reasons:['Local review']}); expect(result.cade.status).toBe('blocked'); expect(result.cade.findings.some((x:any)=>x.code==='missing_terms')).toBe(true) })
  it('never treats missing legal authority coverage as clear',()=>{ const draft=generateStructuredDraft(LEGAL_TEMPLATE_BY_KEY.nda_mutual as any,{party_a:'A',party_b:'B',purpose:'Discussion',term:'2 years',jurisdiction:'Example'},'Draft'); const result=analyzeDraft(LEGAL_TEMPLATE_BY_KEY.nda_mutual as any,draft.content,{coverage:{complete:false},review_reasons:[]}); expect(result.cade.status).toBe('blocked') })
})
